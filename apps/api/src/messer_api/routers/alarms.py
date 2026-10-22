"""/api/v1/alarms — thresholds on metrics (errors, latency, cost or custom metrics) with email/Slack alerts.

The scheduler evaluates enabled alarms every minute (``messer_scheduler.tasks.alarms``): the metric is computed
over the last ``window_minutes`` (scoped to the alarm's project, environment, run channel and agent) and compared
with the threshold. Transitions ok → firing → ok notify admins in-app, send the ``alarm_fired`` email and post
to Slack when those channels are selected, and are kept in the alarm history. Members read; admins manage.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import analytics as an
from messer_common import audit
from messer_common.analytics.metrics import metric_unit
from messer_common.db import Principal
from messer_common.db.models import Alarm, Connection, CustomMetric, Project
from messer_common.db.models.governance import AlarmEvent

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound
from ..services.analytics import compute

router = APIRouter(prefix="/alarms", tags=["alarms"])

Comparator = Literal[">", ">=", "<", "<=", "==", "!="]
DeliveryChannel = Literal["email", "slack"]
Environment = Literal["development", "production"]
MAX_WINDOW_MINUTES = 7 * 24 * 60


class InvalidAlarm(ApiError):
    status_code = 422
    code = "invalid_alarm"


def _finite(value: float) -> float:
    if not math.isfinite(value) or abs(value) > 1e12:
        raise ValueError("El umbral debe ser un número finito")
    return value


class AlarmIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    metric: str = Field(min_length=1, max_length=80)
    comparator: Comparator = ">"
    threshold: float
    window_minutes: int = Field(default=60, ge=1, le=MAX_WINDOW_MINUTES)
    channels: list[DeliveryChannel] = Field(default_factory=lambda: ["email"], max_length=2)
    environment: Environment | None = None
    run_channel: str | None = Field(default=None, min_length=1, max_length=20)
    workforce_name: str | None = Field(default=None, min_length=1, max_length=80)
    slack_channel: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool = True

    @field_validator("threshold")
    @classmethod
    def _threshold(cls, value: float) -> float:
        return _finite(value)

    @model_validator(mode="after")
    def _slack_target(self) -> AlarmIn:
        self.channels = list(dict.fromkeys(self.channels))
        if "slack" in self.channels and not (self.slack_channel or "").strip():
            raise ValueError("Indica el canal de Slack donde publicar la alarma")
        return self


class AlarmPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    metric: str | None = Field(default=None, min_length=1, max_length=80)
    comparator: Comparator | None = None
    threshold: float | None = None
    window_minutes: int | None = Field(default=None, ge=1, le=MAX_WINDOW_MINUTES)
    channels: list[DeliveryChannel] | None = Field(default=None, max_length=2)
    environment: Environment | None = None
    run_channel: str | None = Field(default=None, max_length=20)
    workforce_name: str | None = Field(default=None, max_length=80)
    slack_channel: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None

    @field_validator("threshold")
    @classmethod
    def _threshold(cls, value: float | None) -> float | None:
        return _finite(value) if value is not None else None


class AlarmOut(BaseModel):
    id: uuid.UUID
    name: str
    project_id: uuid.UUID | None
    project_name: str | None
    metric: str
    metric_name: str | None
    unit: str
    comparator: str
    threshold: float
    window_minutes: int
    channels: list[str]
    environment: str | None
    run_channel: str | None
    workforce_name: str | None
    slack_channel: str | None
    enabled: bool
    state: str
    last_value: float | None
    last_evaluated_at: datetime | None
    last_fired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AlarmEventOut(BaseModel):
    id: uuid.UUID
    from_state: str
    to_state: str
    value: float | None
    metric: str
    comparator: str
    threshold: float
    window_minutes: int
    delivery: dict[str, Any]
    created_at: datetime


class AlarmTestOut(BaseModel):
    value: float | None
    breached: bool
    unit: str
    state: str
    error: str | None
    evaluated_at: datetime


class MetricOption(BaseModel):
    key: str
    unit: str
    name: str | None = None


class AlarmCatalogOut(BaseModel):
    builtin: list[MetricOption]
    custom: list[MetricOption]
    slack_connected: bool


async def _custom_metric(session: AsyncSession, org_id: uuid.UUID, metric: str) -> CustomMetric | None:
    try:
        metric_id = an.custom_metric_id(metric)
    except an.UnknownMetric as exc:
        raise InvalidAlarm("Métrica desconocida", code="unknown_metric", details={"metric": metric}) from exc
    if metric_id is None:
        if metric not in an.BUILTIN_METRICS:
            raise InvalidAlarm("Métrica desconocida", code="unknown_metric", details={"metric": metric})
        return None
    row = await session.get(CustomMetric, metric_id)
    if row is None or row.org_id != org_id:
        raise InvalidAlarm("La métrica personalizada no existe", code="unknown_metric", details={"metric": metric})
    return row


async def _project(session: AsyncSession, principal: Principal, project_id: uuid.UUID | None) -> Project | None:
    if project_id is None:
        if principal.project_id is not None:
            raise ApiError("La API key está limitada a un proyecto", code="project_scope", status_code=403)
        return None
    ensure_project_access(principal, project_id)
    project = await session.get(Project, project_id)
    if project is None or project.org_id != principal.org_id:
        raise NotFound("Proyecto no encontrado", code="unknown_project")
    return project


async def _out(session: AsyncSession, alarm: Alarm) -> AlarmOut:
    custom: CustomMetric | None = None
    try:
        metric_id = an.custom_metric_id(alarm.metric)
    except an.UnknownMetric:
        metric_id = None
    if metric_id is not None:
        found = await session.get(CustomMetric, metric_id)
        custom = found if found is not None and found.org_id == alarm.org_id else None
    project = await session.get(Project, alarm.project_id) if alarm.project_id else None
    cfg = alarm.config or {}
    return AlarmOut(
        id=alarm.id,
        name=alarm.name,
        project_id=alarm.project_id,
        project_name=project.name if project else None,
        metric=alarm.metric,
        metric_name=custom.name if custom else None,
        unit=metric_unit(alarm.metric, custom),
        comparator=alarm.comparator,
        threshold=float(alarm.threshold),
        window_minutes=alarm.window_minutes,
        channels=[str(c) for c in (alarm.channels or [])],
        environment=cfg.get("environment"),
        run_channel=cfg.get("channel"),
        workforce_name=cfg.get("workforce_name"),
        slack_channel=cfg.get("slack_channel"),
        enabled=alarm.enabled,
        state=alarm.state,
        last_value=alarm.last_value,
        last_evaluated_at=alarm.last_evaluated_at,
        last_fired_at=alarm.last_fired_at,
        created_at=alarm.created_at,
        updated_at=alarm.updated_at,
    )


async def _get(session: AsyncSession, principal: Principal, alarm_id: uuid.UUID) -> Alarm:
    alarm = await session.get(Alarm, alarm_id)
    if alarm is None or alarm.org_id != principal.org_id:
        raise NotFound("Alarma no encontrada", code="unknown_alarm")
    if principal.project_id is not None and alarm.project_id != principal.project_id:
        raise NotFound("Alarma no encontrada", code="unknown_alarm")
    return alarm


def _snapshot(a: Alarm) -> dict[str, Any]:
    return {
        "name": a.name,
        "project_id": a.project_id,
        "metric": a.metric,
        "comparator": a.comparator,
        "threshold": a.threshold,
        "window_minutes": a.window_minutes,
        "channels": list(a.channels or []),
        "config": dict(a.config or {}),
        "enabled": a.enabled,
    }


def _config(
    environment: str | None, run_channel: str | None, workforce: str | None, slack: str | None
) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if environment:
        cfg["environment"] = environment
    if run_channel and run_channel.strip():
        cfg["channel"] = run_channel.strip()
    if workforce and workforce.strip():
        cfg["workforce_name"] = workforce.strip()
    if slack and slack.strip():
        cfg["slack_channel"] = slack.strip()
    return cfg


@router.get("/metrics", response_model=AlarmCatalogOut)
async def alarm_catalog(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> AlarmCatalogOut:
    """Metrics an alarm can watch and whether Slack delivery is available."""
    assert principal.org_id is not None
    customs = (
        (
            await db.execute(
                select(CustomMetric).where(CustomMetric.org_id == principal.org_id).order_by(CustomMetric.name)
            )
        )
        .scalars()
        .all()
    )
    slack = (
        await db.execute(
            select(Connection.id)
            .where(
                Connection.org_id == principal.org_id,
                Connection.connector_key == "slack",
                Connection.status.in_(("active", "demo")),
            )
            .limit(1)
        )
    ).first()
    return AlarmCatalogOut(
        builtin=[MetricOption(key=m.key, unit=m.unit) for m in an.BUILTIN_METRICS.values()],
        custom=[
            MetricOption(key=f"{an.CUSTOM_PREFIX}{c.id}", unit=metric_unit(f"{an.CUSTOM_PREFIX}{c.id}", c), name=c.name)
            for c in customs
        ],
        slack_connected=slack is not None,
    )


@router.get("", response_model=list[AlarmOut])
async def list_alarms(
    project_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[AlarmOut]:
    assert principal.org_id is not None
    q = select(Alarm).where(Alarm.org_id == principal.org_id)
    scope = principal.project_id or project_id
    if scope is not None:
        q = q.where(Alarm.project_id == scope)
    rows = (await db.execute(q.order_by(Alarm.state.asc(), Alarm.name))).scalars().all()  # 'firing' sorts before 'ok'
    return [await _out(db, a) for a in rows]


@router.post("", response_model=AlarmOut, status_code=201)
async def create_alarm(
    body: AlarmIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> AlarmOut:
    assert principal.org_id is not None
    await _project(db, principal, body.project_id)
    await _custom_metric(db, principal.org_id, body.metric)
    alarm = Alarm(
        org_id=principal.org_id,
        project_id=body.project_id,
        name=body.name.strip(),
        metric=body.metric,
        comparator=body.comparator,
        threshold=body.threshold,
        window_minutes=body.window_minutes,
        channels=list(body.channels),
        config=_config(body.environment, body.run_channel, body.workforce_name, body.slack_channel),
        enabled=body.enabled,
        state="ok",
    )
    db.add(alarm)
    await db.flush()
    await audit.record(
        db, action="alarm.created", principal=principal, entity_type="alarm", entity_id=alarm.id, diff=_snapshot(alarm)
    )
    await db.refresh(alarm)
    return await _out(db, alarm)


@router.get("/{alarm_id}", response_model=AlarmOut)
async def get_alarm(
    alarm_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> AlarmOut:
    return await _out(db, await _get(db, principal, alarm_id))


@router.patch("/{alarm_id}", response_model=AlarmOut)
async def update_alarm(
    alarm_id: uuid.UUID,
    body: AlarmPatch,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> AlarmOut:
    assert principal.org_id is not None
    alarm = await _get(db, principal, alarm_id)
    before = _snapshot(alarm)
    changes = body.model_dump(exclude_unset=True)
    if "project_id" in changes:
        await _project(db, principal, body.project_id)
        alarm.project_id = body.project_id
    if body.metric is not None:
        await _custom_metric(db, principal.org_id, body.metric)
        alarm.metric = body.metric
    if body.name is not None:
        alarm.name = body.name.strip()
    if body.comparator is not None:
        alarm.comparator = body.comparator
    if body.threshold is not None:
        alarm.threshold = body.threshold
    if body.window_minutes is not None:
        alarm.window_minutes = body.window_minutes
    if body.channels is not None:
        alarm.channels = list(dict.fromkeys(body.channels))
    cfg = dict(alarm.config or {})
    merged = _config(
        changes.get("environment", cfg.get("environment")),
        changes.get("run_channel", cfg.get("channel")),
        changes.get("workforce_name", cfg.get("workforce_name")),
        changes.get("slack_channel", cfg.get("slack_channel")),
    )
    if "slack" in (alarm.channels or []) and not merged.get("slack_channel"):
        raise InvalidAlarm("Indica el canal de Slack donde publicar la alarma", code="slack_channel_required")
    alarm.config = merged
    if body.enabled is not None:
        alarm.enabled = body.enabled
        if not body.enabled:
            # A paused alarm starts clean when it is enabled again (no "resolved" notice for a stale state).
            alarm.state = "ok"
    if {
        "metric",
        "comparator",
        "threshold",
        "window_minutes",
        "project_id",
        "environment",
        "run_channel",
        "workforce_name",
    } & changes.keys():
        alarm.last_evaluated_at = None  # re-evaluate on the next scheduler tick
    alarm.updated_at = datetime.now(UTC)
    await db.flush()
    await audit.record(
        db,
        action="alarm.updated",
        principal=principal,
        entity_type="alarm",
        entity_id=alarm.id,
        diff={"before": before, "after": _snapshot(alarm)},
    )
    return await _out(db, alarm)


@router.delete("/{alarm_id}", status_code=204)
async def delete_alarm(
    alarm_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    alarm = await _get(db, principal, alarm_id)
    snapshot = _snapshot(alarm)
    await db.delete(alarm)
    await audit.record(
        db, action="alarm.deleted", principal=principal, entity_type="alarm", entity_id=alarm_id, diff=snapshot
    )
    return Response(status_code=204)


@router.get("/{alarm_id}/history", response_model=list[AlarmEventOut])
async def alarm_history(
    alarm_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=500),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[AlarmEventOut]:
    alarm = await _get(db, principal, alarm_id)
    rows = (
        (
            await db.execute(
                select(AlarmEvent)
                .where(AlarmEvent.alarm_id == alarm.id, AlarmEvent.org_id == alarm.org_id)
                .order_by(AlarmEvent.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        AlarmEventOut(
            id=e.id,
            from_state=e.from_state,
            to_state=e.to_state,
            value=e.value,
            metric=e.metric,
            comparator=e.comparator,
            threshold=e.threshold,
            window_minutes=e.window_minutes,
            delivery=e.delivery or {},
            created_at=e.created_at,
        )
        for e in rows
    ]


@router.post("/{alarm_id}/test", response_model=AlarmTestOut)
async def test_alarm(
    alarm_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> AlarmTestOut:
    """Compute the alarm's metric now and say whether it would fire (no state change, nothing is sent)."""
    alarm = await _get(db, principal, alarm_id)
    now = datetime.now(UTC)
    value, breached, error = await compute(db, alarm, now)
    custom = None
    try:
        metric_id = an.custom_metric_id(alarm.metric)
    except an.UnknownMetric:
        metric_id = None
    if metric_id is not None:
        custom = await db.get(CustomMetric, metric_id)
    return AlarmTestOut(
        value=value,
        breached=breached,
        unit=metric_unit(alarm.metric, custom),
        state=alarm.state,
        error=error,
        evaluated_at=now,
    )
