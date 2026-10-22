"""/api/v1/models — model tiers and the models an organization can use (with prices and EU availability)."""

from __future__ import annotations

import fnmatch
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import ModelPolicy, ModelPrice
from messer_common.models_config import DEMO_MODEL, TIERS, bedrock_model_id, tier_model

from ..deps import get_db, require_role

router = APIRouter(prefix="/models", tags=["models"])


class ModelOut(BaseModel):
    model: str
    display_name: str
    provider: str
    input_per_mtok_usd: Decimal
    output_per_mtok_usd: Decimal
    context_window: int | None
    eu_bedrock: bool
    allowed: bool
    tiers: list[str]


class ModelsOut(BaseModel):
    tiers: dict[str, str]
    models: list[ModelOut]


def _allowed(rules: dict[str, Any], model: str) -> bool:
    deny = [str(p) for p in rules.get("deny", []) or []]
    allow = [str(p) for p in rules.get("allow", []) or []]
    if any(fnmatch.fnmatch(model, p) for p in deny):
        return False
    return not allow or any(fnmatch.fnmatch(model, p) for p in allow)


@router.get("", response_model=ModelsOut)
async def list_models(principal: Principal = Depends(require_role("viewer")),
                      session: AsyncSession = Depends(get_db)) -> ModelsOut:
    tiers = {t: tier_model(t) for t in TIERS}
    policy = (await session.execute(select(ModelPolicy).where(ModelPolicy.org_id == principal.org_id))
              ).scalar_one_or_none()
    rules = policy.rules if policy else {}
    prices = (await session.execute(select(ModelPrice).order_by(ModelPrice.model))).scalars().all()
    return ModelsOut(
        tiers=tiers,
        models=[
            ModelOut(model=p.model, display_name=p.display_name or p.model, provider=p.provider,
                     input_per_mtok_usd=p.input_per_mtok_usd, output_per_mtok_usd=p.output_per_mtok_usd,
                     context_window=getattr(p, "context_window", None),
                     eu_bedrock=bedrock_model_id(p.model) is not None, allowed=_allowed(rules, p.model),
                     tiers=[t for t, m in tiers.items() if m == p.model])
            for p in prices if p.model != DEMO_MODEL
        ],
    )
