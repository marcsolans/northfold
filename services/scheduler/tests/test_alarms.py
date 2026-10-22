"""Alarm evaluator (scheduler task ``alarms.evaluate``): ok → firing → ok transitions with history, in-app
notices to admins (each in their language), the ``alarm_fired`` email, Slack delivery through the org's Slack
connection (or a logged skip), custom metrics, scopes, no duplicate notices, and isolation between orgs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from messer_api.services.analytics import run_alarm_sweep
from messer_common.db import system_session
from messer_common.db.models import (
    Alarm,
    Connection,
    Connector,
    CustomMetric,
    Membership,
    Notification,
    Project,
    Run,
    Span,
    User,
)
from messer_common.db.models.governance import AlarmEvent
from messer_common.email import ConsoleEmailAdapter
from messer_common.security import encrypt_json
from messer_scheduler.core import discover_tasks
from messer_scheduler.tasks.alarms import evaluate_alarms


async def _project(org_id: uuid.UUID, name: str = "Soporte") -> uuid.UUID:
    async with system_session() as s:
        p = Project(org_id=org_id, name=name, slug=f"p-{uuid.uuid4().hex[:8]}", repo_path="/tmp/alarms")
        s.add(p)
        await s.flush()
        return p.id


async def _runs(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    statuses: list[str],
    *,
    at: datetime | None = None,
    environment: str = "production",
    tool: str | None = None,
) -> None:
    started = at or datetime.now(UTC) - timedelta(minutes=5)
    async with system_session() as s:
        for status in statuses:
            run_id = uuid.uuid4()
            s.add(
                Run(
                    id=run_id,
                    org_id=org_id,
                    project_id=project_id,
                    workforce_name="soporte",
                    status=status,
                    cost_usd=Decimal("0.01"),
                    duration_ms=100,
                    started_at=started,
                    environment=environment,
                )
            )
            if tool:
                await s.flush()
                t0 = int(started.timestamp() * 1000)
                s.add(Span(org_id=org_id, run_id=run_id, call_id="c", kind="tool", name=tool, t0=t0, t1=t0 + 10))


async def _alarm(org_id: uuid.UUID, **values: Any) -> uuid.UUID:
    data: dict[str, Any] = {
        "name": "Errores",
        "metric": "error_rate",
        "comparator": ">",
        "threshold": 20.0,
        "window_minutes": 60,
        "channels": ["email"],
        **values,
    }
    async with system_session() as s:
        alarm = Alarm(org_id=org_id, **data)
        s.add(alarm)
        await s.flush()
        return alarm.id


async def _state(alarm_id: uuid.UUID) -> Alarm:
    async with system_session() as s:
        alarm = await s.get(Alarm, alarm_id)
        assert alarm is not None
        return alarm


async def _events(alarm_id: uuid.UUID) -> list[AlarmEvent]:
    async with system_session() as s:
        return list(
            (await s.execute(select(AlarmEvent).where(AlarmEvent.alarm_id == alarm_id).order_by(AlarmEvent.created_at)))
            .scalars()
            .all()
        )


async def _notifications(user_id: uuid.UUID) -> list[Notification]:
    async with system_session() as s:
        return list(
            (
                await s.execute(
                    select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at)
                )
            )
            .scalars()
            .all()
        )


def _alarm_mails(to: str) -> list[str]:
    return [e.subject for e in ConsoleEmailAdapter.sent if e.to == to and e.tags == ["alarm_fired"]]


def test_alarm_task_is_registered_every_minute() -> None:
    task = next(t for t in discover_tasks() if t.name == "alarms.evaluate")
    assert task.interval_s == 60


async def test_fire_then_resolve_with_notifications_and_history(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    admin_en = await make_user()
    viewer = await make_user()
    org, _ = await make_org(owner=owner, members={str(admin_en.id): "admin", str(viewer.id): "viewer"})
    async with system_session() as s:
        await s.execute(update(User).where(User.id == admin_en.id).values(locale="en"))
    project = await _project(org.id)
    alarm_id = await _alarm(org.id, project_id=project, name="Errores soporte", config={"environment": "production"})
    await _runs(org.id, project, ["success", "success", "error"])
    await _runs(org.id, project, ["error", "error"], environment="development")  # out of scope
    ConsoleEmailAdapter.sent.clear()

    now = datetime.now(UTC)
    outcomes = await run_alarm_sweep(now=now)
    mine = next(o for o in outcomes if o.alarm_id == alarm_id)
    assert mine.transitioned and mine.state == "firing" and abs((mine.value or 0) - 100 / 3) < 1e-3
    alarm = await _state(alarm_id)
    assert alarm.state == "firing" and alarm.last_fired_at is not None and alarm.last_value is not None
    events = await _events(alarm_id)
    assert [(e.from_state, e.to_state) for e in events] == [("ok", "firing")]
    assert events[0].delivery == {"in_app": 2, "email": 2}
    assert _alarm_mails(owner.email) == ["Alarma: Errores soporte · Soporte"]
    assert _alarm_mails(admin_en.email) == ["Alarm: Errores soporte · Soporte"]
    assert _alarm_mails(viewer.email) == []
    owner_notes = await _notifications(owner.id)
    assert [n.kind for n in owner_notes] == ["alarm.firing"]
    assert "33.3 %" in owner_notes[0].payload["body"] and owner_notes[0].payload["url"].startswith(
        "/app/analytics/alarms"
    )
    english = await _notifications(admin_en.id)
    assert english[0].payload["title"].startswith("Alarm:") and "Error rate" in english[0].payload["body"]
    assert await _notifications(viewer.id) == []

    # Still firing a minute later: no new transition, no duplicate notices.
    again = await run_alarm_sweep(now=now + timedelta(seconds=61))
    assert not next(o for o in again if o.alarm_id == alarm_id).transitioned
    assert len(await _events(alarm_id)) == 1 and len(_alarm_mails(owner.email)) == 1
    # Evaluations closer than the minimum interval are skipped.
    assert all(o.alarm_id != alarm_id for o in await run_alarm_sweep(now=now + timedelta(seconds=70)))

    await _runs(org.id, project, ["success"] * 7)
    await evaluate_alarms()  # the scheduler entry point (real clock)
    alarm = await _state(alarm_id)
    assert alarm.state == "ok" and abs((alarm.last_value or 0) - 10.0) < 1e-6
    events = await _events(alarm_id)
    assert [(e.from_state, e.to_state) for e in events] == [("ok", "firing"), ("firing", "ok")]
    assert events[1].delivery == {"in_app": 2, "email": 0}
    assert len(_alarm_mails(owner.email)) == 1  # resolution is in-app only
    resolved = (await _notifications(owner.id))[-1]
    assert resolved.kind == "alarm.resolved" and resolved.payload["title"] == "Alarma resuelta: Errores soporte"
    assert (await _notifications(admin_en.id))[-1].payload["title"] == "Alarm resolved: Errores soporte"


async def test_slack_delivery_skip_demo_and_failure(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    project = await _project(org.id)
    await _runs(org.id, project, ["error"])
    no_conn = await _alarm(
        org.id, name="Sin conexión", channels=["slack"], config={"slack_channel": "#soporte-clientes"}
    )
    no_target = await _alarm(org.id, name="Sin canal", channels=["slack", "email"])
    now = datetime.now(UTC)
    await run_alarm_sweep(now=now, org_id=org.id)
    assert (await _events(no_conn))[0].delivery["slack"] == "skipped:no_connection"
    assert (await _events(no_target))[0].delivery["slack"] == "skipped:no_channel"

    async with system_session() as s:
        await s.execute(
            insert(Connector)
            .values(key="slack", name="Slack", category="communication", auth_type="oauth2")
            .on_conflict_do_nothing()
        )
        s.add(
            Connection(
                org_id=org.id,
                connector_key="slack",
                name="Slack (demo)",
                credentials=encrypt_json(
                    {"access_token": "demo", "token_type": "Bearer", "expires_at": None, "extra": {}}
                ),
                status="demo",
                demo=True,
                config={"demo_epoch": now.isoformat()},
            )
        )
    demo = await _alarm(org.id, name="Demo", channels=["slack"], config={"slack_channel": "#soporte-clientes"})
    wrong = await _alarm(org.id, name="Canal inexistente", channels=["slack"], config={"slack_channel": "#nada"})
    await run_alarm_sweep(now=now + timedelta(minutes=2), org_id=org.id)
    assert (await _events(demo))[0].delivery["slack"] == "demo"
    assert (await _events(wrong))[0].delivery["slack"].startswith("failed:")
    # Email channel not selected: in-app only.
    assert (await _events(demo))[0].delivery["email"] == 0


async def test_custom_metric_scopes_no_data_and_isolation(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    other_owner = await make_user()
    other, _ = await make_org(owner=other_owner, name="Other")
    project = await _project(org.id)
    other_project = await _project(other.id, "Ajeno")
    async with system_session() as s:
        metric = CustomMetric(
            org_id=org.id,
            name="Emails enviados",
            definition={"source": "spans", "filter": {"kind": "tool", "name": "enviar_*"}, "aggregate": "count"},
        )
        s.add(metric)
        await s.flush()
        metric_id = metric.id
    custom = await _alarm(org.id, name="Demasiados emails", metric=f"custom:{metric_id}", threshold=2, comparator=">=")
    latency = await _alarm(org.id, name="Lento", metric="latency_p95_ms", threshold=5000)
    disabled = await _alarm(org.id, name="Pausada", metric="runs", threshold=0, enabled=False)
    broken = await _alarm(org.id, name="Rota", metric=f"custom:{uuid.uuid4()}", threshold=1)
    old = datetime.now(UTC) - timedelta(hours=3)
    await _runs(org.id, project, ["success"], tool="enviar_email")
    await _runs(org.id, project, ["success"], tool="enviar_email", at=old)  # outside the 60-minute window
    await _runs(other.id, other_project, ["success"] * 5, tool="enviar_email")  # another organization

    outcomes = {o.alarm_id: o for o in await run_alarm_sweep(org_id=org.id)}
    assert outcomes[custom].value == 1.0 and outcomes[custom].state == "ok"
    assert outcomes[latency].value == 100.0 and not outcomes[latency].breached
    assert disabled not in outcomes
    assert outcomes[broken].error == "unknown_metric" and (await _state(broken)).state == "ok"

    await _runs(org.id, project, ["success"], tool="enviar_factura")
    async with system_session() as s:
        await s.execute(update(Alarm).where(Alarm.org_id == org.id).values(last_evaluated_at=None))
    outcomes = {o.alarm_id: o for o in await run_alarm_sweep(org_id=org.id)}
    assert outcomes[custom].transitioned and outcomes[custom].state == "firing" and outcomes[custom].value == 2.0

    # No data: rates and percentiles are undefined and never fire.
    empty_owner = await make_user()
    empty, _ = await make_org(owner=empty_owner, name="Vacía")
    quiet = await _alarm(empty.id, name="Sin ejecuciones", metric="error_rate", comparator=">=", threshold=0)
    count = await _alarm(empty.id, name="Pocas ejecuciones", metric="runs", comparator="<", threshold=1)
    outcomes = {o.alarm_id: o for o in await run_alarm_sweep(org_id=empty.id)}
    assert outcomes[quiet].value is None and outcomes[quiet].state == "ok"
    assert outcomes[count].value == 0.0 and outcomes[count].state == "firing"
    async with system_session() as s:
        members = (await s.execute(select(Membership.user_id).where(Membership.org_id == other.id))).scalars().all()
        assert (await s.execute(select(Notification).where(Notification.user_id.in_(members)))).first() is None
