"""/api/v1/runs — run history, trace detail (span tree with tokens and cost), re-run, feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, runtime_client
from messer_common.db import Principal
from messer_common.db.models import Approval, Feedback, Project, Run, Span
from messer_common.runtime_client import RuntimeUnavailable

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound

router = APIRouter(prefix="/runs", tags=["runs"])
project_router = APIRouter(prefix="/projects/{project_id}/runs", tags=["runs"])


class RunSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None = None
    workforce_name: str
    status: str
    channel: str
    environment: str
    cost_usd: Decimal
    credits: Decimal
    duration_ms: int | None
    models: list[Any]
    user_id: uuid.UUID | None
    external_user_id: str | None
    conversation_id: uuid.UUID | None
    parent_run_id: uuid.UUID | None
    started_at: datetime
    ended_at: datetime | None


class SpanOut(BaseModel):
    id: uuid.UUID
    call_id: str
    parent_span_id: uuid.UUID | None
    kind: str
    name: str
    path: str
    status: str
    input: Any
    output: Any
    error: Any
    model: str | None
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: Decimal
    t0: int
    t1: int | None
    meta: dict[str, Any]


class ApprovalBrief(BaseModel):
    id: uuid.UUID
    tool_name: str
    title: str
    status: str
    assigned_role: str
    payload: dict[str, Any]
    resume_run_id: uuid.UUID | None


class RunDetail(RunSummary):
    input: Any
    output: Any
    error: Any
    usage: dict[str, Any]
    git_commit: str | None
    version_id: uuid.UUID | None
    rerun_of: uuid.UUID | None
    spans: list[SpanOut]
    approvals: list[ApprovalBrief]
    feedback: list[dict[str, Any]]
    children: list[uuid.UUID]


class RunPage(BaseModel):
    items: list[RunSummary]
    next_cursor: str | None


def _summary(run: Run, project_names: dict[uuid.UUID, str]) -> RunSummary:
    return RunSummary(
        id=run.id,
        project_id=run.project_id,
        project_name=project_names.get(run.project_id),
        workforce_name=run.workforce_name,
        status=run.status,
        channel=run.channel,
        environment=run.environment,
        cost_usd=run.cost_usd,
        credits=run.credits,
        duration_ms=run.duration_ms,
        models=list(run.models or []),
        user_id=run.user_id,
        external_user_id=run.external_user_id,
        conversation_id=run.conversation_id,
        parent_run_id=run.parent_run_id,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


@router.get("", response_model=RunPage)
async def list_runs(
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    project_id: uuid.UUID | None = None,
    workforce: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    environment: Literal["development", "production"] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = Query(default=None, description="started_at|id of the last item of the previous page"),
    limit: int = Query(default=50, ge=1, le=200),
) -> RunPage:
    q = select(Run).where(Run.org_id == principal.org_id)
    if principal.project_id is not None:
        q = q.where(Run.project_id == principal.project_id)
    if project_id is not None:
        q = q.where(Run.project_id == project_id)
    if workforce:
        q = q.where(Run.workforce_name == workforce)
    if status:
        q = q.where(Run.status.in_(status.split(",")))
    if channel:
        q = q.where(Run.channel.in_(channel.split(",")))
    if environment:
        q = q.where(Run.environment == environment)
    if since:
        q = q.where(Run.started_at >= since)
    if until:
        q = q.where(Run.started_at < until)
    if cursor:
        try:
            raw_ts, raw_id = cursor.split("|", 1)
            ts, rid = datetime.fromisoformat(raw_ts), uuid.UUID(raw_id)
        except ValueError as exc:
            raise ApiError("Cursor no válido", code="invalid_cursor") from exc
        q = q.where((Run.started_at < ts) | ((Run.started_at == ts) & (Run.id < rid)))
    rows = (await session.execute(q.order_by(Run.started_at.desc(), Run.id.desc()).limit(limit + 1))).scalars().all()
    page = list(rows[:limit])
    names = await _project_names(session, {r.project_id for r in page})
    next_cursor = f"{page[-1].started_at.isoformat()}|{page[-1].id}" if len(rows) > limit and page else None
    return RunPage(items=[_summary(r, names) for r in page], next_cursor=next_cursor)


async def _project_names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {p.id: p.name for p in (await session.execute(select(Project).where(Project.id.in_(ids)))).scalars()}


async def _get_run(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None or run.org_id != principal.org_id:
        raise NotFound("Ejecución no encontrada")
    ensure_project_access(principal, run.project_id)
    return run


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), session: AsyncSession = Depends(get_db)
) -> RunDetail:
    run = await _get_run(session, principal, run_id)
    spans = (await session.execute(select(Span).where(Span.run_id == run.id).order_by(Span.t0))).scalars().all()
    approvals = (await session.execute(select(Approval).where(Approval.run_id == run.id))).scalars().all()
    feedback = (await session.execute(select(Feedback).where(Feedback.run_id == run.id))).scalars().all()
    children = (await session.execute(select(Run.id).where(Run.parent_run_id == run.id))).scalars().all()
    names = await _project_names(session, {run.project_id})
    return RunDetail(
        **_summary(run, names).model_dump(),
        input=run.input,
        output=run.output,
        error=run.error,
        usage=run.usage or {},
        git_commit=run.git_commit,
        version_id=run.version_id,
        rerun_of=run.rerun_of,
        spans=[
            SpanOut(
                id=s.id,
                call_id=s.call_id,
                parent_span_id=s.parent_span_id,
                kind=s.kind,
                name=s.name,
                path=s.path,
                status=s.status,
                input=s.input,
                output=s.output,
                error=s.error,
                model=s.model,
                input_tokens=s.input_tokens,
                output_tokens=s.output_tokens,
                cache_read_tokens=s.cache_read_tokens,
                cost_usd=s.cost_usd,
                t0=s.t0,
                t1=s.t1,
                meta=s.meta or {},
            )
            for s in spans
        ],
        approvals=[
            ApprovalBrief(
                id=a.id,
                tool_name=a.tool_name,
                title=a.title,
                status=a.status,
                assigned_role=a.assigned_role,
                payload=a.payload or {},
                resume_run_id=a.resume_run_id,
            )
            for a in approvals
        ],
        feedback=[
            {
                "id": str(f.id),
                "value": f.value,
                "comment": f.comment,
                "user_id": str(f.user_id) if f.user_id else None,
                "created_at": f.created_at.isoformat(),
            }
            for f in feedback
        ],
        children=list(children),
    )


@router.post("/{run_id}/rerun", response_model=RunSummary)
async def rerun(
    run_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), session: AsyncSession = Depends(get_db)
) -> RunSummary:
    """Run again with the same input on the exact same code (git commit)."""
    run = await _get_run(session, principal, run_id)
    if run.parent_run_id is not None and run.input is None:
        raise ApiError("Esta ejecución no se puede repetir", code="not_rerunnable")
    body = {
        "org_id": str(run.org_id),
        "project_id": str(run.project_id),
        "workforce": run.workforce_name,
        "ref": run.git_commit or "HEAD",
        "input": run.input or {},
        "environment": run.environment,
        "environment_id": str(run.environment_id) if run.environment_id else None,
        "version_id": str(run.version_id) if run.version_id else None,
        "channel": "studio",
        "user_id": str(principal.user_id) if principal.user_id else None,
        "rerun_of": str(run.id),
    }
    try:
        result = await runtime_client.run(body)
    except RuntimeUnavailable as exc:
        raise ApiError(
            "El entorno de ejecución no está disponible",
            code="runtime_unavailable",
            status_code=503,
            details={"detail": str(exc)[:300]},
        ) from exc
    await audit.record(
        session,
        action="run.rerun",
        principal=principal,
        entity_type="run",
        entity_id=run.id,
        diff={"new_run_id": result.get("run_id")},
    )
    new = await session.get(Run, uuid.UUID(str(result["run_id"])))
    if new is None:
        raise ApiError(
            "La ejecución no se pudo iniciar",
            code="rerun_failed",
            status_code=502,
            details={"errors": result.get("errors")},
        )
    await session.refresh(new)
    return _summary(new, await _project_names(session, {new.project_id}))


class FeedbackIn(BaseModel):
    value: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=4000)


@router.post("/{run_id}/feedback", status_code=201)
async def add_feedback(
    run_id: uuid.UUID,
    body: FeedbackIn,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await _get_run(session, principal, run_id)
    existing = (
        await session.execute(select(Feedback).where(Feedback.run_id == run.id, Feedback.user_id == principal.user_id))
    ).scalar_one_or_none()
    if existing is not None:
        existing.value, existing.comment = body.value, body.comment
        row = existing
    else:
        row = Feedback(
            org_id=run.org_id,
            run_id=run.id,
            project_id=run.project_id,
            user_id=principal.user_id,
            value=body.value,
            comment=body.comment,
        )
        session.add(row)
    await session.flush()
    return {"id": str(row.id), "value": row.value, "comment": row.comment}


@project_router.get("", response_model=RunPage)
async def list_project_runs(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    workforce: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> RunPage:
    """Same as ``GET /runs?project_id=`` (spec path)."""
    ensure_project_access(principal, project_id)
    return await list_runs(
        principal=principal,
        session=session,
        project_id=project_id,
        workforce=workforce,
        status=status,
        channel=channel,
        environment=None,
        since=None,
        until=None,
        cursor=cursor,
        limit=limit,
    )


extra_routers = [project_router]
