"""/api/v1/metrics — custom metrics defined on traces (§7.11), usable in charts and alarms.

A definition picks a source (``spans`` or ``runs``), a filter (kind, name, status, model, path glob, output
substring, error), an aggregate (count, sum, avg, min, max, p50, p95) and a field (cost, duration, tokens,
credits). Values are computed with parameterized SQL over the analytics filters. Members read; admins manage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import analytics as an
from messer_common import audit
from messer_common.analytics.filters import zone
from messer_common.db import Principal
from messer_common.db.models import Alarm, CustomMetric

from ..deps import get_db, require_role
from ..errors import ApiError, Conflict, NotFound
from ..services.analytics import InvalidQuery
from .analytics import DEFAULT_TZ, scoped_filters

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    definition: an.MetricDefinition


class MetricPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    definition: an.MetricDefinition | None = None


class MetricOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str
    definition: dict[str, Any]
    unit: str
    valid: bool
    alarm_count: int
    created_at: datetime


class MetricPointOut(BaseModel):
    t: datetime
    value: float | None


class MetricValuesOut(BaseModel):
    since: datetime
    until: datetime
    bucket: str
    tz: str
    unit: str
    total: float | None
    points: list[MetricPointOut]


class PreviewIn(BaseModel):
    definition: an.MetricDefinition


def _definition_dict(defn: an.MetricDefinition) -> dict[str, Any]:
    return defn.model_dump(mode="json", exclude_none=False)


def _parsed(row: CustomMetric) -> an.MetricDefinition | None:
    try:
        return an.parse_definition(row.definition or {})
    except ValidationError:
        return None


async def _alarm_counts(session: AsyncSession, org_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Alarm.metric, func.count())
            .where(Alarm.org_id == org_id, Alarm.metric.like(f"{an.CUSTOM_PREFIX}%"))
            .group_by(Alarm.metric)
        )
    ).all()
    return {metric: int(n) for metric, n in rows}


def _out(row: CustomMetric, alarm_count: int) -> MetricOut:
    defn = _parsed(row)
    return MetricOut(
        id=row.id,
        name=row.name,
        description=row.description,
        definition=row.definition or {},
        unit=defn.unit if defn else "count",
        valid=defn is not None,
        alarm_count=alarm_count,
        created_at=row.created_at,
    )


async def _get(session: AsyncSession, principal: Principal, metric_id: uuid.UUID) -> CustomMetric:
    row = await session.get(CustomMetric, metric_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Métrica no encontrada", code="unknown_metric")
    return row


async def _ensure_unique(session: AsyncSession, org_id: uuid.UUID, name: str, exclude: uuid.UUID | None) -> None:
    q = select(CustomMetric.id).where(CustomMetric.org_id == org_id, func.lower(CustomMetric.name) == name.lower())
    if exclude is not None:
        q = q.where(CustomMetric.id != exclude)
    if (await session.execute(q)).first() is not None:
        raise Conflict("Ya existe una métrica con ese nombre", code="metric_exists")


async def _series(
    session: AsyncSession, defn: an.MetricDefinition, f: an.Filters, bucket: an.Bucket | None, tz: str
) -> MetricValuesOut:
    try:
        zone(tz)
        chosen: an.Bucket = bucket or an.auto_bucket(f.since, f.until)
        series = await an.metric_series(session, defn, f, bucket=chosen, tz=tz)
    except an.AnalyticsError as exc:
        raise InvalidQuery(exc.message, code=exc.code) from exc
    return MetricValuesOut(
        since=f.since,
        until=f.until,
        bucket=chosen,
        tz=tz,
        unit=series.unit,
        total=series.total,
        points=[MetricPointOut(t=p.t, value=p.value) for p in series.points],
    )


@router.get("", response_model=list[MetricOut])
async def list_metrics(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[MetricOut]:
    assert principal.org_id is not None
    rows = (
        (
            await db.execute(
                select(CustomMetric).where(CustomMetric.org_id == principal.org_id).order_by(CustomMetric.name)
            )
        )
        .scalars()
        .all()
    )
    counts = await _alarm_counts(db, principal.org_id)
    return [_out(r, counts.get(f"{an.CUSTOM_PREFIX}{r.id}", 0)) for r in rows]


@router.post("", response_model=MetricOut, status_code=201)
async def create_metric(
    body: MetricIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> MetricOut:
    assert principal.org_id is not None
    name = body.name.strip()
    await _ensure_unique(db, principal.org_id, name, None)
    row = CustomMetric(
        org_id=principal.org_id,
        name=name,
        description=body.description.strip(),
        definition=_definition_dict(body.definition),
    )
    db.add(row)
    await db.flush()
    await audit.record(
        db,
        action="custom_metric.created",
        principal=principal,
        entity_type="custom_metric",
        entity_id=row.id,
        diff={"name": row.name, "definition": row.definition},
    )
    await db.refresh(row)
    return _out(row, 0)


@router.post("/preview", response_model=MetricValuesOut)
async def preview_metric(
    body: PreviewIn,
    bucket: an.Bucket | None = None,
    tz: str = Query(default=DEFAULT_TZ, max_length=64),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> MetricValuesOut:
    """Evaluate a definition without saving it (editor preview)."""
    return await _series(db, body.definition, f, bucket, tz)


@router.get("/{metric_id}", response_model=MetricOut)
async def get_metric(
    metric_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> MetricOut:
    assert principal.org_id is not None
    row = await _get(db, principal, metric_id)
    counts = await _alarm_counts(db, principal.org_id)
    return _out(row, counts.get(f"{an.CUSTOM_PREFIX}{row.id}", 0))


@router.patch("/{metric_id}", response_model=MetricOut)
async def update_metric(
    metric_id: uuid.UUID,
    body: MetricPatch,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> MetricOut:
    assert principal.org_id is not None
    row = await _get(db, principal, metric_id)
    before = {"name": row.name, "description": row.description, "definition": row.definition}
    if body.name is not None:
        await _ensure_unique(db, principal.org_id, body.name.strip(), row.id)
        row.name = body.name.strip()
    if body.description is not None:
        row.description = body.description.strip()
    if body.definition is not None:
        row.definition = _definition_dict(body.definition)
    await db.flush()
    await audit.record(
        db,
        action="custom_metric.updated",
        principal=principal,
        entity_type="custom_metric",
        entity_id=row.id,
        diff={
            "before": before,
            "after": {"name": row.name, "description": row.description, "definition": row.definition},
        },
    )
    counts = await _alarm_counts(db, principal.org_id)
    return _out(row, counts.get(f"{an.CUSTOM_PREFIX}{row.id}", 0))


@router.delete("/{metric_id}", status_code=204)
async def delete_metric(
    metric_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    assert principal.org_id is not None
    row = await _get(db, principal, metric_id)
    alarms = (
        await db.execute(
            select(Alarm.id, Alarm.name).where(
                Alarm.org_id == principal.org_id, Alarm.metric == f"{an.CUSTOM_PREFIX}{row.id}"
            )
        )
    ).all()
    if alarms:
        raise Conflict(
            "Hay alarmas que usan esta métrica. Elimínalas o cámbialas antes de borrarla.",
            code="metric_in_use",
            details={"alarms": [{"id": str(a_id), "name": a_name} for a_id, a_name in alarms]},
        )
    snapshot = {"name": row.name, "definition": row.definition}
    await db.delete(row)
    await audit.record(
        db,
        action="custom_metric.deleted",
        principal=principal,
        entity_type="custom_metric",
        entity_id=metric_id,
        diff=snapshot,
    )
    return Response(status_code=204)


@router.get("/{metric_id}/values", response_model=MetricValuesOut)
async def metric_values(
    metric_id: uuid.UUID,
    bucket: an.Bucket | None = None,
    tz: str = Query(default=DEFAULT_TZ, max_length=64),
    principal: Principal = Depends(require_role("viewer")),
    f: an.Filters = Depends(scoped_filters),
    db: AsyncSession = Depends(get_db),
) -> MetricValuesOut:
    row = await _get(db, principal, metric_id)
    defn = _parsed(row)
    if defn is None:
        raise ApiError(
            "La definición guardada de esta métrica ya no es válida: edítala", code="invalid_metric", status_code=422
        )
    return await _series(db, defn, f, bucket, tz)
