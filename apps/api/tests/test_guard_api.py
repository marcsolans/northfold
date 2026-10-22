"""Guard API (``/api/v1/projects/{id}/guard``): playbook lifecycle, validation, plan gate, roles, audit, and the
metrics and decisions computed from real guarded runs."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from sqlalchemy import select, update

from messer_common.db import system_session
from messer_common.db.models import AuditLog, Membership, Subscription, User
from messer_common.guard.generate import SMALL_TALK_PATTERN
from messer_common.projects_repo import ProjectRepo
from messer_runtime.testing import Harness

PROMPT = "Eres el asistente de facturas de Acme. Pide aprobación humana antes de emitir abonos de más de 500 €."
CREDIT_NOTE_TOOL = {
    "type": "custom",
    "key": "create_credit_note",
    "description": "Emite un abono",
    "input_schema": {
        "type": "object",
        "properties": {"amount": {"type": "number"}, "invoice_id": {"type": "string"}},
        "required": ["amount"],
    },
}
TOOLS_PY = '''from messer import Tool


def _create_credit_note(amount: float, invoice_id: str) -> dict:
    return {"credit_note": "AB-1", "amount": amount, "invoice_id": invoice_id}


create_credit_note = Tool(name="create_credit_note", description="Emite un abono (credit note)", handler=_create_credit_note)
'''


async def _setup(client: httpx.AsyncClient, email: str = "ana@acme.example") -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "Ana"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Facturas"})).json()["id"]
    agent = (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})).json()
    cfg = agent["config"]
    cfg["system_prompt"] = PROMPT
    cfg["guardrails"] = []
    cfg["tools"] = [CREDIT_NOTE_TOOL, {"type": "builtin", "key": "send_email", "requires_approval": True}]
    res = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)
    assert res.status_code == 200, res.text
    return str(pid)


async def _upgrade(email: str = "ana@acme.example", plan: str = "business") -> None:
    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalar_one()
        await s.execute(update(Subscription).where(Subscription.org_id == org_id).values(plan_id=plan))


def playbook(**extra: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "small_model": "anthropic/claude-haiku-5-5",
        "large_model": "anthropic/claude-sonnet-5-5",
        "policies": [
            {
                "id": "small_talk",
                "match": {"last_message": "user_text", "max_chars": 60, "text_patterns": [SMALL_TALK_PATTERN]},
                "model": "small",
            },
            {
                "id": "credit_note_limit",
                "tool_action": {
                    "tool": "create_credit_note",
                    "action": "deny",
                    "constraints": [{"arg": "amount", "op": ">", "value": 500}],
                },
            },
        ],
        **extra,
    }


async def test_playbook_lifecycle_validation_plan_gate_and_audit(client: httpx.AsyncClient) -> None:
    pid = await _setup(client)
    base = f"/api/v1/projects/{pid}/guard"

    overview = (await client.get(base)).json()
    assert overview["agents"] == [
        {"member": "soporte", "enabled": False, "has_playbook": False, "generated_by": None, "policies": 0,
         "updated_at": None}
    ]
    assert overview["plan_allows"] is False  # trial (Pro) does not include Guard

    detail = (await client.get(f"{base}/soporte")).json()
    assert detail["playbook"] is None and detail["enabled"] is False
    assert {t["name"]: t["gated"] for t in detail["tools"]} == {"create_credit_note": False, "send_email": True}
    assert detail["defaults"]["small_model"] == "anthropic/claude-haiku-5-5"
    assert any(m["id"] == "anthropic/claude-opus-5-5" for m in detail["models"])
    assert "approval:create_credit_note" in detail["facts"]

    no_playbook = await client.post(f"{base}/soporte/enable")
    assert no_playbook.status_code == 402 and no_playbook.json()["error"]["details"]["feature"] == "guard"
    await _upgrade()
    no_playbook = await client.post(f"{base}/soporte/enable")
    assert no_playbook.status_code == 409 and no_playbook.json()["error"]["code"] == "no_playbook"

    # Generation without provider keys: deterministic proposal from the configuration.
    generated = await client.post(f"{base}/soporte/regenerate")
    assert generated.status_code == 200, generated.text
    g = generated.json()
    assert g["generated_by"] == "rules" and g["meta"]["demo"] is True and g["meta"]["warnings"]
    ids = [p["id"] for p in g["playbook"]["policies"]]
    assert ids == ["small_talk", "create_credit_note_limit", "send_email_approval"]
    limit = g["playbook"]["policies"][1]["tool_action"]
    assert limit["action"] == "deny" and limit["constraints"] == [{"arg": "amount", "op": ">", "value": 500.0}]

    bad = playbook()
    bad["policies"][1]["tool_action"]["constraints"][0]["value"] = "quinientos"
    bad["policies"].append({"id": "small_talk", "model": "large"})
    invalid = await client.put(f"{base}/soporte", json={"playbook": bad})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "invalid_playbook"
    issues = invalid.json()["error"]["details"]["issues"]
    assert {i["path"] for i in issues} >= {"policies.1.tool_action.constraints.0"}
    checked = (await client.post(f"{base}/soporte/validate", json={"playbook": bad})).json()
    assert checked["ok"] is False and checked["issues"]

    warn = playbook()
    warn["policies"].append({"id": "ghost", "tool_action": {"tool": "refund", "action": "deny"}})
    saved = await client.put(f"{base}/soporte", json={"playbook": warn})
    assert saved.status_code == 200, saved.text
    s = saved.json()
    assert s["generated_by"] == "manual" and s["enabled"] is False
    assert [i["code"] for i in s["issues"]] == ["unknown_tool"]

    enabled = (await client.post(f"{base}/soporte/enable")).json()
    assert enabled["enabled"] is True and enabled["playbook"]["enabled"] is True
    member = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()
    assert member["guard_enabled"] is True
    # Editing keeps the toggle as it is.
    again = (await client.put(f"{base}/soporte", json={"playbook": playbook()})).json()
    assert again["enabled"] is True and again["playbook"]["enabled"] is True and again["issues"] == []

    disabled = (await client.post(f"{base}/soporte/disable")).json()
    assert disabled["enabled"] is False
    async with system_session() as session:
        actions = (await session.execute(select(AuditLog.action).where(AuditLog.action.like("guard.%")))).scalars().all()
    assert sorted(actions) == sorted(
        ["guard.playbook_generated", "guard.playbook_updated", "guard.enabled", "guard.playbook_updated",
         "guard.disabled"]
    )

    workflow = await client.get(f"{base}/no_existe")
    assert workflow.status_code == 404


async def test_viewers_read_but_cannot_change_guard(client: httpx.AsyncClient) -> None:
    pid = await _setup(client)
    await client.put(f"/api/v1/projects/{pid}/guard/soporte", json={"playbook": playbook()})
    viewer_email = f"viewer-{uuid.uuid4().hex[:6]}@acme.example"
    async with system_session() as s:
        owner = (await s.execute(select(User).where(User.email == "ana@acme.example"))).scalar_one()
        oid = (await s.execute(select(Membership.org_id).where(Membership.user_id == owner.id))).scalar_one()
    await client.post("/api/v1/auth/logout")
    res = await client.post("/api/v1/auth/signup", json={"email": viewer_email, "password": "Contrasena123", "name": "V"})
    assert res.status_code == 200, res.text
    async with system_session() as s:
        viewer = (await s.execute(select(User).where(User.email == viewer_email))).scalar_one()
        s.add(Membership(org_id=oid, user_id=viewer.id, role="viewer"))
    headers = {"X-Messer-Org": str(oid)}
    read = await client.get(f"/api/v1/projects/{pid}/guard/soporte", headers=headers)
    assert read.status_code == 200 and read.json()["playbook"] is not None
    write = await client.put(f"/api/v1/projects/{pid}/guard/soporte", json={"playbook": playbook()}, headers=headers)
    assert write.status_code == 403
    assert (await client.post(f"/api/v1/projects/{pid}/guard/soporte/enable", headers=headers)).status_code == 403


async def _chat(client: httpx.AsyncClient, pid: str, message: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    async with client.stream(
        "POST", f"/api/v1/projects/{pid}/workforce/soporte/chat", json={"message": message}
    ) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events[-1]


async def test_metrics_and_decisions_from_guarded_runs(client: httpx.AsyncClient, runtime: Harness) -> None:
    pid = await _setup(client)
    await ProjectRepo.for_project(pid).write(
        {"workforce/soporte/tools.py": TOOLS_PY}, message="Add tools", author="Test", email="t@example.com"
    )
    await _upgrade()
    base = f"/api/v1/projects/{pid}/guard/soporte"
    assert (await client.put(base, json={"playbook": playbook()})).status_code == 200
    assert (await client.post(f"{base}/enable")).json()["enabled"] is True

    empty = (await client.get(f"{base}/metrics")).json()
    assert empty["turns"] == 0 and empty["on_path_share"] is None and empty["cost"]["savings_pct"] is None

    hello = await _chat(client, pid, "hola")
    assert hello["type"] == "RUN_FINISHED" and hello["status"] == "success", hello
    blocked = await _chat(client, pid, "Create a credit note of 900 EUR for invoice F-1043")
    assert blocked["status"] == "success", blocked
    other = await _chat(client, pid, "¿Qué facturas tengo pendientes?")
    assert other["status"] == "success", other

    m = (await client.get(f"{base}/metrics", params={"days": 7})).json()
    assert m["runs"] == 3 and m["turns"] == 3 and m["days"] == 7
    assert m["on_path_turns"] == 2 and abs(m["on_path_share"] - 2 / 3) < 1e-9
    assert m["blocked_actions"] == 1 and m["routes"] == {"small": 1, "default": 2}
    assert m["demo"] is True and m["daily"][0]["turns"] == 3 and m["daily"][0]["blocked"] == 1
    # Demo calls are priced at list prices: the greeting on Haiku is cheaper than the same tokens on Sonnet.
    assert float(m["cost"]["baseline_usd"]) > float(m["cost"]["guarded_usd"]) > 0
    assert m["cost"]["savings_pct"] is not None and m["cost"]["savings_pct"] > 0
    assert {p["policy"] for p in m["policies"]} == {"small_talk", "credit_note_limit", "fallthrough"}

    decisions = (await client.get(f"{base}/decisions", params={"limit": 10})).json()
    assert [d["policy"] for d in decisions] == ["fallthrough", "credit_note_limit", "small_talk"]
    block = decisions[1]
    assert block["status"] == "blocked" and block["blocked"][0]["tool"] == "create_credit_note"
    assert block["tool_calls"][0]["input"]["amount"] == 900 and uuid.UUID(block["run_id"]) == uuid.UUID(blocked["run_id"])
    assert decisions[2]["model"] == "anthropic/claude-haiku-5-5" and decisions[2]["route"] == "small"
    assert decisions[0]["on_path"] is False and decisions[0]["text"] == "¿Qué facturas tengo pendientes?"
