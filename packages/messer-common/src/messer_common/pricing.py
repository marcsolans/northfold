"""Cost and credit computation from engine usage counters.

The engine reports usage as ``{"<provider>/<model>:<unit>": count}`` where unit is
one of ``input_text_tokens``, ``input_cached_tokens``, ``input_cache_write_tokens``,
``output_text_tokens`` (plus audio/long-context variants). Unknown units are
ignored for pricing but kept in the run's usage record.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .settings import get_settings

MTOK = Decimal(1_000_000)


@dataclass(slots=True)
class Price:
    input: Decimal
    output: Decimal
    cache_read: Decimal = Decimal("0")
    cache_write: Decimal = Decimal("0")


@dataclass(slots=True)
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(slots=True)
class CostBreakdown:
    total_usd: Decimal = Decimal("0")
    by_model: dict[str, Decimal] = field(default_factory=dict)
    usage: dict[str, ModelUsage] = field(default_factory=dict)

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens + u.cache_read_tokens + u.cache_write_tokens for u in self.usage.values())

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usage.values())

    @property
    def cache_read_tokens(self) -> int:
        return sum(u.cache_read_tokens for u in self.usage.values())


def _unit_bucket(unit: str) -> str | None:
    if unit.startswith("output"):
        return "output"
    if unit.startswith("input_cached") or unit.startswith("cache_read") or "cache_read" in unit:
        return "cache_read"
    if unit.startswith("input_cache_write") or "cache_creation" in unit or unit.startswith("ephemeral"):
        return "cache_write"
    if unit.startswith("input"):
        return "input"
    return None


def aggregate_usage(usage: dict[str, Any]) -> dict[str, ModelUsage]:
    per_model: dict[str, ModelUsage] = defaultdict(ModelUsage)
    for key, value in usage.items():
        if ":" not in key or not isinstance(value, int | float):
            continue
        model, unit = key.rsplit(":", 1)
        if "/" not in model:
            continue
        bucket = _unit_bucket(unit)
        if bucket is None:
            continue
        mu = per_model[model]
        count = int(value)
        if bucket == "input":
            mu.input_tokens += count
        elif bucket == "output":
            mu.output_tokens += count
        elif bucket == "cache_read":
            mu.cache_read_tokens += count
        else:
            mu.cache_write_tokens += count
    return dict(per_model)


def compute_cost(usage: dict[str, Any], prices: dict[str, Price]) -> CostBreakdown:
    breakdown = CostBreakdown(usage=aggregate_usage(usage))
    for model, mu in breakdown.usage.items():
        price = prices.get(model)
        if price is None:
            breakdown.by_model[model] = Decimal("0")
            continue
        cost = (
            Decimal(mu.input_tokens) * price.input
            + Decimal(mu.output_tokens) * price.output
            + Decimal(mu.cache_read_tokens) * price.cache_read
            + Decimal(mu.cache_write_tokens) * price.cache_write
        ) / MTOK
        breakdown.by_model[model] = cost
        breakdown.total_usd += cost
    breakdown.total_usd = breakdown.total_usd.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    return breakdown


def usd_to_credits(cost_usd: Decimal, margin: float | None = None) -> Decimal:
    """Credits charged for a raw model cost: (cost * (1 + margin)) / credit value."""
    settings = get_settings()
    m = Decimal(str(settings.messer_credit_margin if margin is None else margin))
    credit_usd = Decimal(str(settings.messer_credit_usd))
    credits = (cost_usd * (Decimal(1) + m)) / credit_usd
    return credits.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def credits_to_usd(credits: Decimal) -> Decimal:
    return (credits * Decimal(str(get_settings().messer_credit_usd))).quantize(Decimal("0.000001"))
