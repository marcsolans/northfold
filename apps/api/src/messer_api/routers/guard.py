"""/api/v1/projects/{project_id}/guard — Guard playbooks per agent: read, edit, regenerate, enable, metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import Project
from messer_common.guard import validate_playbook

from ..deps import ensure_project_access, get_db, require_role
from ..services import guard as svc
from ..services import projects as projects_svc

router = APIRouter(prefix="/projects/{project_id}/guard", tags=["guard"])


class IssueOut(BaseModel):
    level: Literal["error", "warning"]
    path: str
    code: str
    message: str
    params: dict[str, Any] = Field(default_factory=dict)


class ToolOut(BaseModel):
    name: str
    kind: str
    label: str
    side_effect: bool
    gated: bool
    input_schema: dict[str, Any] | None = None


class ModelOut(BaseModel):
    id: str
    label: str


class ModelDefaults(BaseModel):
    small_model: str
    large_model: str


class GuardDetail(BaseModel):
    member: str
    workforce_id: uuid.UUID
    enabled: bool
    playbook: dict[str, Any] | None
    generated_by: str | None
    meta: dict[str, Any]
    updated_at: datetime | None
    updated_by: uuid.UUID | None
    issues: list[IssueOut]
    tools: list[ToolOut]
    models: list[ModelOut]
    defaults: ModelDefaults
    facts: list[str]
    plan_allows: bool


class AgentGuardSummary(BaseModel):
    member: str
    enabled: bool
    has_playbook: bool
    generated_by: str | None
    policies: int
    updated_at: datetime | None


class GuardOverview(BaseModel):
    agents: list[AgentGuardSummary]
    plan_allows: bool


class PlaybookIn(BaseModel):
    playbook: dict[str, Any]


class ValidationOut(BaseModel):
    ok: bool
    issues: list[IssueOut]


class CostOut(BaseModel):
    guarded_usd: str
    baseline_usd: str
    overhead_usd: str
    per_run_guarded_usd: str | None
    per_run_baseline_usd: str | None
    savings_pct: float | None


class DailyOut(BaseModel):
    day: str
    turns: int
    on_path: int
    blocked: int


class PolicyCountOut(BaseModel):
    policy: str
    turns: int
    blocked: int


class MetricsOut(BaseModel):
    days: int
    runs: int
    turns: int
    on_path_turns: int
    on_path_share: float | None
    blocked_actions: int
    errors: int
    invalid_outputs: int
    routes: dict[str, int]
    cost: CostOut
    demo: bool
    daily: list[DailyOut]
    policies: list[PolicyCountOut]


class DecisionOut(BaseModel):
    span_id: uuid.UUID
    run_id: uuid.UUID
    at: datetime
    channel: str | None
    policy: str
    action: str | None
    status: str
    route: str | None
    model: str | None
    requested_model: str | None
    on_path: bool
    text: str
    turn: str | None
    tool_calls: list[dict[str, Any]]
    blocked: list[dict[str, Any]]
    votes: list[dict[str, Any]]
    facts: list[str]
    latency_ms: int | None
    overhead_cost_usd: str
    priced_cost_usd: str | None
    baseline_cost_usd: str | None
    demo: bool
    errors: list[str]


async def _project(db: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Project:
    ensure_project_access(principal, project_id)
    return await projects_svc.get_project(db, project_id)


async def _detail(db: AsyncSession, project: Project, member: str) -> GuardDetail:
    st = await svc.state(db, project, member)
    return GuardDetail.model_validate(await svc.describe(db, project, st))


@router.get("", response_model=GuardOverview)
async def guard_overview(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> GuardOverview:
    project = await _project(db, principal, project_id)
    return GuardOverview.model_validate(await svc.overview(db, project))


@router.get("/{member}", response_model=GuardDetail)
async def get_guard(
    project_id: uuid.UUID,
    member: str,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> GuardDetail:
    project = await _project(db, principal, project_id)
    return await _detail(db, project, member)


@router.put("/{member}", response_model=GuardDetail)
async def save_playbook(
    project_id: uuid.UUID,
    member: str,
    body: PlaybookIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> GuardDetail:
    """Replace the playbook (validated; schema errors → 422 ``invalid_playbook`` with ``details.issues``)."""
    project = await _project(db, principal, project_id)
    await svc.save(db, principal, project, member, body.playbook)
    return await _detail(db, project, member)


@router.post("/{member}/validate", response_model=ValidationOut)
async def validate(
    project_id: uuid.UUID,
    member: str,
    body: PlaybookIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> ValidationOut:
    project = await _project(db, principal, project_id)
    st = await svc.state(db, project, member)
    result = validate_playbook(body.playbook, tools=st.tools)
    return ValidationOut(ok=result.ok, issues=[IssueOut.model_validate(i.as_dict()) for i in result.issues])


@router.post("/{member}/regenerate", response_model=GuardDetail)
async def regenerate(
    project_id: uuid.UUID,
    member: str,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> GuardDetail:
    """Propose a playbook from the agent's code, configuration and tools (LLM, or rules in demo mode)."""
    project = await _project(db, principal, project_id)
    await svc.regenerate(db, principal, project, member)
    return await _detail(db, project, member)


@router.post("/{member}/enable", response_model=GuardDetail)
async def enable(
    project_id: uuid.UUID,
    member: str,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> GuardDetail:
    project = await _project(db, principal, project_id)
    await svc.set_enabled(db, principal, project, member, True)
    return await _detail(db, project, member)


@router.post("/{member}/disable", response_model=GuardDetail)
async def disable(
    project_id: uuid.UUID,
    member: str,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> GuardDetail:
    project = await _project(db, principal, project_id)
    await svc.set_enabled(db, principal, project, member, False)
    return await _detail(db, project, member)


@router.get("/{member}/metrics", response_model=MetricsOut)
async def guard_metrics(
    project_id: uuid.UUID,
    member: str,
    days: int = Query(default=30, ge=1, le=90),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> MetricsOut:
    project = await _project(db, principal, project_id)
    return MetricsOut.model_validate(await svc.metrics(db, project, member, days))


@router.get("/{member}/decisions", response_model=list[DecisionOut])
async def guard_decisions(
    project_id: uuid.UUID,
    member: str,
    limit: int = Query(default=50, ge=1, le=svc.MAX_DECISIONS),
    days: int = Query(default=30, ge=1, le=90),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionOut]:
    project = await _project(db, principal, project_id)
    return [DecisionOut.model_validate(d) for d in await svc.decisions(db, project, member, limit, days)]
