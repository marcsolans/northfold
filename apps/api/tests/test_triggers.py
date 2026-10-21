"""Triggers: signed webhooks, cron scheduling, inbound email, firing runs, approval expiry."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from messer_common import triggers
from messer_common.db import system_session
from messer_common.db.models import Approval, Run, Trigger
from messer_common.settings import get_settings
from messer_runtime.testing import Harness


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...], dict[str, Any]]]:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        calls.append((job, args, kwargs))

    monkeypatch.setattr(triggers, "enqueue", fake_enqueue)
    return calls


async def _project(client: httpx.AsyncClient) -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": "ops@acme.example", "password": "Contrasena123"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Operaciones"})).json()["id"]
    assert (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "avisos"})).status_code == 201
    return str(pid)


async def test_webhook_signature_and_dedup(client: httpx.AsyncClient, queued) -> None:  # type: ignore[no-untyped-def]
    pid = await _project(client)
    created = await client.post(
        f"/api/v1/projects/{pid}/triggers",
        json={"workforce": "avisos", "kind": "webhook", "environment": "development"},
    )
    assert created.status_code == 201, created.text
    hook = created.json()
    assert hook["secret"].startswith("whsec_") and hook["webhook_url"].endswith(f"/api/hooks/{hook['id']}")
    body = json.dumps({"pedido": 1043}).encode()
    signed = {
        "X-Messer-Signature": triggers.sign(hook["secret"], body),
        "Content-Type": "application/json",
        "X-Messer-Event-Id": "evt-1",
    }
    ok = await client.post(f"/api/hooks/{hook['id']}", content=body, headers=signed)
    assert ok.status_code == 202, ok.text
    again = await client.post(f"/api/hooks/{hook['id']}", content=body, headers=signed)
    assert again.json()["job_id"] == ok.json()["job_id"]  # same event id → same job (deduplicated by the queue)
    bad = await client.post(
        f"/api/hooks/{hook['id']}", content=body, headers={"X-Messer-Signature": triggers.sign("whsec_wrong", body)}
    )
    assert bad.status_code == 401
    stale = await client.post(
        f"/api/hooks/{hook['id']}",
        content=body,
        headers={"X-Messer-Signature": triggers.sign(hook["secret"], body, 1_000_000)},
    )
    assert stale.status_code == 401
    assert [c[0] for c in queued] == ["fire_trigger", "fire_trigger"]
    assert queued[0][1][1]["body"] == {"pedido": 1043}
    listed = (await client.get(f"/api/v1/projects/{pid}/triggers")).json()
    assert "secret" not in listed[0]


async def test_cron_trigger_validation_and_schedule(client: httpx.AsyncClient, queued) -> None:  # type: ignore[no-untyped-def]
    from messer_scheduler.tasks.triggers import fire_due_cron

    pid = await _project(client)
    bad = await client.post(
        f"/api/v1/projects/{pid}/triggers",
        json={"workforce": "avisos", "kind": "cron", "config": {"expression": "cada lunes"}},
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_trigger"
    res = await client.post(
        f"/api/v1/projects/{pid}/triggers",
        json={
            "workforce": "avisos",
            "kind": "cron",
            "config": {"expression": "0 9 * * 1-5", "timezone": "Europe/Madrid"},
        },
    )
    assert res.status_code == 201, res.text
    trig = res.json()
    nxt = datetime.fromisoformat(trig["next_fire_at"])
    assert nxt.astimezone(triggers._zone("Europe/Madrid")).hour == 9
    async with system_session() as s:
        row = await s.get(Trigger, uuid.UUID(trig["id"]))
        assert row is not None
        row.next_fire_at = datetime.now(UTC) - timedelta(minutes=1)
    await fire_due_cron()
    assert [c[0] for c in queued] == ["fire_trigger"]
    async with system_session() as s:
        row = await s.get(Trigger, uuid.UUID(trig["id"]))
        assert row is not None and row.next_fire_at is not None and row.next_fire_at > datetime.now(UTC)
    await fire_due_cron()
    assert len(queued) == 1  # not due again


async def test_inbound_email_routes_by_address(
    client: httpx.AsyncClient,
    queued,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "messer_inbound_email_secret", "in-secret")
    pid = await _project(client)
    trig = (await client.post(f"/api/v1/projects/{pid}/triggers", json={"workforce": "avisos", "kind": "email"})).json()
    address = trig["inbound_address"]
    assert address.startswith("wf-") and address.endswith("@in.messer.local")
    denied = await client.post("/api/inbound/email", json={"To": address, "From": "a@b.c", "TextBody": "x"})
    assert denied.status_code == 401
    ok = await client.post(
        "/api/inbound/email?token=in-secret",
        json={
            "To": f"Pedidos <{address}>",
            "From": "cliente@example.com",
            "Subject": "Pedido",
            "TextBody": "Quiero 3",
            "MessageID": "m-1",
        },
    )
    assert ok.status_code == 202 and ok.json()["fired"] == 1
    payload = queued[0][1][1]
    assert payload["from"] == "cliente@example.com" and payload["text"] == "Quiero 3"
    sim = await client.post(
        f"/api/v1/triggers/{trig['id']}/simulate-email",
        json={"from": "x@example.com", "subject": "Prueba", "text": "Hola"},
    )
    assert sim.status_code == 202 and sim.json()["fired"] == 1


async def test_firing_runs_the_member(client: httpx.AsyncClient, runtime: Harness) -> None:
    from messer_worker.jobs.triggers import fire_trigger

    pid = await _project(client)
    trig = (
        await client.post(
            f"/api/v1/projects/{pid}/triggers",
            json={"workforce": "avisos", "kind": "manual", "environment": "development"},
        )
    ).json()
    result = await fire_trigger({}, trig["id"], {"type": "manual", "note": "prueba"}, "evt-42")
    assert result["status"] == "success", result
    async with system_session() as s:
        run = await s.get(Run, uuid.UUID(result["run_id"]))
        assert run is not None and run.channel == "trigger" and str(run.trigger_id) == trig["id"]
        row = await s.get(Trigger, uuid.UUID(trig["id"]))
        assert row is not None and row.state["last"]["run_id"] == result["run_id"]
    prod = (
        await client.post(f"/api/v1/projects/{pid}/triggers", json={"workforce": "avisos", "kind": "manual"})
    ).json()
    skipped = await fire_trigger({}, prod["id"], {"type": "manual"}, "evt-43")
    assert skipped["status"] == "not_deployed"


async def test_expired_approvals_apply_default_and_resume(make_org, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.projects import create_project
    from messer_common.testing.fixtures import principal_for
    from messer_scheduler.tasks import triggers as sched

    enqueued: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        enqueued.append((job, args))

    monkeypatch.setattr(sched, "enqueue", fake_enqueue)
    org, owner = await make_org()
    async with system_session() as s:
        project = await create_project(s, principal_for(owner.id, org.id, "owner"), name="Pagos")
        run = Run(
            id=uuid.uuid4(),
            org_id=org.id,
            project_id=project.id,
            status="paused",
            workforce_name="pagos",
            input={"prompt": "Paga la factura"},
            git_commit="a" * 40,
        )
        s.add(run)
        await s.flush()
        s.add(
            Approval(
                org_id=org.id,
                project_id=project.id,
                run_id=run.id,
                engine_approval_id="ap-x",
                workforce_name="pagos",
                tool_name="pay",
                title="Pagar",
                payload={"amount": 10},
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
                expiry_action="deny",
            )
        )
    await sched.expire_approvals()
    async with system_session() as s:
        approval = (await s.execute(select(Approval).where(Approval.run_id == run.id))).scalar_one()
    assert approval.status == "denied" and approval.decision_via == "expiry"
    assert enqueued and enqueued[0][0] == "resume_run"
    request = enqueued[0][1][0]
    assert request["resume"]["ap-x"]["approved"] is False and request["ref"] == "a" * 40
