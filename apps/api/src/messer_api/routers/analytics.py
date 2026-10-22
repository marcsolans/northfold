"""/api/v1/analytics — AI analytics (§7.11): cost, runs, users, latency, success rate, models and feedback.

Filters on every endpoint: ``since``/``until`` (default: last 30 days), ``project_id``, ``environment``,
``channel`` and ``workforce`` (agent or workflow name). Time series take ``bucket`` (hour/day/week, automatic by
default) and ``tz`` (IANA time zone of the viewer). Every table view has a CSV export. Members (viewer and up)
read through their RLS session; project-scoped API keys only see their project.

Also: ``/projects/{id}/workforce/{name}/evals/compare`` — eval pass rate per case across versions (§7.12).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import analytics as an
from messer_common.analytics.filters import zone
from messer_common.db import Principal
from messer_common.db.models import EvalRun, Project, Run, Version, Workforce

from ..deps import ensure_project_access, get_db, require_role
from ..errors import NotFound
from ..services.analytics import InvalidQuery, build_filters, to_csv

router = APIRouter(tags=["analytics"])

CSV_LIMIT = 10_000
DEFAULT_TZ = "Europe/Madrid"


# --------------------------------------------------------------------------------------------- schemas


class KpisOut(BaseModel):
    runs: int
    success: int
    errors: int
    terminal: int
    success_rate: float | None
    error_rate: float | None
    cost_usd: Decimal
    credits: Decimal
    users: int
    p50_ms: float | None
    p95_ms: float | None
    avg_ms: float | None
    last_run_at: datetime | None


class FeedbackOut(BaseModel):
    up: int
    down: int
    total: int
    up_ratio: float | None


class ModelOut(BaseModel):
    model: str
    label: str
    runs: int
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    errors: int
    p50_ms: float | None
    p95_ms: float | None


class OverviewOut(BaseModel):
    since: datetime
    until: datetime
    kpis: KpisOut
    previous: KpisOut
    feedback: FeedbackOut
    top_models: list[ModelOut]


class PointOut(BaseModel):
    t: datetime
    runs: int
    success: int
    errors: int
    error_rate: float | None
    cost_usd: Decimal
    credits: Decimal
    users: int
    p50_ms: float | None
    p95_ms: float | None


class TimeseriesOut(BaseModel):
    since: datetime
    until: datetime
    bucket: str
    tz: str
    points: list[PointOut]


class RowOut(BaseModel):
    key: str
    label: str
    project_id: uuid.UUID | None = None
    project_name: str | None = None
    runs: int
    success: int | None = None
    errors: int
    terminal: int | None = None
    success_rate: float | None = None
    error_rate: float | None = None
    cost_usd: Decimal
    credits: Decimal | None = None
    users: int | None = None
    p50_ms: float | None = None
    p95_ms: float | None = None
    avg_ms: float | None = None
    last_run_at: datetime | None = None
    calls: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class BreakdownOut(BaseModel):
    group_by: str
    since: datetime
    until: datetime
    rows: list[RowOut]


class CommentOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    value: str
    comment: str
    created_at: datetime
    project_id: uuid.UUID | None
    project_name: str | None
    workforce_name: str
    channel: str
    user: str | None


class FeedbackDetailOut(FeedbackOut):
    comments: list[CommentOut]


class FilterOption(BaseModel):
    value: str
    label: str


class FilterOptionsOut(BaseModel):
    projects: list[FilterOption]
    environments: list[str]
    channels: list[str]
    agents: list[FilterOption]


# --------------------------------------------------------------------------------------------- helpers


def _kpis_out(k: an.Kpis) -> KpisOut:
    return KpisOut(
        runs=k.runs,
        success=k.success,
        errors=k.errors,
        terminal=k.terminal,
        success_rate=k.success_rate,
        error_rate=k.error_rate,
        cost_usd=k.cost_usd,
        credits=k.credits,
        users=k.users,
        p50_ms=k.p50_ms,
        p95_ms=k.p95_ms,
        avg_ms=k.avg_ms,
        last_run_at=k.last_run_at,
    )


def _model_out(m: an.ModelUsage) -> ModelOut:
    return ModelOut(
        model=m.model,
        label=m.label,
        runs=m.runs,
        calls=m.calls,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
        cost_usd=m.cost_usd,
        errors=m.errors,
        p50_ms=m.p50_ms,
        p95_ms=m.p95_ms,
    )


def _row_out(r: an.BreakdownRow) -> RowOut:
    k = r.kpis
    return RowOut(
        key=r.key,
        label=r.label,
        project_id=r.project_id,
        project_name=r.extra.get("project_name") or (r.label if r.project_id and r.key == str(r.project_id) else None),
        runs=k.runs,
        success=k.success,
        errors=k.errors,
        terminal=k.terminal,
        success_rate=k.success_rate,
        error_rate=k.error_rate,
        cost_usd=k.cost_usd,
        credits=k.credits,
        users=k.users,
        p50_ms=k.p50_ms,
        p95_ms=k.p95_ms,
        avg_ms=k.avg_ms,
        last_run_at=k.last_run_at,
    )


def _model_row(m: an.ModelUsage) -> RowOut:
    return RowOut(
        key=m.model,
        label=m.label,
        runs=m.runs,
        errors=m.errors,
        cost_usd=m.cost_usd,
        p50_ms=m.p50_ms,
        p95_ms=m.p95_ms,
        calls=m.calls,
        input_tokens=m.input_tokens,
        output_tokens=m.output_tokens,
    )


async def scoped_filters(
    principal: Principal = Depends(require_role("viewer")),
    since: datetime | None = Query(default=None, description="Inicio (ISO 8601). Por defecto, hace 30 días."),
    until: datetime | None = Query(default=None, description="Fin (ISO 8601, exclusivo). Por defecto, ahora."),
    project_id: uuid.UUID | None = None,
    environment: Literal["development", "production"] | None = None,
    channel: str | None = Query(default=None, max_length=20),
    workforce: str | None = Query(default=None, max_length=80, description="Nombre del agente o flujo"),
) -> an.Filters:
    assert principal.org_id is not None
    if principal.project_id is not None:
        if project_id is not None:
            ensure_project_access(principal, project_id)
        project_id = principal.project_id
    return build_filters(
        principal.org_id,
        since=since,
        until=until,
        project_id=project_id,
        environment=environment,
        channel=channel,
        workforce=workforce,
    )


def _tz(tz: str) -> str:
    try:
        zone(tz)
    except an.AnalyticsError as exc:
        raise InvalidQuery(exc.message, code=exc.code) from exc
    return tz


async def _timeseries(session: AsyncSession, f: an.Filters, bucket: an.Bucket | None, tz: str) -> TimeseriesOut:
    chosen: an.Bucket = bucket or an.auto_bucket(f.since, f.until)
    try:
        points = await an.timeseries(session, f, bucket=chosen, tz=_tz(tz))
    except an.AnalyticsError as exc:
        raise InvalidQuery(exc.message, code=exc.code) from exc
    return TimeseriesOut(
        since=f.since,
        until=f.until,
        bucket=chosen,
        tz=tz,
        points=[
            PointOut(
                t=p.t,
                runs=p.kpis.runs,
                success=p.kpis.success,
                errors=p.kpis.errors,
                error_rate=p.kpis.error_rate,
                cost_usd=p.kpis.cost_usd,
                credits=p.kpis.credits,
                users=p.kpis.users,
                p50_ms=p.kpis.p50_ms,
                p95_ms=p.kpis.p95_ms,
            )
            for p in points
        ],
    )


async def _breakdown(
    session: AsyncSession, f: an.Filters, group_by: an.GroupBy, sort: an.SortKey, limit: int
) -> list[RowOut]:
    if group_by == "model":
        return [_model_row(m) for m in await an.model_usage(session, f, limit=limit)]
    return [_row_out(r) for r in await an.breakdown(session, f, group_by, sort=sort, limit=limit)]


def _csv_response(body: str, name: str) -> Response:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"', "Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------------------------- endpoints


@router.get("/analytics/overview", response_model=OverviewOut)
async def overview(f: an.Filters = Depends(scoped_filters), db: AsyncSession = Depends(get_db)) -> OverviewOut:
    """KPI cards: current period, the previous period of the same length, feedback and the top models."""
    current = await an.kpis(db, f)
    previous = await an.kpis(db, f.previous())
    fb = await an.feedback_stats(db, f)
    models = await an.model_usage(db, f, limit=5)
    return OverviewOut(
        since=f.since,
        until=f.until,
        kpis=_kpis_out(current),
        previous=_kpis_out(previous),
        feedback=FeedbackOut(up=fb.up, down=fb.down, total=fb.total, up_ratio=fb.up_ratio),
        top_models=[_model_out(m) for m in models],
    )


@router.get("/analytics/timeseries", response_model=TimeseriesOut)
async def timeseries(
    f: an.Filters = Depends(scoped_filters),
    bucket: an.Bucket | None = None,
    tz: str = Query(default=DEFAULT_TZ, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> TimeseriesOut:
    return await _timeseries(db, f, bucket, tz)


@router.get("/analytics/breakdown", response_model=BreakdownOut)
async def breakdown(
    group_by: an.GroupBy = "project",
    sort: an.SortKey = "runs",
    limit: int = Query(default=50, ge=1, le=500),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> BreakdownOut:
    rows = await _breakdown(db, f, group_by, sort, limit)
    return BreakdownOut(group_by=group_by, since=f.since, until=f.until, rows=rows)


@router.get("/analytics/models", response_model=list[ModelOut])
async def models(
    limit: int = Query(default=20, ge=1, le=200),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> list[ModelOut]:
    return [_model_out(m) for m in await an.model_usage(db, f, limit=limit)]


@router.get("/analytics/feedback", response_model=FeedbackDetailOut)
async def feedback(
    limit: int = Query(default=20, ge=1, le=200),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> FeedbackDetailOut:
    stats = await an.feedback_stats(db, f)
    comments = await an.feedback_comments(db, f, limit=limit)
    return FeedbackDetailOut(
        up=stats.up,
        down=stats.down,
        total=stats.total,
        up_ratio=stats.up_ratio,
        comments=[CommentOut(**{k: getattr(c, k) for k in CommentOut.model_fields}) for c in comments],
    )


@router.get("/analytics/filters", response_model=FilterOptionsOut)
async def filter_options(
    f: an.Filters = Depends(scoped_filters), db: AsyncSession = Depends(get_db)
) -> FilterOptionsOut:
    """Values for the filter bar: projects of the organization and environments/channels/agents seen in the period."""
    pq = select(Project.id, Project.name).where(Project.org_id == f.org_id, Project.archived_at.is_(None))
    if f.project_id is not None:
        pq = pq.where(Project.id == f.project_id)
    projects = [
        FilterOption(value=str(pid), label=name) for pid, name in (await db.execute(pq.order_by(Project.name))).all()
    ]
    window = f.run_conditions()
    envs = (await db.execute(select(Run.environment).where(*window).distinct())).scalars().all()
    channels = (await db.execute(select(Run.channel).where(*window).distinct())).scalars().all()
    agents = (
        await db.execute(
            select(Run.workforce_name, Project.name)
            .join(Project, Project.id == Run.project_id)
            .where(*window, Run.workforce_name != "")
            .group_by(Run.workforce_name, Project.name)
            .order_by(Run.workforce_name)
            .limit(500)
        )
    ).all()
    seen: dict[str, list[str]] = {}
    for name, project_name in agents:
        seen.setdefault(name, []).append(project_name)
    return FilterOptionsOut(
        projects=projects,
        environments=sorted({e for e in envs if e}),
        channels=sorted({c for c in channels if c}),
        agents=[FilterOption(value=n, label=n if len(p) == 1 else f"{n} ({len(p)})") for n, p in seen.items()],
    )


ExportView = Literal["overview", "timeseries", "breakdown", "feedback"]


@router.get("/analytics/export.csv")
async def export_csv(
    view: ExportView = "breakdown",
    group_by: an.GroupBy = "project",
    sort: an.SortKey = "runs",
    bucket: an.Bucket | None = None,
    tz: str = Query(default=DEFAULT_TZ, max_length=64),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CSV of any table view (same filters as the screen)."""
    if view == "overview":
        cur = _kpis_out(await an.kpis(db, f))
        prev = _kpis_out(await an.kpis(db, f.previous()))
        fb = await an.feedback_stats(db, f)
        fields = [
            "runs",
            "success",
            "errors",
            "success_rate",
            "error_rate",
            "cost_usd",
            "credits",
            "users",
            "p50_ms",
            "p95_ms",
            "avg_ms",
        ]
        rows: list[list[Any]] = [[k, getattr(cur, k), getattr(prev, k)] for k in fields]
        rows += [["feedback_up", fb.up, ""], ["feedback_down", fb.down, ""], ["feedback_up_ratio", fb.up_ratio, ""]]
        body = to_csv(["metric", "value", "previous_period"], rows)
        return _csv_response(body, "analytics-overview")
    if view == "timeseries":
        series = await _timeseries(db, f, bucket, tz)
        body = to_csv(
            ["t", "runs", "success", "errors", "error_rate", "cost_usd", "credits", "users", "p50_ms", "p95_ms"],
            [
                [p.t, p.runs, p.success, p.errors, p.error_rate, p.cost_usd, p.credits, p.users, p.p50_ms, p.p95_ms]
                for p in series.points
            ],
        )
        return _csv_response(body, f"analytics-timeseries-{series.bucket}")
    if view == "feedback":
        comments = await an.feedback_comments(db, f, limit=CSV_LIMIT)
        body = to_csv(
            ["created_at", "value", "comment", "project", "agent", "channel", "user", "run_id"],
            [
                [c.created_at, c.value, c.comment, c.project_name, c.workforce_name, c.channel, c.user, c.run_id]
                for c in comments
            ],
        )
        return _csv_response(body, "analytics-feedback")
    rows_out = await _breakdown(db, f, group_by, sort, CSV_LIMIT)
    if group_by == "model":
        body = to_csv(
            [
                "model",
                "name",
                "runs",
                "calls",
                "input_tokens",
                "output_tokens",
                "cost_usd",
                "errors",
                "p50_ms",
                "p95_ms",
            ],
            [
                [
                    r.key,
                    r.label,
                    r.runs,
                    r.calls,
                    r.input_tokens,
                    r.output_tokens,
                    r.cost_usd,
                    r.errors,
                    r.p50_ms,
                    r.p95_ms,
                ]
                for r in rows_out
            ],
        )
    else:
        body = to_csv(
            [
                "name",
                "project",
                "runs",
                "success",
                "errors",
                "success_rate",
                "cost_usd",
                "credits",
                "users",
                "p50_ms",
                "p95_ms",
                "last_run_at",
            ],
            [
                [
                    r.label or r.key,
                    r.project_name,
                    r.runs,
                    r.success,
                    r.errors,
                    r.success_rate,
                    r.cost_usd,
                    r.credits,
                    r.users,
                    r.p50_ms,
                    r.p95_ms,
                    r.last_run_at,
                ]
                for r in rows_out
            ],
        )
    return _csv_response(body, f"analytics-{group_by}")


