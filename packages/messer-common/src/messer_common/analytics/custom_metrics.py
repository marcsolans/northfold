"""Custom metrics defined over traces (spans) or runs, compiled to parameterized SQL.

A definition is::

    {"source": "spans" | "runs",
     "filter": {"kind", "name", "status", "model", "path_glob", "output_contains", "error"},
     "aggregate": "count" | "sum" | "avg" | "min" | "max" | "p50" | "p95",
     "field": "cost_usd" | "duration" | "tokens" | "input_tokens" | "output_tokens" | "credits"}

``name``, ``model`` and ``path_glob`` accept shell globs (``*``, ``?``), translated to escaped ``LIKE``
patterns; ``output_contains`` is a case-insensitive substring of the JSON output. Every value is a bound
parameter: nothing from the definition is ever concatenated into SQL text.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Float, Select, Text, case, cast, column, exists, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

from ..db.models import Run, Span
from .filters import BUCKETS, FAILED_STATUSES, Bucket, Filters, bucket_starts, localize, zone

Source = Literal["spans", "runs"]
Aggregate = Literal["count", "sum", "avg", "min", "max", "p50", "p95"]
FieldName = Literal["cost_usd", "duration", "tokens", "input_tokens", "output_tokens", "credits"]
SpanKind = Literal["llm", "tool", "step", "agent", "workflow", "guardrail", "guard"]

ADDITIVE: tuple[Aggregate, ...] = ("count", "sum")
UNITS: dict[str, str] = {
    "cost_usd": "usd",
    "duration": "ms",
    "tokens": "tokens",
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "credits": "credits",
}


class MetricFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SpanKind | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, min_length=1, max_length=20, pattern=r"^[a-z_]+$")
    model: str | None = Field(default=None, min_length=1, max_length=200)
    path_glob: str | None = Field(default=None, min_length=1, max_length=500)
    output_contains: str | None = Field(default=None, min_length=1, max_length=500)
    error: bool | None = None


class MetricDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: Source = "spans"
    filter: MetricFilter = Field(default_factory=MetricFilter)
    aggregate: Aggregate = Field(default="count", validation_alias=AliasChoices("aggregate", "aggregation"))
    field: FieldName | None = None

    @model_validator(mode="after")
    def _consistent(self) -> MetricDefinition:
        if self.aggregate == "count":
            self.field = None
        elif self.field is None:
            raise ValueError("«field» es obligatorio salvo para count")
        if self.source == "runs":
            if self.filter.kind is not None:
                raise ValueError("«kind» solo se aplica a spans")
            if self.filter.path_glob is not None:
                raise ValueError("«path_glob» solo se aplica a spans")
        if self.source == "spans" and self.field == "credits":
            raise ValueError("«credits» solo se aplica a ejecuciones (source=runs)")
        return self

    @property
    def unit(self) -> str:
        return "count" if self.field is None else UNITS[self.field]

    @property
    def additive(self) -> bool:
        return self.aggregate in ADDITIVE


def parse_definition(raw: dict[str, Any]) -> MetricDefinition:
    return MetricDefinition.model_validate(raw)


def glob_to_like(pattern: str) -> str:
    """Shell glob → LIKE pattern with ``\\`` as escape character (``%``, ``_`` and ``\\`` are literal)."""
    out: list[str] = []
    for ch in pattern:
        if ch == "*":
            out.append("%")
        elif ch == "?":
            out.append("_")
        elif ch in ("%", "_", "\\"):
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _substring(needle: str) -> str:
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def models_array(col: ColumnElement[Any] | QueryableAttribute[Any]) -> ColumnElement[Any]:
    """``runs.models`` as a JSON array (legacy or malformed values become ``[]`` instead of failing)."""
    return case((func.jsonb_typeof(col) == "array", col), else_=literal_column("'[]'::jsonb"))


def _has_error_json(col: ColumnElement[Any] | QueryableAttribute[Any]) -> ColumnElement[bool]:
    # SQL NULL and JSON null both mean "no error".
    return func.coalesce(func.jsonb_typeof(col), "null") != "null"


@dataclass(slots=True)
class Compiled:
    time: ColumnElement[Any] | QueryableAttribute[Any]
    value: ColumnElement[Any] | None
    base: Select[Any]


def _value_column(defn: MetricDefinition) -> ColumnElement[Any] | None:
    fld = defn.field
    if fld is None:
        return None
    if defn.source == "spans":
        return {
            "cost_usd": Span.cost_usd,
            "duration": Span.t1 - Span.t0,
            "tokens": Span.input_tokens + Span.output_tokens,
            "input_tokens": Span.input_tokens,
            "output_tokens": Span.output_tokens,
        }[fld]
    if fld in ("tokens", "input_tokens", "output_tokens"):
        tokens = {
            "tokens": Span.input_tokens + Span.output_tokens,
            "input_tokens": Span.input_tokens,
            "output_tokens": Span.output_tokens,
        }[fld]
        return (
            select(func.coalesce(func.sum(tokens), 0))
            .where(Span.run_id == Run.id, Span.org_id == Run.org_id)
            .correlate(Run)
            .scalar_subquery()
        )
    return {"cost_usd": Run.cost_usd, "credits": Run.credits, "duration": Run.duration_ms}[fld]


def compile_definition(defn: MetricDefinition, f: Filters) -> Compiled:
    flt = defn.filter
    conds: list[ColumnElement[bool]] = []
    if defn.source == "spans":
        since_ms = int(f.since.timestamp() * 1000)
        until_ms = int(f.until.timestamp() * 1000)
        base = select().select_from(Span)
        conds += [Span.org_id == f.org_id, Span.t0 >= since_ms, Span.t0 < until_ms]
        if f.has_run_scope:
            base = base.join(Run, Run.id == Span.run_id)
            conds += f.scope_conditions()
        if flt.kind is not None:
            conds.append(Span.kind == flt.kind)
        if flt.name is not None:
            conds.append(Span.name.like(glob_to_like(flt.name), escape="\\"))
        if flt.status is not None:
            conds.append(Span.status == flt.status)
        if flt.model is not None:
            conds.append(Span.model.like(glob_to_like(flt.model), escape="\\"))
        if flt.path_glob is not None:
            conds.append(Span.path.like(glob_to_like(flt.path_glob), escape="\\"))
        if flt.output_contains is not None:
            conds.append(cast(Span.output, Text).ilike(_substring(flt.output_contains), escape="\\"))
        if flt.error is not None:
            failed = or_(Span.status == "error", _has_error_json(Span.error))
            conds.append(failed if flt.error else ~failed)
        time: ColumnElement[Any] | QueryableAttribute[Any] = func.to_timestamp(cast(Span.t0, Float) / 1000.0)
    else:
        base = select().select_from(Run)
        conds += f.run_conditions()
        if flt.name is not None:
            conds.append(Run.workforce_name.like(glob_to_like(flt.name), escape="\\"))
        if flt.status is not None:
            conds.append(Run.status == flt.status)
        if flt.model is not None:
            elem = func.jsonb_array_elements(models_array(Run.models)).table_valued(column("value", JSONB))
            conds.append(
                exists(
                    select(literal_column("1"))
                    .select_from(elem)
                    .where(
                        elem.c.value.op("->>", return_type=Text)(literal_column("'model'")).like(
                            glob_to_like(flt.model), escape="\\"
                        )
                    )
                )
            )
        if flt.output_contains is not None:
            conds.append(cast(Run.output, Text).ilike(_substring(flt.output_contains), escape="\\"))
        if flt.error is not None:
            failed = Run.status.in_(FAILED_STATUSES)
            conds.append(failed if flt.error else ~failed)
        time = Run.started_at
    return Compiled(time=time, value=_value_column(defn), base=base.where(*conds))


def _aggregate(defn: MetricDefinition, value: ColumnElement[Any] | None) -> ColumnElement[Any]:
    if defn.aggregate == "count" or value is None:
        return func.count()
    if defn.aggregate == "sum":
        return func.coalesce(func.sum(value), 0)
    if defn.aggregate == "avg":
        return func.avg(value)
    if defn.aggregate == "min":
        return func.min(value)
    if defn.aggregate == "max":
        return func.max(value)
    pct = 0.5 if defn.aggregate == "p50" else 0.95
    return func.percentile_cont(pct).within_group(value)


@dataclass(slots=True)
class MetricPoint:
    t: datetime
    value: float | None


@dataclass(slots=True)
class MetricSeries:
    total: float | None
    points: list[MetricPoint]
    unit: str


async def metric_value(session: AsyncSession, defn: MetricDefinition, f: Filters) -> float | None:
    c = compile_definition(defn, f)
    q = c.base.add_columns(_aggregate(defn, c.value).label("v"))
    value = (await session.execute(q)).scalar_one()
    return float(value) if value is not None else (0.0 if defn.additive else None)


async def metric_series(
    session: AsyncSession, defn: MetricDefinition, f: Filters, *, bucket: Bucket, tz: str
) -> MetricSeries:
    if bucket not in BUCKETS:
        raise ValueError(f"unknown bucket {bucket!r}")
    zone(tz)
    starts = bucket_starts(f.since, f.until, bucket, tz)
    c = compile_definition(defn, f)
    b = func.date_trunc(literal_column(f"'{bucket}'"), func.timezone(tz, c.time)).label("bucket")
    q = (
        c.base.add_columns(b, _aggregate(defn, c.value).label("v"))
        .group_by(literal_column("bucket"))
        .order_by(literal_column("bucket"))
    )
    rows = {r._mapping["bucket"]: r._mapping["v"] for r in (await session.execute(q)).all()}
    empty = 0.0 if defn.additive else None
    points = [
        MetricPoint(t=localize(s, tz), value=float(rows[s]) if rows.get(s) is not None else empty) for s in starts
    ]
    return MetricSeries(total=await metric_value(session, defn, f), points=points, unit=defn.unit)


def metric_ref(metric_id: uuid.UUID) -> str:
    """Alarm ``metric`` value pointing at a custom metric."""
    return f"custom:{metric_id}"
