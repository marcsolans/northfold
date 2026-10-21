"""Model tiers, Bedrock mapping and default prices loaded from config/models.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

Tier = Literal["fast", "standard", "powerful"]
TIERS: tuple[Tier, ...] = ("fast", "standard", "powerful")
DEMO_MODEL = "messer/demo"

_CONFIG_PATH = Path(__file__).parent / "config" / "models.yaml"


@dataclass(frozen=True, slots=True)
class PriceSeed:
    model: str
    provider: str
    display_name: str
    input: Decimal
    output: Decimal
    cache_read: Decimal
    cache_write: Decimal
    context_window: int | None


@lru_cache(maxsize=1)
def load_models_config() -> dict[str, Any]:
    with _CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def tier_model(tier: str) -> str:
    tiers = load_models_config()["tiers"]
    if tier not in tiers:
        raise ValueError(f"Unknown model tier: {tier}")
    return str(tiers[tier])


def resolve_model(model_or_tier: str | None, default_tier: str = "standard") -> str:
    """Accept a tier name ("fast"), a provider/model string, or None (default tier)."""
    if not model_or_tier:
        return tier_model(default_tier)
    if model_or_tier in TIERS:
        return tier_model(model_or_tier)
    if "/" not in model_or_tier:
        raise ValueError(f"Model must be a tier or a 'provider/model' string, got {model_or_tier!r}")
    return model_or_tier


def guard_models() -> tuple[str, str]:
    cfg = load_models_config()["guard"]
    return str(cfg["small"]), str(cfg["large"])


def composer_tier(role: str, mode: str = "standard") -> str:
    cfg = load_models_config()["composer"]
    if role == "architect":
        return str(cfg["architect"])
    return str(cfg["builders"].get(mode, "standard"))


def bedrock_region() -> str:
    return str(load_models_config()["bedrock"]["region"])


def bedrock_model_id(model: str) -> str | None:
    return load_models_config()["bedrock"]["models"].get(model)


def bedrock_allowed_regions() -> list[str]:
    return list(load_models_config()["bedrock"]["allowed_regions"])


def request_defaults(model: str) -> dict[str, Any]:
    return dict(load_models_config().get("request_defaults", {}).get(model, {}))


def price_seeds() -> list[PriceSeed]:
    seeds: list[PriceSeed] = []
    for row in load_models_config()["prices"]:
        model = str(row["model"])
        seeds.append(
            PriceSeed(
                model=model,
                provider=model.split("/", 1)[0],
                display_name=str(row.get("display_name", model)),
                input=Decimal(str(row["input"])),
                output=Decimal(str(row["output"])),
                cache_read=Decimal(str(row.get("cache_read", 0))),
                cache_write=Decimal(str(row.get("cache_write", 0))),
                context_window=row.get("context_window"),
            )
        )
    return seeds