# --------------------------------------------------------------------------------------------- eval comparison


class EvalVersionOut(BaseModel):
    key: str
    version_id: uuid.UUID | None
    number: int | None
    entity_type: str | None
    message: str | None
    git_commit: str | None
    created_at: datetime | None
    eval_runs: int
    passed: int
    failed: int
    errored_runs: int
    pass_rate: float | None
    last_eval_at: datetime
    inferred: bool


class EvalCellOut(BaseModel):
    passed: int
    total: int
    rate: float


class EvalCaseOut(BaseModel):
    name: str
    description: str | None
    results: dict[str, EvalCellOut]


class EvalComparisonOut(BaseModel):
    workforce: str
    kind: str
    versions: list[EvalVersionOut]
    cases: list[EvalCaseOut]


@router.get("/projects/{project_id}/workforce/{name}/evals/compare", response_model=EvalComparisonOut)
async def compare_evals(
    project_id: uuid.UUID,
    name: str,
    versions: int = Query(default=12, ge=1, le=50, description="Número de versiones más recientes"),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> EvalComparisonOut:
    """Pass rate per eval case across versions of one agent or workflow.

    Deployment gate evals carry their version. Manual evals run on the latest code, so they are attributed to
    the member's newest saved version at the time they ran (``inferred``), or to "sin versión" if none existed.
    """
    ensure_project_access(principal, project_id)
    member = (
        await db.execute(select(Workforce).where(Workforce.project_id == project_id, Workforce.name == name))
    ).scalar_one_or_none()
    if member is None:
        raise NotFound("Agente o flujo no encontrado", code="unknown_member")
    evals = list(
        (
            await db.execute(
                select(EvalRun)
                .where(EvalRun.workforce_id == member.id, EvalRun.status.in_(("passed", "failed", "error")))
                .order_by(EvalRun.created_at.desc())
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    referenced = {e.version_id for e in evals if e.version_id is not None}
    member_versions = list(
        (
            await db.execute(
                select(Version)
                .where(Version.entity_type == "workforce", Version.entity_id == member.id)
                .order_by(Version.created_at)
            )
        )
        .scalars()
        .all()
    )
    by_id: dict[uuid.UUID, Version] = {v.id: v for v in member_versions}
    missing = referenced - set(by_id)
    if missing:
        for v in (await db.execute(select(Version).where(Version.id.in_(missing)))).scalars().all():
            by_id[v.id] = v

    groups: dict[str, dict[str, Any]] = {}
    cases: dict[str, dict[str, Any]] = {}
    for e in evals:
        inferred = False
        version: Version | None = by_id.get(e.version_id) if e.version_id else None
        if version is None:
            prior = [v for v in member_versions if v.created_at <= e.created_at]
            version = prior[-1] if prior else None
            inferred = True
        key = str(version.id) if version is not None else "head"
        g = groups.setdefault(
            key,
            {
                "version": version,
                "inferred": inferred,
                "runs": 0,
                "passed": 0,
                "failed": 0,
                "errored": 0,
                "last": e.created_at,
            },
        )
        g["inferred"] = g["inferred"] and inferred
        g["runs"] += 1
        g["last"] = max(g["last"], e.created_at)
        run_error = False
        for res in e.results or []:
            if not isinstance(res, dict):
                continue
            case = res.get("name")
            if not case:
                run_error = run_error or bool(res.get("error"))
                continue
            passed = bool(res.get("passed"))
            g["passed" if passed else "failed"] += 1
            c = cases.setdefault(str(case), {"description": res.get("description"), "cells": {}})
            cell = c["cells"].setdefault(key, [0, 0])
            cell[0] += 1 if passed else 0
            cell[1] += 1
        if run_error or e.status == "error":
            g["errored"] += 1

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[datetime, datetime]:
        v: Version | None = item[1]["version"]
        anchor = v.created_at if v is not None else datetime.min.replace(tzinfo=UTC)
        return anchor, item[1]["last"]

    ordered = sorted(groups.items(), key=sort_key)[-versions:]
    kept = {k for k, _ in ordered}
    out_versions: list[EvalVersionOut] = []
    for key, g in ordered:
        v: Version | None = g["version"]
        total = g["passed"] + g["failed"]
        out_versions.append(
            EvalVersionOut(
                key=key,
                version_id=v.id if v else None,
                number=v.version if v else None,
                entity_type=v.entity_type if v else None,
                message=v.message if v else None,
                git_commit=v.git_commit if v else None,
                created_at=v.created_at if v else None,
                eval_runs=g["runs"],
                passed=g["passed"],
                failed=g["failed"],
                errored_runs=g["errored"],
                pass_rate=g["passed"] / total if total else None,
                last_eval_at=g["last"],
                inferred=bool(g["inferred"]),
            )
        )
    out_cases = [
        EvalCaseOut(
            name=case,
            description=data["description"],
            results={
                k: EvalCellOut(passed=p, total=t, rate=p / t) for k, (p, t) in data["cells"].items() if k in kept and t
            },
        )
        for case, data in sorted(cases.items())
    ]
    return EvalComparisonOut(
        workforce=member.name,
        kind=member.kind,
        versions=out_versions,
        cases=[c for c in out_cases if c.results],
    )
