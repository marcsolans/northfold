"""Phase 8 channels: connect, simulate, process with memory, approvals over a channel, inbox, lifecycle."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from messer_common.channels import processing
from messer_common.db import system_session
from messer_common.db.models import AuditLog, Conversation, Run
from messer_common.db.models.channels import ChannelMessage
from messer_common.email import ConsoleEmailAdapter
from messer_runtime.testing import Harness


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Inbound jobs queued by webhooks and the simulator (run them with ``drain``)."""
    jobs: list[str] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        assert job == "channel_inbound"
        jobs.append(str(args[0]))

    monkeypatch.setattr(processing, "enqueue", fake_enqueue)
    return jobs


async def drain(jobs: list[str]) -> list[dict[str, Any]]:
    from messer_worker.jobs.channels import channel_inbound

    results = []
    while jobs:
        results.append(await channel_inbound({"job_try": 1}, jobs.pop(0)))
    return results


async def setup_project(client: httpx.AsyncClient, tools: list[dict[str, Any]] | None = None) -> str:
    res = await client.post(
        "/api/v1/auth/signup", json={"email": "marta@acme.example", "password": "Contrasena123", "name": "Marta"}
    )
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Facturas"})).json()["id"]
    agent = (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})).json()
    cfg = agent["config"]
    cfg["system_prompt"] = "Eres el asistente de facturas. Responde en español."
    cfg["tools"] = tools or []
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    return str(pid)


async def test_whatsapp_demo_conversation_with_memory(
    client: httpx.AsyncClient, runtime: Harness, queued: list[str]
) -> None:
    pid = await setup_project(client)
    res = await client.post(f"/api/v1/projects/{pid}/channels", json={"provider": "whatsapp", "workforce": "soporte"})
    assert res.status_code == 201, res.text
    channel = res.json()
    assert channel["demo"] is True and channel["status"] == "demo"
    assert channel["development_fallback"] is True  # production is not deployed: demo runs development
    assert {"access_token", "app_secret", "phone_number_id"} <= set(channel["missing_credentials"])
    assert channel["webhook_url"].endswith(f"/api/channels/{channel['id']}/whatsapp")
    assert channel["webhook_secret"]

    first = await client.post(
        f"/api/v1/channels/{channel['id']}/simulate",
        json={"from": "+34600111222", "name": "Ana", "text": "Hola, ¿cuándo vence mi factura 12?"},
    )
    assert first.status_code == 202, first.text
    conversation_id = first.json()["conversation_id"]
    [result] = await drain(queued)
    assert result["status"] == "processed" and result["run_status"] == "success", result
    assert result["delivery"]["status"] == "stored"

    second = await client.post(
        f"/api/v1/channels/{channel['id']}/simulate",
        json={"from": "+34600111222", "name": "Ana", "text": "¿Y cuánto es el importe?"},
    )
    assert second.json()["conversation_id"] == conversation_id  # same thread for the same user
    [result2] = await drain(queued)
    assert result2["run_status"] == "success"

    # Memory: the second run continues from the first one (parent_run_id chain) on the same conversation.
    async with system_session() as s:
        runs = (
            (
                await s.execute(
                    select(Run).where(Run.conversation_id == uuid.UUID(conversation_id)).order_by(Run.started_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 2
        assert runs[0].parent_run_id is None and runs[1].parent_run_id == runs[0].id
        assert {r.channel for r in runs} == {"whatsapp"}
        assert {r.environment for r in runs} == {"development"}
        assert runs[0].external_user_id == "sim:+34600111222"
        conv = await s.get(Conversation, uuid.UUID(conversation_id))
        assert conv is not None and conv.last_run_id == runs[1].id

    detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    roles = [m["role"] for m in detail["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"], detail["messages"]
    assert detail["messages"][1]["run_id"] == str(runs[0].id)
    assert detail["messages"][1]["delivery"]["status"] == "stored"
    assert detail["contact_name"] == "Ana" and detail["simulated"] is True
    assert detail["channel"]["provider"] == "whatsapp"

    inbox = (await client.get(f"/api/v1/projects/{pid}/conversations")).json()
    assert [c["id"] for c in inbox["items"]] == [conversation_id]
    item = inbox["items"][0]
    assert item["provider"] == "whatsapp" and item["message_count"] == 4 and item["contact_name"] == "Ana"
    assert inbox["providers"] == [{"provider": "whatsapp", "count": 1}]
    assert (await client.get(f"/api/v1/projects/{pid}/conversations", params={"q": "importe"})).json()["items"]
    assert not (await client.get(f"/api/v1/projects/{pid}/conversations", params={"provider": "slack"})).json()["items"]

    log = (await client.get(f"/api/v1/channels/{channel['id']}/messages")).json()["items"]
    assert sorted((m["direction"], m["status"]) for m in log) == [
        ("inbound", "processed"),
        ("inbound", "processed"),
        ("outbound", "stored"),
        ("outbound", "stored"),
    ]
    listed = (await client.get(f"/api/v1/projects/{pid}/channels")).json()
    assert listed[0]["stats"]["conversations"] == 1 and listed[0]["stats"]["messages_24h"] == 4

    closed = await client.post(f"/api/v1/conversations/{conversation_id}/close")
    assert closed.status_code == 200 and closed.json()["status"] == "closed"
    assert (await client.get(f"/api/v1/projects/{pid}/conversations", params={"status": "closed"})).json()["items"]
    # A new message from the user reopens the conversation and keeps its memory.
    await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"from": "+34600111222", "text": "Gracias"})
    await drain(queued)
    reopened = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    assert reopened["status"] == "open" and len(reopened["messages"]) == 6
    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action))).scalars().all())
    assert {"channel.connected", "conversation.closed"} <= actions

    # Re-running a processed message never runs the agent again (idempotent per provider message).
    async with system_session() as s:
        first_msg = (
            await s.execute(select(ChannelMessage).where(ChannelMessage.direction == "inbound").limit(1))
        ).scalar_one()
    again = await processing.process_inbound(first_msg.id)
    assert again == {"status": "skipped", "reason": "processed"}


