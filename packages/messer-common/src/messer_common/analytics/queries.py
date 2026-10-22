"""AI analytics aggregations over ``runs``, ``spans`` and ``feedback`` (RLS-safe: callers pass their session).

Every query filters by ``org_id`` and the time window explicitly, so it uses ``ix_runs_org_started`` /
``ix_runs_project_started`` whether it runs on an RLS session (user requests) or the owner connection
(alarm evaluator). All user input reaches SQL as bound parameters; group-by keys and buckets come from
whitelists. GROUP BY / ORDER BY reference output aliases because bound parameters inside repeated
expressions are not recognised as identical by PostgreSQL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    Float,
    String,
    Text,
    cast,
    column,
    desc,
    distinct,
    func,
    literal,
    literal_column,
    nulls_last,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement, Label

from ..db.models import Feedback, ModelPrice, Org, Project, Run, Span, User
from .custom_metrics import models_array
from .filters import BUCKETS, FAILED_STATUSES, TERMINAL_STATUSES, Bucket, Filters, bucket_starts, localize, zone

GroupBy = Literal["org", "project", "agent", "channel", "environment", "user", "model"]
GROUP_BYS: tuple[GroupBy, ...] = ("org", "project", "agent", "channel", "environment", "user", "model")
SortKey = Literal["runs", "cost_usd", "errors", "error_rate", "p95_ms", "users", "credits", "last_run_at"]
SORT_KEYS: tuple[SortKey, ...] = (
    "runs",
    "cost_usd",
    "errors",
    "error_rate",
    "p95_ms",
    "users",
    "credits",
    "last_run_at",
)


# --------------------------------------------------------------------------------------------- results


@dataclass(slots=True)
class Kpis:
    runs: int = 0
    success: int = 0
    errors: int = 0
    terminal: int = 0
    cost_usd: Decimal = Decimal("0")
    credits: Decimal = Decimal("0")
    users: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None
    avg_ms: float | None = None
    last_run_at: datetime | None = None

    @property
    def success_rate(self) -> float | None:
        return self.success / self.terminal if self.terminal else None

    @property
    def error_rate(self) -> float | None:
        return self.errors / self.terminal if self.terminal else None


@dataclass(slots=True)
class FeedbackStats:
    up: int = 0
    down: int = 0

    @property
    def total(self) -> int:
        return self.up + self.down

    @property
    def up_ratio(self) -> float | None:
        return self.up / self.total if self.total else None


@dataclass(slots=True)
class FeedbackComment:
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


@dataclass(slots=True)
class ModelUsage:
    model: str
    label: str
    runs: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    errors: int = 0
    p50_ms: float | None = None
    p95_ms: float | None = None


@dataclass(slots=True)
class BreakdownRow:
    key: str
    label: str
    kpis: Kpis
    project_id: uuid.UUID | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Point:
    t: datetime
    kpis: Kpis


# --------------------------------------------------------------------------------------------- helpers


def _user_key() -> ColumnElement[Any]:
    """One identity per platform user or external (channel) user; runs without either are not counted."""
    return func.coalesce(cast(Run.user_id, String), literal("x:", String) + Run.external_user_id)


def kpi_columns() -> list[Label[Any]]:
    failed = Run.status.in_(FAILED_STATUSES)
    terminal = Run.status.in_(TERMINAL_STATUSES)
    return [
        func.count().label("runs"),
        func.count().filter(Run.status == "success").label("success"),
        func.count().filter(failed).label("errors"),
        func.count().filter(terminal).label("terminal"),
        func.coalesce(func.sum(Run.cost_usd), 0).label("cost_usd"),
        func.coalesce(func.sum(Run.credits), 0).label("credits"),
        func.count(distinct(_user_key())).label("users"),
        func.percentile_cont(0.5).within_group(Run.duration_ms).label("p50_ms"),
        func.percentile_cont(0.95).within_group(Run.duration_ms).label("p95_ms"),
        func.avg(Run.duration_ms).label("avg_ms"),
        func.max(Run.started_at).label("last_run_at"),
        (cast(func.count().filter(failed), Float) / func.nullif(func.count().filter(terminal), 0)).label("error_rate"),
    ]


def _f(value: Any) -> float | None:
    return float(value) if value is not None else None


def kpis_from(row: Any) -> Kpis:
    m = row._mapping
    return Kpis(
        runs=int(m["runs"] or 0),
        success=int(m["success"] or 0),
        errors=int(m["errors"] or 0),
        terminal=int(m["terminal"] or 0),
        cost_usd=Decimal(str(m["cost_usd"] or 0)),
        credits=Decimal(str(m["credits"] or 0)),
        users=int(m["users"] or 0),
        p50_ms=_f(m["p50_ms"]),
        p95_ms=_f(m["p95_ms"]),
        avg_ms=_f(m["avg_ms"]),
        last_run_at=m["last_run_at"],
    )


def _local_bucket(ts: ColumnElement[Any] | QueryableAttribute[Any], bucket: Bucket, tz: str) -> Label[Any]:
    # ``bucket`` is a whitelisted literal; the time zone is a bound parameter.
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    return func.date_trunc(literal_column(f"'{bucket}'"), func.timezone(tz, ts)).label("bucket")


# --------------------------------------------------------------------------------------------- queries


async def kpis(session: AsyncSession, f: Filters) -> Kpis:
    row = (await session.execute(select(*kpi_columns()).where(*f.run_conditions()))).one()
    return kpis_from(row)


async def timeseries(session: AsyncSession, f: Filters, *, bucket: Bucket, tz: str) -> list[Point]:
    zone(tz)
    starts = bucket_starts(f.since, f.until, bucket, tz)
    b = _local_bucket(Run.started_at, bucket, tz)
    rows = (
        await session.execute(
            select(b, *kpi_columns())
            .where(*f.run_conditions())
            .group_by(literal_column("bucket"))
            .order_by(literal_column("bucket"))
        )
    ).all()
    by_start = {r._mapping["bucket"]: kpis_from(r) for r in rows}
    return [Point(t=localize(s, tz), kpis=by_start.get(s, Kpis())) for s in starts]


async def feedback_stats(session: AsyncSession, f: Filters) -> FeedbackStats:
    q = (
        select(
            func.count().filter(Feedback.value == "up").label("up"),
            func.count().filter(Feedback.value == "down").label("down"),
        )
        .select_from(Feedback)
        .join(Run, Run.id == Feedback.run_id)
        .where(
            Feedback.org_id == f.org_id,
            Feedback.created_at >= f.since,
            Feedback.created_at < f.until,
            *f.scope_conditions(),
        )
    )
    row = (await session.execute(q)).one()
    return FeedbackStats(up=int(row.up or 0), down=int(row.down or 0))


async def feedback_comments(session: AsyncSession, f: Filters, *, limit: int = 20) -> list[FeedbackComment]:
    q = (
        select(Feedback, Run.workforce_name, Run.channel, Run.project_id, Project.name, User.email)
        .join(Run, Run.id == Feedback.run_id)
        .outerjoin(Project, Project.id == Run.project_id)
        .outerjoin(User, User.id == Feedback.user_id)
        .where(
            Feedback.org_id == f.org_id,
            Feedback.created_at >= f.since,
            Feedback.created_at < f.until,
            Feedback.comment.is_not(None),
            func.length(func.btrim(Feedback.comment)) > 0,
            *f.scope_conditions(),
        )
        .order_by(Feedback.created_at.desc())
        .limit(limit)
    )
    out: list[FeedbackComment] = []
    for fb, workforce_name, channel, project_id, project_name, email in (await session.execute(q)).all():
        out.append(
            FeedbackComment(
                id=fb.id,
                run_id=fb.run_id,
                value=fb.value,
                comment=fb.comment or "",
                created_at=fb.created_at,
                project_id=project_id,
                project_name=project_name,
                workforce_name=workforce_name,
                channel=channel,
                user=email or fb.external_user_id,
            )
        )
    return out


async def model_usage(session: AsyncSession, f: Filters, *, limit: int = 50) -> list[ModelUsage]:
    """Most-used models: calls, tokens, cost and latency from LLM spans; runs per model from ``runs.models``."""
    duration = Span.t1 - Span.t0
    span_rows = (
        await session.execute(
            select(
                Span.model.label("model"),
                func.count().label("calls"),
                func.count(distinct(Span.run_id)).label("runs"),
                func.coalesce(func.sum(Span.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(Span.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(Span.cost_usd), 0).label("cost_usd"),
                func.count().filter(Span.status == "error").label("errors"),
                func.percentile_cont(0.5).within_group(duration).label("p50_ms"),
                func.percentile_cont(0.95).within_group(duration).label("p95_ms"),
            )
            .select_from(Span)
            .join(Run, Run.id == Span.run_id)
            .where(Span.org_id == f.org_id, Span.kind == "llm", Span.model.is_not(None), *f.run_conditions())
            .group_by(Span.model)
        )
    ).all()
    elem = func.jsonb_array_elements(models_array(Run.models)).table_valued(column("value", JSONB)).lateral("m")
    model_expr = elem.c.value.op("->>", return_type=Text)(literal_column("'model'")).label("model")
    run_rows = (
        await session.execute(
            select(model_expr, func.count(distinct(Run.id)).label("runs"))
            .select_from(Run)
            .join(elem, true())
            .where(*f.run_conditions())
            .group_by(literal_column("model"))
        )
    ).all()
    usage: dict[str, ModelUsage] = {}
    for r in span_rows:
        m = r._mapping
        name = str(m["model"])
        usage[name] = ModelUsage(
            model=name,
            label=name,
            runs=int(m["runs"] or 0),
            calls=int(m["calls"] or 0),
            input_tokens=int(m["input_tokens"] or 0),
            output_tokens=int(m["output_tokens"] or 0),
            cost_usd=Decimal(str(m["cost_usd"] or 0)),
            errors=int(m["errors"] or 0),
            p50_ms=_f(m["p50_ms"]),
            p95_ms=_f(m["p95_ms"]),
        )
    for r in run_rows:
        name = r._mapping["model"]
        if not name:
            continue
        entry = usage.setdefault(str(name), ModelUsage(model=str(name), label=str(name)))
        entry.runs = max(entry.runs, int(r._mapping["runs"] or 0))
    if usage:
        names = (
            await session.execute(
                select(ModelPrice.model, ModelPrice.display_name).where(ModelPrice.model.in_(list(usage)))
            )
        ).all()
        for model, display in names:
            if display:
                usage[model].label = display
    ranked = sorted(usage.values(), key=lambda u: (u.runs, u.calls, u.cost_usd), reverse=True)
    return ranked[:limit]


def _order(sort: SortKey) -> Any:
    if sort not in SORT_KEYS:
        raise ValueError(f"unknown sort key {sort!r}")
    return nulls_last(desc(literal_column(sort)))


async def breakdown(
    session: AsyncSession,
    f: Filters,
    group_by: GroupBy,
    *,
    sort: SortKey = "runs",
    limit: int = 50,
) -> list[BreakdownRow]:
    """KPIs per organization, project, agent, channel, environment or user (``model`` → :func:`model_usage`)."""
    if group_by == "model":
        raise ValueError("use model_usage() for the model breakdown")
    cols = kpi_columns()
    rows: list[BreakdownRow] = []
    if group_by == "org":
        kp = await kpis(session, f)
        org = await session.get(Org, f.org_id)
        return [BreakdownRow(key=str(f.org_id), label=org.name if org else "", kpis=kp)] if kp.runs else []
    if group_by == "project":
        q = (
            select(Run.project_id.label("project_id"), func.max(Project.name).label("project_name"), *cols)
            .select_from(Run)
            .outerjoin(Project, Project.id == Run.project_id)
            .where(*f.run_conditions())
            .group_by(Run.project_id)
        )
        for r in (await session.execute(q.order_by(_order(sort)).limit(limit))).all():
            m = r._mapping
            rows.append(
                BreakdownRow(
                    key=str(m["project_id"]),
                    label=m["project_name"] or "",
                    kpis=kpis_from(r),
                    project_id=m["project_id"],
                )
            )
        return rows
    if group_by == "agent":
        q = (
            select(
                Run.project_id.label("project_id"),
                Run.workforce_name.label("workforce_name"),
                func.max(Project.name).label("project_name"),
                *cols,
            )
            .select_from(Run)
            .outerjoin(Project, Project.id == Run.project_id)
            .where(*f.run_conditions())
            .group_by(Run.project_id, Run.workforce_name)
        )
        for r in (await session.execute(q.order_by(_order(sort)).limit(limit))).all():
            m = r._mapping
            rows.append(
                BreakdownRow(
                    key=f"{m['project_id']}:{m['workforce_name']}",
                    label=m["workforce_name"] or "",
                    kpis=kpis_from(r),
                    project_id=m["project_id"],
                    extra={"project_name": m["project_name"]},
                )
            )
        return rows
    if group_by in ("channel", "environment"):
        col = Run.channel if group_by == "channel" else Run.environment
        q = select(col.label("k"), *cols).where(*f.run_conditions()).group_by(col)
        for r in (await session.execute(q.order_by(_order(sort)).limit(limit))).all():
            k = str(r._mapping["k"] or "")
            rows.append(BreakdownRow(key=k, label=k, kpis=kpis_from(r)))
        return rows
    # user: platform users by id (with email/name) and external channel users by their external id.
    q = (
        select(
            Run.user_id.label("user_id"),
            Run.external_user_id.label("external_user_id"),
            func.max(User.email).label("email"),
            func.max(User.name).label("name"),
            *cols,
        )
        .select_from(Run)
        .outerjoin(User, User.id == Run.user_id)
        .where(*f.run_conditions())
        .group_by(Run.user_id, Run.external_user_id)
    )
    for r in (await session.execute(q.order_by(_order(sort)).limit(limit))).all():
        m = r._mapping
        if m["user_id"] is not None:
            key, label = f"u:{m['user_id']}", m["name"] or m["email"] or str(m["user_id"])
        elif m["external_user_id"]:
            key, label = f"x:{m['external_user_id']}", str(m["external_user_id"])
        else:
            key, label = "anonymous", ""
        rows.append(BreakdownRow(key=key, label=label, kpis=kpis_from(r), extra={"email": m["email"]}))
    return rows
