"""Phase 3 journey through the public API: chat with an agent built in Studio, approve a gated tool, inspect
the trace with cost and credits."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import CreditLedger, Membership, User
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import get_settings
from messer_runtime.testing import Harness, anthropic_reply


async def _sse(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def _setup(client: httpx.AsyncClient, tools: list[dict[str, Any]]) -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": "ana@acme.example", "password": "Contrasena123",
                                                         "name": "Ana"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Facturas"})).json()["id"]
    agent = (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})).json()
    cfg = agent["config"]
    cfg["system_prompt"] = "Eres el asistente de facturas. Responde en español."
    cfg["tools"] = tools
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    return str(pid)


async def test_chat_approval_resume_and_trace(client: httpx.AsyncClient, runtime: Harness) -> None:
    pid = await _setup(client, [{"type": "builtin", "key": "send_email", "requires_approval": True,
                                 "approver_role": "admin"}])
    ConsoleEmailAdapter.sent.clear()
    events = await _sse(client, f"/api/v1/projects/{pid}/workforce/soporte/chat", {
        "message": 'Envía un email a cliente@example.com con asunto "Factura 77" y el texto "Ya está pagada"'})
    assert events[0]["type"] == "CONVERSATION"
    conversation_id = events[0]["conversation_id"]
    assert any(e["type"] == "DELTA" for e in events)
    finished = events[-1]
    assert finished["type"] == "RUN_FINISHED" and finished["status"] == "paused", finished

    inbox = (await client.get("/api/v1/approvals")).json()
    assert inbox["pending"] == 1
    approval = inbox["items"][0]
    assert approval["can_decide"] and approval["tool_name"] == "send_email"
    assert approval["payload"]["to"] == "cliente@example.com"

    # The approver fixes the recipient before approving (approve with changes).
    resumed = await _sse(client, f"/api/v1/approvals/{approval['id']}/decision?stream=true", {
        "decision": "approve_with_changes", "payload": {"to": "facturacion@example.com"}, "comment": "Mejor a este"})
    assert resumed[0]["type"] == "APPROVAL_RECORDED"
    assert resumed[-1]["type"] == "RUN_FINISHED" and resumed[-1]["status"] == "success", resumed[-1]
    assert [m.to for m in ConsoleEmailAdapter.sent] == ["facturacion@example.com"]
    again = await client.post(f"/api/v1/approvals/{approval['id']}/decision", json={"decision": "deny"})
    assert again.status_code == 409

    conv = (await client.get(f"/api/v1/projects/{pid}/conversations/{conversation_id}")).json()
    assert conv["messages"][0]["role"] == "user" and conv["messages"][-1]["role"] == "assistant"

    # A follow-up in the same conversation continues from the previous run (memory).
    follow = await _sse(client, f"/api/v1/projects/{pid}/workforce/soporte/chat",
                        {"message": "Gracias", "conversation_id": conversation_id})
    assert follow[-1]["status"] == "success"

    runs = (await client.get("/api/v1/runs", params={"project_id": pid})).json()["items"]
    assert len(runs) == 3
    detail = (await client.get(f"/api/v1/runs/{resumed[-1]['run_id'].replace('-', '')}")).json()
    kinds = {s["kind"] for s in detail["spans"]}
    assert {"agent", "llm", "tool"} <= kinds
    assert detail["git_commit"]
    fb = await client.post(f"/api/v1/runs/{detail['id']}/feedback", json={"value": "up"})
    assert fb.status_code == 201
    audit_res = await client.get("/api/v1/audit-log", params={"action": "approval.approved"})
    assert audit_res.status_code == 200, audit_res.text
    audit = audit_res.json()
    assert any(item["action"] == "approval.approved" for item in audit)


async def test_cost_and_credits_are_charged(client: httpx.AsyncClient, runtime: Harness,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    gateway.anthropic_transport = httpx.MockTransport(
        anthropic_reply("Su próxima factura vence el día 30.", {"input_tokens": 120_000, "output_tokens": 8_000})
    )
    pid = await _setup(client, [])
    credits_before = (await client.get("/api/v1/billing/credits")).json()
    events = await _sse(client, f"/api/v1/projects/{pid}/workforce/soporte/chat", {"message": "¿Cuándo vence?"})
    finished = events[-1]
    assert finished["status"] == "success" and Decimal(finished["cost_usd"]) > 0, finished
    detail = (await client.get(f"/api/v1/runs/{finished['run_id']}")).json()
    assert Decimal(detail["cost_usd"]) == Decimal(finished["cost_usd"])
    llm = [s for s in detail["spans"] if s["kind"] == "llm"]
    assert llm and llm[0]["input_tokens"] == 120_000 and Decimal(llm[0]["cost_usd"]) > 0
    async with system_session() as s:
        entry = (await s.execute(select(CreditLedger).where(CreditLedger.kind == "usage"))).scalar_one()
    assert entry.amount == -Decimal(finished["credits"])
    credits_after = (await client.get("/api/v1/billing/credits")).json()
    assert Decimal(str(credits_after["balance"])) == Decimal(str(credits_before["balance"])) - Decimal(finished["credits"])


async def test_viewer_cannot_chat_or_decide(client: httpx.AsyncClient, runtime: Harness, make_user) -> None:  # type: ignore[no-untyped-def]
    pid = await _setup(client, [{"type": "builtin", "key": "send_email", "requires_approval": True}])
    events = await _sse(client, f"/api/v1/projects/{pid}/workforce/soporte/chat",
                        {"message": 'Envía un email a x@example.com con asunto "A" y el texto "B"'})
    assert events[-1]["status"] == "paused"
    approval_id = (await client.get("/api/v1/approvals")).json()["items"][0]["id"]
    viewer = await make_user(email="viewer@acme.example")
    async with system_session() as s:
        owner = (await s.execute(select(User).where(User.email == "ana@acme.example"))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == owner.id))).scalar_one()
        s.add(Membership(org_id=org_id, user_id=viewer.id, role="viewer"))
    await client.post("/api/v1/auth/logout")
    login = await client.post("/api/v1/auth/login", json={"email": "viewer@acme.example", "password": "Sup3rSecret!pass"})
    assert login.status_code == 200, login.text
    client.headers["X-Messer-Org"] = str(org_id)
    chat = await client.post(f"/api/v1/projects/{pid}/workforce/soporte/chat", json={"message": "Hola"})
    assert chat.status_code == 403
    item = (await client.get("/api/v1/approvals")).json()["items"][0]
    assert item["can_decide"] is False
    denied = await client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"})
    assert denied.status_code == 403


async def test_public_api_requires_deployment_and_runs_development(client: httpx.AsyncClient,
                                                                   runtime: Harness) -> None:
    pid = await _setup(client, [])
    prod = await client.post(f"/v1/projects/{pid}/workforce/soporte/run", json={"input": {"prompt": "Hola"}})
    assert prod.status_code == 409 and prod.json()["error"]["code"] == "not_deployed"
    dev = await client.post(f"/v1/projects/{pid}/workforce/soporte/run",
                            json={"input": {"prompt": "Hola"}, "environment": "development", "session_id": "s-1"})
    assert dev.status_code == 200, dev.text
    out = dev.json()
    assert out["status"] == "success" and out["output"]
    again = await client.post(f"/v1/projects/{pid}/workforce/soporte/run",
                              json={"input": {"prompt": "¿Y ahora?"}, "environment": "development", "session_id": "s-1"})
    assert again.status_code == 200
    first = (await client.get(f"/v1/runs/{out['run_id']}")).json()
    assert first["status"] == "success"
    second = (await client.get(f"/api/v1/runs/{uuid.UUID(again.json()['run_id'])}")).json()
    assert second["parent_run_id"] == str(uuid.UUID(out["run_id"]))
