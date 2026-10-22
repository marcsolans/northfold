"""/api/v1/admin — catalog management (superadmins): plans (synced to Stripe), model prices, templates and
feature flags. Every change is audited (global entries, ``org_id`` empty)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import stripe
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import FeatureFlag, ModelPrice, Org, Plan, Subscription, Template
from messer_common.plans import FEATURES

from ..deps import require_superadmin
from ..errors import ApiError, Conflict, NotFound
from ..services import billing as billing_service
from ..services.billing_providers import ProviderError
from .plans import PlanOut, plan_out

router = APIRouter(prefix="/admin", tags=["admin"])

superadmin = require_superadmin()
_PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,38}$")
_FLAG_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,78}$")


# ============================================================================= plans


class PlanLimitsIn(BaseModel):
    seats: int = Field(ge=-1, le=1_000_000)
    projects: int = Field(ge=-1, le=1_000_000)
    runs_month: int = Field(ge=-1, le=1_000_000_000)
    credits_month: int = Field(ge=-1, le=1_000_000_000)
    storage_gb: int = Field(ge=-1, le=1_000_000)
    features: list[str] = Field(default_factory=list)

    @field_validator("features")
    @classmethod
    def _known(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(FEATURES))
        if unknown:
            raise ValueError(f"funcionalidades desconocidas: {', '.join(unknown)}")
        return [f for f in FEATURES if f in set(value)]


class PlanCreateIn(BaseModel):
    id: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    price_month_eur: Decimal = Field(ge=0, le=Decimal("1000000"), decimal_places=2)
    price_year_eur: Decimal = Field(ge=0, le=Decimal("12000000"), decimal_places=2)
    price_is_starting: bool = False
    public: bool = True
    self_serve: bool = True
    sort_order: int = Field(default=0, ge=0, le=1000)
    limits: PlanLimitsIn

    @field_validator("id")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not _PLAN_ID.match(value):
            raise ValueError("solo minúsculas, números, guiones y guiones bajos")
        return value


class PlanUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    price_month_eur: Decimal | None = Field(default=None, ge=0, le=Decimal("1000000"), decimal_places=2)
    price_year_eur: Decimal | None = Field(default=None, ge=0, le=Decimal("12000000"), decimal_places=2)
    price_is_starting: bool | None = None
    public: bool | None = None
    self_serve: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    limits: PlanLimitsIn | None = None


class StripeSyncOut(BaseModel):
    mode: str
    ok: bool
    changed: bool = False
    error: str | None = None


class PlanAdminOut(PlanOut):
    public: bool
    stripe_product_id: str | None
    stripe_price_ids: dict[str, Any]
    subscriptions: int
    updated_at: datetime
    stripe_sync: StripeSyncOut | None = None


async def _subscription_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Subscription.plan_id, func.count())
            .where(Subscription.status.in_(("active", "past_due", "trialing")))
            .group_by(Subscription.plan_id)
        )
    ).all()
    return {str(plan_id): int(n) for plan_id, n in rows}


def _plan_admin(plan: Plan, counts: dict[str, int], sync: StripeSyncOut | None = None) -> PlanAdminOut:
    return PlanAdminOut(
        **plan_out(plan).model_dump(),
        public=plan.public,
        stripe_product_id=plan.stripe_product_id,
        stripe_price_ids=dict(plan.stripe_price_ids or {}),
        subscriptions=counts.get(plan.id, 0),
        updated_at=plan.updated_at,
        stripe_sync=sync,
    )


def _plan_snapshot(plan: Plan) -> dict[str, Any]:
    return {
        "name": plan.name,
        "price_month_eur": str(plan.price_month_eur),
        "price_year_eur": str(plan.price_year_eur),
        "price_is_starting": plan.price_is_starting,
        "public": plan.public,
        "self_serve": plan.self_serve,
        "sort_order": plan.sort_order,
        "limits": plan.limits,
    }


async def _sync(plan: Plan) -> StripeSyncOut:
    """Push the plan to Stripe (products/prices) when Stripe is configured. Never raises."""
    prov = billing_service.provider()
    if prov.mode != "stripe":
        return StripeSyncOut(mode=prov.mode, ok=True)
    try:
        changed = await prov.sync_plan(plan)
    except (ProviderError, stripe.StripeError) as exc:
        message = exc.message if isinstance(exc, ProviderError) else str(exc)
        return StripeSyncOut(mode=prov.mode, ok=False, error=message)
    return StripeSyncOut(mode=prov.mode, ok=True, changed=changed)


@router.get("/plans", response_model=list[PlanAdminOut])
async def list_plans(_: Principal = Depends(superadmin)) -> list[PlanAdminOut]:
    async with system_session() as s:
        plans = (await s.execute(select(Plan).order_by(Plan.sort_order, Plan.id))).scalars().all()
        counts = await _subscription_counts(s)
        return [_plan_admin(p, counts) for p in plans]


@router.post("/plans", response_model=PlanAdminOut, status_code=201)
async def create_plan(body: PlanCreateIn, admin: Principal = Depends(superadmin)) -> PlanAdminOut:
    async with system_session() as s:
        if await s.get(Plan, body.id) is not None:
            raise Conflict("Ya existe un plan con ese identificador.", code="plan_exists")
        plan = Plan(
            id=body.id,
            name=body.name,
            description=body.description,
            price_month_eur=body.price_month_eur,
            price_year_eur=body.price_year_eur,
            price_is_starting=body.price_is_starting,
            public=body.public,
            self_serve=body.self_serve,
            sort_order=body.sort_order,
            limits=body.limits.model_dump(),
            stripe_price_ids={},
        )
        s.add(plan)
        await s.flush()
        sync = await _sync(plan)
        await audit.record(
            s,
            action="admin.plan_created",
            principal=admin,
            org_id=None,
            entity_type="plan",
            entity_id=plan.id,
            diff={**_plan_snapshot(plan), "stripe_sync": sync.model_dump()},
        )
        await s.flush()
        await s.refresh(plan)
        return _plan_admin(plan, await _subscription_counts(s), sync)


@router.patch("/plans/{plan_id}", response_model=PlanAdminOut)
async def update_plan(plan_id: str, body: PlanUpdateIn, admin: Principal = Depends(superadmin)) -> PlanAdminOut:
    """Edit prices, limits and visibility. Prices sync to Stripe (new prices, old ones archived)."""
    async with system_session() as s:
        plan = await s.get(Plan, plan_id)
        if plan is None:
            raise NotFound("Plan no encontrado")
        before = _plan_snapshot(plan)
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        if "limits" in changes and body.limits is not None:
            changes["limits"] = body.limits.model_dump()
        for field, value in changes.items():
            setattr(plan, field, value)
        await s.flush()
        sync = await _sync(plan)
        await audit.record(
            s,
            action="admin.plan_updated",
            principal=admin,
            org_id=None,
            entity_type="plan",
            entity_id=plan.id,
            diff={"before": before, "after": _plan_snapshot(plan), "stripe_sync": sync.model_dump()},
        )
        await s.flush()
        await s.refresh(plan)
        return _plan_admin(plan, await _subscription_counts(s), sync)


@router.post("/plans/sync", response_model=list[PlanAdminOut])
async def sync_plans(admin: Principal = Depends(superadmin)) -> list[PlanAdminOut]:
    """Push every plan to Stripe (no-op in simulated test mode)."""
    async with system_session() as s:
        plans = (await s.execute(select(Plan).order_by(Plan.sort_order, Plan.id))).scalars().all()
        results = [(p, await _sync(p)) for p in plans]
        await audit.record(
            s,
            action="admin.plans_synced",
            principal=admin,
            org_id=None,
            entity_type="plan",
            diff={p.id: r.model_dump() for p, r in results},
        )
        await s.flush()
        counts = await _subscription_counts(s)
        return [_plan_admin(p, counts, r) for p, r in results]


# ============================================================================= model prices


class ModelPriceIn(BaseModel):
    provider: str = Field(min_length=1, max_length=40)
    display_name: str = Field(default="", max_length=120)
    input_per_mtok_usd: Decimal = Field(ge=0, le=Decimal("100000"), decimal_places=4)
    output_per_mtok_usd: Decimal = Field(ge=0, le=Decimal("100000"), decimal_places=4)
    cache_read_per_mtok_usd: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000"), decimal_places=4)
    cache_write_per_mtok_usd: Decimal = Field(default=Decimal("0"), ge=0, le=Decimal("100000"), decimal_places=4)
    context_window: int | None = Field(default=None, ge=1, le=100_000_000)
    active: bool = True


class ModelPriceOut(ModelPriceIn):
    model: str
    updated_at: datetime


def _price_out(p: ModelPrice) -> ModelPriceOut:
    return ModelPriceOut(
        model=p.model,
        provider=p.provider,
        display_name=p.display_name,
        input_per_mtok_usd=p.input_per_mtok_usd,
        output_per_mtok_usd=p.output_per_mtok_usd,
        cache_read_per_mtok_usd=p.cache_read_per_mtok_usd,
        cache_write_per_mtok_usd=p.cache_write_per_mtok_usd,
        context_window=p.context_window,
        active=p.active,
        updated_at=p.updated_at,
    )


def _check_model_id(model: str) -> str:
    model = model.strip()
    if "/" not in model or len(model) > 120 or model.startswith("/") or model.endswith("/"):
        raise ApiError("El modelo debe tener el formato proveedor/modelo", code="invalid_model")
    return model


@router.get("/model-prices", response_model=list[ModelPriceOut])
async def list_model_prices(_: Principal = Depends(superadmin)) -> list[ModelPriceOut]:
    async with system_session() as s:
        rows = (await s.execute(select(ModelPrice).order_by(ModelPrice.provider, ModelPrice.model))).scalars().all()
        return [_price_out(p) for p in rows]


@router.put("/model-prices/{model:path}", response_model=ModelPriceOut)
async def upsert_model_price(model: str, body: ModelPriceIn, admin: Principal = Depends(superadmin)) -> ModelPriceOut:
    model = _check_model_id(model)
    async with system_session() as s:
        row = await s.get(ModelPrice, model)
        before = _price_out(row).model_dump(mode="json") if row is not None else None
        if row is None:
            row = ModelPrice(model=model, **body.model_dump())
            s.add(row)
        else:
            for field, value in body.model_dump().items():
                setattr(row, field, value)
        row.updated_at = datetime.now(UTC)
        await s.flush()
        await audit.record(
            s,
            action="admin.model_price_updated",
            principal=admin,
            org_id=None,
            entity_type="model_price",
            entity_id=model,
            diff={"before": before, "after": body.model_dump(mode="json")},
        )
        return _price_out(row)


@router.delete("/model-prices/{model:path}", status_code=204)
async def delete_model_price(model: str, admin: Principal = Depends(superadmin)) -> Response:
    async with system_session() as s:
        row = await s.get(ModelPrice, model)
        if row is None:
            raise NotFound("Precio no encontrado")
        snapshot = _price_out(row).model_dump(mode="json")
        await s.delete(row)
        await audit.record(
            s,
            action="admin.model_price_deleted",
            principal=admin,
            org_id=None,
            entity_type="model_price",
            entity_id=model,
            diff=snapshot,
        )
    return Response(status_code=204)


# ============================================================================= templates


class TemplateAdminOut(BaseModel):
    id: str
    sector: str
    name: str
    name_en: str
    description: str
    public: bool
    sort_order: int
    tags: list[Any]
    updated_at: datetime


class TemplateUpdateIn(BaseModel):
    public: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class TemplateOrderIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


def _template_out(t: Template) -> TemplateAdminOut:
    return TemplateAdminOut(
        id=t.id,
        sector=t.sector,
        name=t.name,
        name_en=t.name_en,
        description=t.description,
        public=t.public,
        sort_order=t.sort_order,
        tags=list(t.tags or []),
        updated_at=t.updated_at,
    )


async def _templates(session: AsyncSession) -> list[TemplateAdminOut]:
    rows = (await session.execute(select(Template).order_by(Template.sort_order, Template.name))).scalars().all()
    return [_template_out(t) for t in rows]


@router.get("/templates", response_model=list[TemplateAdminOut])
async def list_templates(_: Principal = Depends(superadmin)) -> list[TemplateAdminOut]:
    async with system_session() as s:
        return await _templates(s)


@router.patch("/templates/{template_id}", response_model=TemplateAdminOut)
async def update_template(
    template_id: str, body: TemplateUpdateIn, admin: Principal = Depends(superadmin)
) -> TemplateAdminOut:
    async with system_session() as s:
        t = await s.get(Template, template_id)
        if t is None:
            raise NotFound("Plantilla no encontrada")
        before = {"public": t.public, "sort_order": t.sort_order}
        for field, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(t, field, value)
        await s.flush()
        await audit.record(
            s,
            action="admin.template_updated",
            principal=admin,
            org_id=None,
            entity_type="template",
            entity_id=t.id,
            diff={"before": before, "after": {"public": t.public, "sort_order": t.sort_order}},
        )
        await s.refresh(t)
        return _template_out(t)


@router.put("/templates/order", response_model=list[TemplateAdminOut])
async def reorder_templates(body: TemplateOrderIn, admin: Principal = Depends(superadmin)) -> list[TemplateAdminOut]:
    """Set the display order: ``ids`` first in the given order, the rest keep their relative order after."""
    if len(set(body.ids)) != len(body.ids):
        raise ApiError("La lista contiene plantillas repetidas", code="duplicate_ids")
    async with system_session() as s:
        rows = (await s.execute(select(Template).order_by(Template.sort_order, Template.name))).scalars().all()
        by_id = {t.id: t for t in rows}
        missing = [i for i in body.ids if i not in by_id]
        if missing:
            raise NotFound(f"Plantillas desconocidas: {', '.join(missing)}", code="unknown_template")
        ordered = [by_id[i] for i in body.ids] + [t for t in rows if t.id not in set(body.ids)]
        for index, t in enumerate(ordered):
            t.sort_order = (index + 1) * 10
        await audit.record(
            s,
            action="admin.templates_reordered",
            principal=admin,
            org_id=None,
            entity_type="template",
            diff={"order": [t.id for t in ordered]},
        )
        await s.flush()
        return await _templates(s)


# ============================================================================= feature flags


class FlagTargeting(BaseModel):
    plans: list[str] = Field(default_factory=list, max_length=50)
    orgs: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class FlagIn(BaseModel):
    description: str = Field(default="", max_length=500)
    enabled: bool = False
    targeting: FlagTargeting = Field(default_factory=FlagTargeting)


class FlagOut(BaseModel):
    key: str
    description: str
    enabled: bool
    targeting: FlagTargeting
    updated_at: datetime


def _flag_out(f: FeatureFlag) -> FlagOut:
    raw = f.targeting or {}
    return FlagOut(
        key=f.key,
        description=f.description,
        enabled=f.enabled,
        targeting=FlagTargeting(plans=list(raw.get("plans") or []), orgs=list(raw.get("orgs") or [])),
        updated_at=f.updated_at,
    )


@router.get("/feature-flags", response_model=list[FlagOut])
async def list_flags(_: Principal = Depends(superadmin)) -> list[FlagOut]:
    async with system_session() as s:
        rows = (await s.execute(select(FeatureFlag).order_by(FeatureFlag.key))).scalars().all()
        return [_flag_out(f) for f in rows]


@router.put("/feature-flags/{key}", response_model=FlagOut)
async def upsert_flag(key: str, body: FlagIn, admin: Principal = Depends(superadmin)) -> FlagOut:
    """Create or update a flag. ``enabled`` is the master switch; targeting limits it to plans/orgs."""
    if not _FLAG_KEY.match(key):
        raise ApiError("Clave no válida: minúsculas, números, puntos, guiones y guiones bajos", code="invalid_key")
    async with system_session() as s:
        if body.targeting.plans:
            known = set((await s.execute(select(Plan.id).where(Plan.id.in_(body.targeting.plans)))).scalars().all())
            unknown = sorted(set(body.targeting.plans) - known)
            if unknown:
                raise ApiError(f"Planes desconocidos: {', '.join(unknown)}", code="unknown_plan")
        if body.targeting.orgs:
            found = set((await s.execute(select(Org.id).where(Org.id.in_(body.targeting.orgs)))).scalars().all())
            missing = [str(o) for o in body.targeting.orgs if o not in found]
            if missing:
                raise ApiError(f"Organizaciones desconocidas: {', '.join(missing)}", code="unknown_org")
        flag = await s.get(FeatureFlag, key)
        before = _flag_out(flag).model_dump(mode="json") if flag is not None else None
        targeting = {"plans": body.targeting.plans, "orgs": [str(o) for o in body.targeting.orgs]}
        if flag is None:
            flag = FeatureFlag(key=key, description=body.description, enabled=body.enabled, targeting=targeting)
            s.add(flag)
        else:
            flag.description = body.description
            flag.enabled = body.enabled
            flag.targeting = targeting
        await s.flush()
        await audit.record(
            s,
            action="admin.feature_flag_updated",
            principal=admin,
            org_id=None,
            entity_type="feature_flag",
            entity_id=key,
            diff={"before": before, "after": body.model_dump(mode="json")},
        )
        await s.refresh(flag)
        return _flag_out(flag)


@router.delete("/feature-flags/{key}", status_code=204)
async def delete_flag(key: str, admin: Principal = Depends(superadmin)) -> Response:
    async with system_session() as s:
        flag = await s.get(FeatureFlag, key)
        if flag is None:
            raise NotFound("Flag no encontrado")
        snapshot = _flag_out(flag).model_dump(mode="json")
        await s.delete(flag)
        await audit.record(
            s,
            action="admin.feature_flag_deleted",
            principal=admin,
            org_id=None,
            entity_type="feature_flag",
            entity_id=key,
            diff=snapshot,
        )
    return Response(status_code=204)
