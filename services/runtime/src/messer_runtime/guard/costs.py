"""List-price cost of a model call, from ``model_prices`` (the same table and cache the gateway charges with)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from messer_common.pricing import MTOK

from .. import gateway


async def price_usage(model: str, usage: dict[str, Any]) -> Decimal:
    """Cost of ``usage`` at ``model``'s list price (0 when the model has no price)."""
    price = (await gateway._prices()).get(model)
    if price is None:
        return Decimal("0")
    return (
        Decimal(int(usage.get("input_tokens") or 0)) * price.input_per_mtok_usd
        + Decimal(int(usage.get("output_tokens") or 0)) * price.output_per_mtok_usd
        + Decimal(int(usage.get("cache_read_input_tokens") or 0)) * price.cache_read_per_mtok_usd
        + Decimal(int(usage.get("cache_creation_input_tokens") or 0)) * price.cache_write_per_mtok_usd
    ) / MTOK


async def has_price(model: str) -> bool:
    return model in await gateway._prices()
