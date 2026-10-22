"""Public catalogs (contracts §1): ``GET /api/v1/plans`` and ``GET /api/v1/credit-packs``. No authentication."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, field_serializer
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Plan
from messer_common.plans import CREDIT_PACKS, FEATURES

router = APIRouter(tags=["plans"])

TWO = Decimal("0.01")


def money(value: Decimal | int | float | str) -> str:
    return str(Decimal(str(value)).quantize(TWO))


class PlanLimits(BaseModel):
    seats: int
    projects: int
    runs_month: int
    credits_month: int
    storage_gb: int
    features: list[str]


class PlanOut(BaseModel):
    id: str
    name: str
    description: str
    price_month_eur: Decimal
    price_year_eur: Decimal
    price_is_starting: bool
    self_serve: bool
    sort_order: int
    limits: PlanLimits

    @field_serializer("price_month_eur", "price_year_eur")
    def _money(self, value: Decimal) -> str:
        return money(value)


class CreditPackOut(BaseModel):
    id: str
    credits: int
    price_eur: Decimal

    @field_serializer("price_eur")
    def _money(self, value: Decimal) -> str:
        return money(value)


class FeatureOut(BaseModel):
    key: str
    label: str


def _limits(raw: dict[str, Any]) -> PlanLimits:
    def num(key: str) -> int:
        value = raw.get(key)
        return -1 if value is None else int(value)

    return PlanLimits(
        seats=num("seats"),
        projects=num("projects"),
        runs_month=num("runs_month"),
        credits_month=num("credits_month"),
        storage_gb=num("storage_gb"),
        features=[str(f) for f in raw.get("features") or []],
    )


def plan_out(plan: Plan) -> PlanOut:
    return PlanOut(
        id=plan.id,
        name=plan.name,
        description=plan.description,
        price_month_eur=Decimal(plan.price_month_eur),
        price_year_eur=Decimal(plan.price_year_eur),
        price_is_starting=plan.price_is_starting,
        self_serve=plan.self_serve,
        sort_order=plan.sort_order,
        limits=_limits(plan.limits or {}),
    )


@router.get("/plans", response_model=list[PlanOut])
async def list_plans() -> list[PlanOut]:
    """Public plans ordered by ``sort_order``. ``-1`` means unlimited."""
    async with system_session() as s:
        rows = (
            (await s.execute(select(Plan).where(Plan.public.is_(True)).order_by(Plan.sort_order, Plan.id)))
            .scalars()
            .all()
        )
    return [plan_out(p) for p in rows]


@router.get("/credit-packs", response_model=list[CreditPackOut])
async def list_credit_packs() -> list[CreditPackOut]:
    return [
        CreditPackOut(id=str(p["id"]), credits=int(p["credits"]), price_eur=Decimal(p["price_eur"]))
        for p in CREDIT_PACKS
    ]


@router.get("/plan-features", response_model=list[FeatureOut])
async def list_plan_features() -> list[FeatureOut]:
    """Feature keys used in ``limits.features`` with their Spanish labels."""
    return [FeatureOut(key=k, label=v) for k, v in FEATURES.items()]
