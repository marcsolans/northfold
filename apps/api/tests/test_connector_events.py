"""Connector events reach workflow triggers through messer_common.triggers.emit (spec 7.5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from messer_api.services.connector_events import EVENT_CURSORS_KEY, poll_connector_events
from messer_common.db import system_session
from messer_common.db.models import Connection, Project, Trigger, Workforce
from messer_common.security import encrypt_json
from messer_connectors.adapters.webhooks import sign


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_fire(trigger: Trigger, payload: dict[str, Any], *, event_id: str | None = None) -> str:
        calls.append({"trigger_id": trigger.id, "payload": payload, "event_id": event_id})
        return f"job-{len(calls)}"

    monkeypatch.setattr("messer_common.triggers.fire", fake_fire)
    return calls


async def _trigger(org_id: uuid.UUID, connection_id: uuid.UUID, event: str) -> uuid.UUID:
    async with system_session() as s:
        project = Project(org_id=org_id, name="Facturas", slug=f"facturas-{uuid.uuid4().hex[:6]}", repo_path="/tmp/p")
        s.add(project)
        await s.flush()
        member = Workforce(
            org_id=org_id, project_id=project.id, kind="workflow", name="avisos", path="workforce/avisos"
        )
        s.add(member)
        await s.flush()
        trigger = Trigger(
            org_id=org_id,
            project_id=project.id,
            workforce_id=member.id,
            kind="connector_event",
            config={"connection_id": str(connection_id), "event": event, "static_input": {}},
        )
        s.add(trigger)
        await s.flush()
        return trigger.id


async def test_polled_provider_events_fire_triggers(make_org, login, fired) -> None:  # type: ignore[no-untyped-def]
    org, user = await make_org()
    epoch = datetime.now(UTC) - timedelta(hours=10)
    async with system_session() as s:
        conn = Connection(
            org_id=org.id,
            connector_key="gmail",
            name="Gmail (demo)",
            credentials=encrypt_json({"access_token": "demo"}),
            config={"demo_epoch": epoch.isoformat()},
            status="demo",
            demo=True,
            created_by=user.id,
        )
        s.add(conn)
        await s.flush()
        conn_id = conn.id
    trigger_id = await _trigger(org.id, conn_id, "gmail.new_email")

    first = await poll_connector_events()
    assert first["connections"] == 1 and first["fired"] == 0  # baseline, no backfill
    async with system_session() as s:
        row = await s.get(Connection, conn_id)
        assert row is not None and row.config[EVENT_CURSORS_KEY]["new_email"]
        # Rewind the cursor to the demo epoch: the incoming demo emails are now "new".
        row.config = {**row.config, EVENT_CURSORS_KEY: {"new_email": str(int(epoch.timestamp() * 1000))}}

    second = await poll_connector_events()
    assert second["fired"] >= 4 and second["fired"] == second["events"]
    assert {c["trigger_id"] for c in fired} == {trigger_id}
    payload = fired[0]["payload"]
    assert payload["type"] == "gmail.new_email" and payload["connector"] == "gmail"
    assert payload["connection_id"] == str(conn_id) and payload["subject"] and payload["data"]["from_email"]
    assert fired[0]["event_id"].startswith("gmail.new_email:")

    third = await poll_connector_events()
    assert third["fired"] == 0  # cursor advanced

    client = await login(user.email)
    listed = (await client.get("/api/v1/connections")).json()
    assert EVENT_CURSORS_KEY not in listed[0]["config"] and "demo_epoch" not in listed[0]["config"]


async def test_webhook_and_sync_events_are_pushed(make_org, login, fired) -> None:  # type: ignore[no-untyped-def]
    org, user = await make_org()
    client = await login(user.email)
    conn = (await client.post("/api/v1/connections", json={"connector_key": "webhooks"})).json()
    await _trigger(org.id, uuid.UUID(conn["id"]), "*")
    secret = (await client.get(f"/api/v1/connections/{conn['id']}/webhook")).json()["secret"]
    body = json.dumps({"order": 88213}).encode()
    res = await client.post(
        f"/api/v1/webhooks/connections/{conn['id']}", content=body, headers={"X-Messer-Signature": sign(secret, body)}
    )
    assert res.status_code == 202
    assert len(fired) == 1
    assert fired[0]["payload"]["type"] == "webhooks.received"
    assert fired[0]["payload"]["data"]["payload"] == {"order": 88213}
    assert fired[0]["event_id"] == f"webhooks.received:{res.json()['id']}"

    detail = (await client.get("/api/v1/connectors/google_drive")).json()
    names = {e["name"]: e for e in detail["events"]}
    assert names["google_drive.new_file"]["delivery"] == "poll"
    assert names["google_drive.sync_completed"]["delivery"] == "push"
    async with system_session() as s:
        triggers = (await s.execute(select(Trigger).where(Trigger.org_id == org.id))).scalars().all()
    assert len(triggers) == 1
