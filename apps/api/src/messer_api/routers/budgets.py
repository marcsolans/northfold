"""/api/v1/budgets — spend limits per organization and per project (§7.11).

Spend is the raw model cost of the period's runs. At ``alert_threshold_pct`` the admins get an in-app
notification and an email once per period; with ``hard_stop`` the runtime refuses new runs once the limit
is reached (``messer_common.budgets.check_budget``). Members can read; admins manage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.budgets import BudgetUsage, budget_usage, check_budget, evaluate_alerts
from messer_common.db import Principal, system_session
from messer_common.db.models import Budget, Project

from ..deps import require_role
from ..errors import Conflict, NotFound

router = APIRouter(prefix="/budgets", tags=["budgets"])

Period = Literal["day", "week", "month"]


class BudgetIn(BaseModel):
    project_id: uuid.UUID | None = None
    period: Period = "month"
    limit_usd: Decimal = Field(gt=0, le=Decimal("10000000"), decimal_places=2)
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)
    hard_stop: bool = True


class BudgetUpdateIn(BaseModel):
    period: Period | None = None
    limit_usd: Decimal | None = Field(default=None, gt=0, le=Decimal("10000000"), decimal_places=2)
    alert_threshold_pct: int | None = Field(default=None, ge=1, le=100)
    hard_stop: bool | None = None


class BudgetOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    project_name: str | None
    period: str
    limit_usd: Decimal
    alert_threshold_pct: int
    hard_stop: bool
    spent_usd: Decimal
    remaining_usd: Decimal
    pct: int
    state: Literal["ok", "alert", "exceeded"]
    period_start: datetime
    period_end: datetime
    last_alerted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class BudgetCheckOut(BaseModel):
    allowed: bool
    reason: str | None
    message: str | None
    remaining_usd: Decimal | None
    budget_id: uuid.UUID | None
    spent_usd: Decimal | None
    limit_usd: Decimal | None


def _out(usage: BudgetUsage, project_name: str | None) -> BudgetOut:
    b = usage.budget
    return BudgetOut(
        id=b.id,
        project_id=b.project_id,
        project_name=project_name,
        period=b.period,
        limit_usd=Decimal(b.limit_usd),
        alert_threshold_pct=b.alert_threshold_pct,
        hard_stop=b.hard_stop,
        spent_usd=usage.spent_usd,
        remaining_usd=usage.remaining_usd,
        pct=usage.pct,
        state="exceeded" if usage.exceeded else ("alert" if usage.state == "alert" else "ok"),
        period_start=usage.period_start,
        period_end=usage.period_end,
        last_alerted_at=b.last_alerted_at,
        created_at=b.created_at,
        updated_at=b.updated_at,
    )


async def _project_name(session: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID | None) -> str | None:
    if project_id is None:
        return None
    project = await session.get(Project, project_id)
    if project is None or project.org_id != org_id:
        raise NotFound("Proyecto no encontrado", code="unknown_project")
    return project.name


async def _get(session: AsyncSession, org_id: uuid.UUID, budget_id: uuid.UUID) -> Budget:
    budget = await session.get(Budget, budget_id)
    if budget is None or budget.org_id != org_id:
        raise NotFound("Presupuesto no encontrado")
    return budget


def _snapshot(b: Budget) -> dict[str, object]:
    return {
        "project_id": b.project_id,
        "period": b.period,
        "limit_usd": str(b.limit_usd),
        "alert_threshold_pct": b.alert_threshold_pct,
        "hard_stop": b.hard_stop,
    }


@router.get("", response_model=list[BudgetOut])
async def list_budgets(principal: Principal = Depends(require_role("viewer"))) -> list[BudgetOut]:
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Budget, Project.name)
                .outerjoin(Project, Project.id == Budget.project_id)
                .where(Budget.org_id == principal.org_id)
                .order_by(Budget.project_id.is_not(None), Project.name, Budget.created_at)
            )
        ).all()
        return [_out(await budget_usage(s, b), name) for b, name in rows]


@router.get("/check", response_model=BudgetCheckOut)
async def check(
    project_id: uuid.UUID | None = None, principal: Principal = Depends(require_role("viewer"))
) -> BudgetCheckOut:
    """Would a run start now? Same gate the runtime applies (billing state, credits, run limit, budgets)."""
    assert principal.org_id is not None
    async with system_session() as s:
        if project_id is not None:
            await _project_name(s, principal.org_id, project_id)
        status = await check_budget(s, principal.org_id, project_id)
    return BudgetCheckOut(
        allowed=status.allowed,
        reason=status.reason,
        message=status.message,
        remaining_usd=status.remaining_usd,
        budget_id=status.budget_id,
        spent_usd=status.spent_usd,
        limit_usd=status.limit_usd,
    )


@router.post("", response_model=BudgetOut, status_code=201)
async def create_budget(body: BudgetIn, principal: Principal = Depends(require_role("admin"))) -> BudgetOut:
    assert principal.org_id is not None
    async with system_session() as s:
        name = await _project_name(s, principal.org_id, body.project_id)
        existing = (
            await s.execute(
                select(Budget.id).where(
                    Budget.org_id == principal.org_id,
                    Budget.project_id == body.project_id
                    if body.project_id is not None
                    else Budget.project_id.is_(None),
                )
            )
        ).first()
        if existing is not None:
            raise Conflict(
                "Ya existe un presupuesto para este ámbito. Edítalo en lugar de crear otro.",
                code="budget_exists",
                details={"budget_id": str(existing[0])},
            )
        budget = Budget(
            org_id=principal.org_id,
            project_id=body.project_id,
            period=body.period,
            limit_usd=body.limit_usd,
            alert_threshold_pct=body.alert_threshold_pct,
            hard_stop=body.hard_stop,
        )
        s.add(budget)
        try:
            await s.flush()
        except IntegrityError as exc:
            raise Conflict("Ya existe un presupuesto para este ámbito.", code="budget_exists") from exc
        await audit.record(
            s,
            action="budget.created",
            principal=principal,
            entity_type="budget",
            entity_id=budget.id,
            diff=_snapshot(budget),
        )
        await evaluate_alerts(s, org_id=principal.org_id)
        await s.refresh(budget)
        return _out(await budget_usage(s, budget), name)


@router.patch("/{budget_id}", response_model=BudgetOut)
async def update_budget(
    budget_id: uuid.UUID, body: BudgetUpdateIn, principal: Principal = Depends(require_role("admin"))
) -> BudgetOut:
    assert principal.org_id is not None
    async with system_session() as s:
        budget = await _get(s, principal.org_id, budget_id)
        before = _snapshot(budget)
        changes = body.model_dump(exclude_unset=True, exclude_none=True)
        for field, value in changes.items():
            setattr(budget, field, value)
        if {"limit_usd", "alert_threshold_pct", "period"} & changes.keys():
            # A new limit or threshold re-arms this period's alert.
            budget.last_alerted_at = None
        await s.flush()
        await audit.record(
            s,
            action="budget.updated",
            principal=principal,
            entity_type="budget",
            entity_id=budget.id,
            diff={"before": before, "after": _snapshot(budget)},
        )
        await evaluate_alerts(s, org_id=principal.org_id)
        await s.refresh(budget)
        name = await _project_name(s, principal.org_id, budget.project_id)
        return _out(await budget_usage(s, budget), name)


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(budget_id: uuid.UUID, principal: Principal = Depends(require_role("admin"))) -> Response:
    assert principal.org_id is not None
    async with system_session() as s:
        budget = await _get(s, principal.org_id, budget_id)
        snapshot = _snapshot(budget)
        await s.delete(budget)
        await audit.record(
            s, action="budget.deleted", principal=principal, entity_type="budget", entity_id=budget_id, diff=snapshot
        )
    return Response(status_code=204)
