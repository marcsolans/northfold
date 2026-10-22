"""GET /api/v1/site/credits: public credit pricing for the website (value of a credit, margin, model rates)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import ModelPrice
from messer_common.models_config import TIERS, tier_model
from messer_common.pricing import usd_to_credits
from messer_common.settings import get_settings

from ..ratelimit import rate_limit

router = APIRouter(prefix="/site", tags=["website"])


class ModelRateOut(BaseModel):
    tier: str
    model: str
    display_name: str
    input_usd_per_mtok: str
    output_usd_per_mtok: str
    input_credits_per_mtok: str
    output_credits_per_mtok: str


class CreditPricingOut(BaseModel):
    credit_usd: str
    margin_pct: str
    models: list[ModelRateOut]


def _fmt(value: Decimal, places: str = "0.01") -> str:
    """Fixed-point string without trailing zeros (``"13"``, ``"0.1"``), never scientific notation."""
    text = format(value.quantize(Decimal(places), rounding=ROUND_HALF_UP), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@router.get("/credits", response_model=CreditPricingOut, dependencies=[Depends(rate_limit("site_credits", 120, 60))])
async def credit_pricing(response: Response) -> dict[str, Any]:
    """How credits are computed: model cost (from ``model_prices``) plus the configured margin."""
    settings = get_settings()
    tier_models = {tier: tier_model(tier) for tier in TIERS}
    async with system_session() as s:
        prices = {
            p.model: p
            for p in (
                await s.execute(select(ModelPrice).where(ModelPrice.model.in_(list(tier_models.values()))))
            ).scalars()
            if p.active
        }
    models: list[dict[str, str]] = []
    for tier, model in tier_models.items():
        price = prices.get(model)
        if price is None:
            continue
        models.append(
            {
                "tier": tier,
                "model": model,
                "display_name": price.display_name or model,
                "input_usd_per_mtok": _fmt(Decimal(price.input_per_mtok_usd), "0.0001"),
                "output_usd_per_mtok": _fmt(Decimal(price.output_per_mtok_usd), "0.0001"),
                "input_credits_per_mtok": _fmt(usd_to_credits(Decimal(price.input_per_mtok_usd))),
                "output_credits_per_mtok": _fmt(usd_to_credits(Decimal(price.output_per_mtok_usd))),
            }
        )
    response.headers["Cache-Control"] = "public, max-age=300"
    return {
        "credit_usd": _fmt(Decimal(str(settings.messer_credit_usd)), "0.000001"),
        "margin_pct": _fmt(Decimal(str(settings.messer_credit_margin)) * 100),
        "models": models,
    }