async def test_approval_over_channel_delivers_final_answer(
    client: httpx.AsyncClient, runtime: Harness, queued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from messer_api.routers import approvals as approvals_router
    from messer_worker.jobs.approvals import resume_run

    pid = await setup_project(
        client, [{"type": "builtin", "key": "send_email", "requires_approval": True, "approver_role": "admin"}]
    )
    channel = (
        await client.post(
            f"/api/v1/projects/{pid}/channels",
            json={"provider": "telegram", "workforce": "soporte", "config": {"locale": "es"}},
        )
    ).json()
    assert channel["demo"] is True
    sim = await client.post(
        f"/api/v1/channels/{channel['id']}/simulate",
        json={
            "from": "tg-77",
            "text": 'Envía un email a cliente@example.com con asunto "Factura 77" y el texto "Ya está pagada"',
        },
    )
    conversation_id = sim.json()["conversation_id"]
    [result] = await drain(queued)
    assert result["run_status"] == "paused", result
    assert result["delivery"]["kind"] == "approval_pending"
    detail = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    assert detail["messages"][-1]["notice"] == "approval_pending"
    assert "aprobación" in detail["messages"][-1]["text"]
    assert len(detail["pending_approvals"]) == 1
    inbox = (await client.get(f"/api/v1/projects/{pid}/conversations")).json()["items"]
    assert inbox[0]["pending_approvals"] == 1

    resumes: list[dict[str, Any]] = []

    async def capture(job: str, *args: Any, **kwargs: Any) -> None:
        assert job == "resume_run"
        resumes.append(args[0])

    monkeypatch.setattr(approvals_router, "enqueue", capture)
    approval_id = detail["pending_approvals"][0]["id"]
    decided = await client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"})
    assert decided.status_code == 200, decided.text
    ConsoleEmailAdapter.sent.clear()
    out = await resume_run({}, resumes[0])
    assert out["status"] == "success", out
    assert [m.to for m in ConsoleEmailAdapter.sent] == ["cliente@example.com"]

    final = (await client.get(f"/api/v1/conversations/{conversation_id}")).json()
    last = final["messages"][-1]
    assert last["role"] == "assistant" and last["notice"] is None
    assert last["delivery"]["status"] == "stored" and last["delivery"]["kind"] == "answer"
    assert final["pending_approvals"] == []
    async with system_session() as s:
        outbound = (
            (
                await s.execute(
                    select(ChannelMessage)
                    .where(ChannelMessage.direction == "outbound")
                    .order_by(ChannelMessage.created_at)
                )
            )
            .scalars()
            .all()
        )
    assert [m.kind for m in outbound] == ["approval_pending", "answer"]
    # Delivering the same resumed run twice is a no-op.
    again = await processing.deliver_resumed_run(resumes[0], out | {"run_id": resumes[0]["run_id"]})
    assert again is not None and again["status"] == "skipped"


async def test_connect_validation_roles_and_lifecycle(client: httpx.AsyncClient, make_user, queued: list[str]) -> None:  # type: ignore[no-untyped-def]
    pid = await setup_project(client)
    providers = (await client.get("/api/v1/channels/providers")).json()
    assert [p["provider"] for p in providers] == ["whatsapp", "slack", "teams", "telegram", "email"]
    whatsapp = providers[0]
    assert {f["key"] for f in whatsapp["credential_fields"]} == {"access_token", "app_secret"}
    assert whatsapp["platform_ready"] is False

    live_without_keys = await client.post(
        f"/api/v1/projects/{pid}/channels", json={"provider": "slack", "workforce": "soporte", "demo": False}
    )
    assert live_without_keys.status_code == 422
    assert live_without_keys.json()["error"]["code"] == "missing_credentials"
    unknown = await client.post(
        f"/api/v1/projects/{pid}/channels",
        json={"provider": "slack", "workforce": "soporte", "credentials": {"password": "x"}},
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["code"] == "unknown_credentials"
    bad_config = await client.post(
        f"/api/v1/projects/{pid}/channels",
        json={"provider": "whatsapp", "workforce": "soporte", "config": {"phone_number_id": "abc"}},
    )
    assert bad_config.status_code == 422
    missing_member = await client.post(
        f"/api/v1/projects/{pid}/channels", json={"provider": "email", "workforce": "nadie"}
    )
    assert missing_member.status_code == 404

    email = await client.post(
        f"/api/v1/projects/{pid}/channels", json={"provider": "email", "workforce": "soporte", "demo": True}
    )
    assert email.status_code == 201, email.text
    channel = email.json()
    assert channel["inbound_address"].startswith("ch-") and channel["inbound_address"].endswith("@in.messer.local")

    paused = await client.patch(f"/api/v1/channels/{channel['id']}", json={"enabled": False, "name": "Soporte email"})
    assert paused.status_code == 200 and paused.json()["status"] == "disabled"
    sim = await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"text": "Hola"})
    assert sim.status_code == 409
    resumed = await client.patch(f"/api/v1/channels/{channel['id']}", json={"enabled": True})
    assert resumed.json()["status"] == "demo"
    tested = await client.post(f"/api/v1/channels/{channel['id']}/test")
    assert tested.status_code == 200 and tested.json()["ok"] is True and tested.json()["demo"] is True
    rotated = await client.post(f"/api/v1/channels/{channel['id']}/rotate-secret")
    assert rotated.status_code == 200 and rotated.json()["webhook_secret"] != channel["webhook_secret"]

    sim = await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"text": "Hola"})
    assert sim.status_code == 202
    conversation_id = sim.json()["conversation_id"]

    # Viewers read channels and the inbox but cannot change anything.
    viewer = await make_user(email="lector@acme.example")
    from messer_common.db.models import Membership, Project

    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(pid))
        assert project is not None
        s.add(Membership(org_id=project.org_id, user_id=viewer.id, role="viewer"))
        org_id = project.org_id
    await client.post("/api/v1/auth/logout")
    login = await client.post(
        "/api/v1/auth/login", json={"email": "lector@acme.example", "password": "Sup3rSecret!pass"}
    )
    assert login.status_code == 200
    client.headers["X-Messer-Org"] = str(org_id)
    assert (await client.get(f"/api/v1/projects/{pid}/channels")).status_code == 200
    assert (await client.get(f"/api/v1/conversations/{conversation_id}")).status_code == 200
    assert (
        await client.post(f"/api/v1/projects/{pid}/channels", json={"provider": "email", "workforce": "soporte"})
    ).status_code == 403
    assert (await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"text": "x"})).status_code == 403
    assert (await client.post(f"/api/v1/conversations/{conversation_id}/close")).status_code == 403
    assert (await client.delete(f"/api/v1/channels/{channel['id']}")).status_code == 403

    # Back as the builder: disconnecting keeps the conversation in the inbox.
    await client.post("/api/v1/auth/logout")
    await client.post("/api/v1/auth/login", json={"email": "marta@acme.example", "password": "Contrasena123"})
    assert (await client.delete(f"/api/v1/channels/{channel['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/channels/{channel['id']}")).status_code == 404
    kept = await client.get(f"/api/v1/conversations/{conversation_id}")
    assert kept.status_code == 200 and kept.json()["channel"] is None


async def test_other_org_cannot_see_channels_or_conversations(
    client: httpx.AsyncClient, make_org, queued: list[str]
) -> None:  # type: ignore[no-untyped-def]
    pid = await setup_project(client)
    channel = (
        await client.post(f"/api/v1/projects/{pid}/channels", json={"provider": "slack", "workforce": "soporte"})
    ).json()
    sim = (await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"text": "Hola"})).json()
    await client.post("/api/v1/auth/logout")
    _, other = await make_org(name="Otra")
    login = await client.post("/api/v1/auth/login", json={"email": other.email, "password": "Sup3rSecret!pass"})
    assert login.status_code == 200
    assert (await client.get(f"/api/v1/channels/{channel['id']}")).status_code == 404
    assert (await client.get(f"/api/v1/conversations/{sim['conversation_id']}")).status_code == 404
    assert (await client.post(f"/api/v1/channels/{channel['id']}/simulate", json={"text": "x"})).status_code == 404
