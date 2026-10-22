"""Interfaces that run things (live runtime, demo model): the public chat with per-end-user memory and an
approval-pending notice, forms and buttons that start workflows and agents, uploads into a knowledge base,
the approvals inbox component and rate limits."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from interfaces_support import (
    add_agent,
    add_workflow,
    anon_client,
    deploy,
    drop_kb_roles,
    invoices_kb,
    signup_owner,
    sse,
)
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Approval, Conversation, KbFile, Run
from messer_runtime.testing import Harness

pytestmark = pytest.mark.usefixtures("drop_kb_roles")
__all__ = ["anon_client", "drop_kb_roles"]

EMAIL_TOOL = [{"type": "builtin", "key": "send_email", "requires_approval": True, "approver_role": "admin"}]


async def _chat_project(client: httpx.AsyncClient, tools: list[dict[str, Any]] | None = None) -> Any:
    owner = await signup_owner(client)
    await add_agent(owner, "soporte", tools)
    res = await client.post(
        f"/api/v1/projects/{owner.project_id}/interfaces",
        json={"template": "public_chat", "name": "Asistente", "agent": "soporte"},
    )
    assert res.status_code == 201, res.text
    return owner, res.json()


async def test_public_chat_memory_per_end_user(
    client: httpx.AsyncClient, runtime: Harness, anon_client: httpx.AsyncClient
) -> None:
    owner, chat = await _chat_project(client)
    base = f"/api/public/v1/chat/{owner.org_slug}/{owner.project_slug}/soporte"
    assert (await anon_client.get(base)).json()["error"]["code"] == "not_deployed"
    await deploy(owner, runtime=True)

    config = await anon_client.get(base)
    assert config.status_code == 200, config.text
    assert "messer_eu" in config.cookies
    assert "httponly" in config.headers["set-cookie"].lower()
    comp = config.json()["interface"]["screens"][0]["components"][0]
    assert comp["type"] == "chat" and comp["binding"] == {"kind": "agent"}
    assert config.json()["viewer"]["authenticated"] is False

    events = await sse(anon_client, f"{base}/messages", {"message": "Hola, ¿qué facturas tengo?"})
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED" and types[-1] == "DONE" and "TEXT" in types
    done = events[-1]
    assert done["status"] == "success" and done["demo"] is True
    # End users only see sanitized events: no engine payloads, tool inputs or costs.
    assert not any(e["type"] in ("DELTA", "OUTPUT", "START", "RUN_FINISHED") for e in events)
    assert all("cost_usd" not in e for e in events)

    second = await sse(anon_client, f"{base}/messages", {"message": "Gracias"})
    assert second[-1]["status"] == "success"
    history = (await anon_client.get(f"{base}/conversation")).json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user", "assistant"]
    assert history["pending_approvals"] == 0

    async with system_session() as s:
        conv = (
            await s.execute(select(Conversation).where(Conversation.channel_key == f"public-chat:{chat['id']}"))
        ).scalar_one()
        runs = (
            (await s.execute(select(Run).where(Run.conversation_id == conv.id).order_by(Run.started_at)))
            .scalars()
            .all()
        )
    assert conv.external_user_id.startswith("anon:")
    assert len(runs) == 2 and runs[1].parent_run_id == runs[0].id  # memory: the second run continues the first
    assert all(r.environment == "production" and r.channel == "public_chat" for r in runs)

    # Another browser is another end user with its own thread.
    from messer_api.main import create_app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver", timeout=120
    ) as other:
        assert (await other.get(f"{base}/conversation")).json()["messages"] == []
        # Embedded widgets without third-party cookies use the signed token header.
        token = (await other.get(base, params={"embed": "true"})).json()["end_user_token"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver", timeout=120
    ) as widget:
        res = await widget.get(f"{base}/conversation", headers={"X-Messer-End-User": token})
        assert res.status_code == 200 and "messer_eu" not in res.cookies
        forged = await widget.get(f"{base}/conversation", headers={"X-Messer-End-User": "forged.token.value"})
        assert forged.status_code == 200 and forged.json()["messages"] == []

    # New conversation: the old thread is closed (kept for the team's inbox) and memory starts over.
    assert (await anon_client.delete(f"{base}/conversation")).status_code == 204
    assert (await anon_client.get(f"{base}/conversation")).json()["messages"] == []
    async with system_session() as s:
        closed = await s.get(Conversation, conv.id)
        assert closed is not None and closed.status == "closed" and len(closed.messages) == 4

    assert (await anon_client.get(f"/api/public/v1/chat/{owner.org_slug}/{owner.project_slug}/otro")).status_code == 404


async def test_public_chat_approval_notice_and_login(
    client: httpx.AsyncClient, runtime: Harness, anon_client: httpx.AsyncClient
) -> None:
    owner, chat = await _chat_project(client, EMAIL_TOOL)
    await deploy(owner, runtime=True)
    base = f"/api/public/v1/chat/{owner.org_slug}/{owner.project_slug}/soporte"
    events = await sse(
        anon_client,
        f"{base}/messages",
        {"message": 'Envía un email a cliente@example.com con asunto "Factura 77" y el texto "Ya está pagada"'},
    )
    assert "APPROVAL_PENDING" in [e["type"] for e in events]
    assert events[-1]["status"] == "paused" and events[-1]["approvals_pending"] == 1
    assert all("cliente@example.com" not in str(e) for e in events)  # tool inputs never reach the end user
    history = (await anon_client.get(f"{base}/conversation")).json()
    assert history["pending_approvals"] == 1
    async with system_session() as s:
        approval = (await s.execute(select(Approval))).scalar_one()
    assert approval.status == "pending" and approval.environment == "production"

    # A chat that requires login: anonymous visitors get 401, members of the org can talk.
    definition = (await client.get(f"/api/v1/interfaces/{chat['id']}")).json()["definition"]
    definition["auth"] = {"required": True, "roles": []}
    assert (await client.put(f"/api/v1/interfaces/{chat['id']}", json={"definition": definition})).status_code == 200
    await deploy(owner, runtime=True)
    res = await anon_client.post(f"{base}/messages", json={"message": "Hola"})
    assert res.status_code == 401 and res.json()["error"]["code"] == "login_required"
    events = await sse(client, f"{base}/messages", {"message": "Hola"})
    assert events[-1]["status"] == "success"
    async with system_session() as s:
        conv = (
            await s.execute(select(Conversation).where(Conversation.external_user_id == f"user:{owner.user_id}"))
        ).scalar_one()
    assert conv.channel_key == f"public-chat:{chat['id']}"


async def test_public_chat_rate_limit(
    client: httpx.AsyncClient, runtime: Harness, anon_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from messer_api.routers import public_interfaces

    owner, _ = await _chat_project(client)
    await deploy(owner, runtime=True)
    monkeypatch.setitem(public_interfaces.LIMITS, "chat", (1, 60))
    base = f"/api/public/v1/chat/{owner.org_slug}/{owner.project_slug}/soporte"
    await anon_client.get(base)
    first = await sse(anon_client, f"{base}/messages", {"message": "Hola"})
    assert first[-1]["type"] == "DONE"
    res = await anon_client.post(f"{base}/messages", json={"message": "Otra vez"})
    assert res.status_code == 429 and res.json()["error"]["code"] == "rate_limited"


async def test_forms_buttons_rows_uploads_and_approvals(client: httpx.AsyncClient, runtime: Harness) -> None:
    owner = await signup_owner(client)
    await add_agent(owner, "soporte", EMAIL_TOOL)
    await add_workflow(owner, "registrar")
    kb_id = await invoices_kb(owner)
    definition = {
        "name": "Operaciones",
        "slug": "operaciones",
        "screens": [
            {
                "id": "main",
                "title": "Operaciones",
                "components": [
                    {
                        "id": "form",
                        "type": "form",
                        "grid": {"x": 0, "y": 0, "w": 6, "h": 6},
                        "props": {
                            "fields": [
                                {"name": "factura", "label": "Factura", "required": True},
                                {"name": "importe", "label": "Importe", "type": "number", "required": True},
                            ]
                        },
                        "binding": {
                            "kind": "workflow",
                            "workforce": "registrar",
                            "input_mapping": {
                                "factura": "$form.factura",
                                "importe": "$form.importe",
                                "solicitante": "$user.email",
                            },
                        },
                    },
                    {
                        "id": "boton",
                        "type": "action_button",
                        "grid": {"x": 6, "y": 0, "w": 3, "h": 2},
                        "props": {"label": "Resumen"},
                        "binding": {
                            "kind": "agent",
                            "workforce": "soporte",
                            "prompt": "Resume las facturas de {{user.email}}",
                        },
                    },
                    {
                        "id": "tabla",
                        "type": "data_table",
                        "grid": {"x": 0, "y": 6, "w": 12, "h": 6},
                        "props": {
                            "row_action": {
                                "label": "Registrar",
                                "binding": {
                                    "kind": "workflow",
                                    "workforce": "registrar",
                                    "input_mapping": {"factura": "$row.numero", "importe": "$row.importe"},
                                },
                            }
                        },
                        "binding": {
                            "kind": "knowledge_sql",
                            "kb_id": str(kb_id),
                            "sql": "SELECT numero, importe FROM facturas",
                        },
                    },
                    {
                        "id": "subida",
                        "type": "file_upload",
                        "grid": {"x": 9, "y": 0, "w": 3, "h": 3},
                        "props": {"kb_id": str(kb_id), "accept": [".txt", ".md"], "max_mb": 1},
                    },
                    {"id": "aprobaciones", "type": "approvals_inbox", "grid": {"x": 6, "y": 2, "w": 3, "h": 4}},
                ],
            }
        ],
    }
    res = await client.post(f"/api/v1/projects/{owner.project_id}/interfaces", json={"definition": definition})
    assert res.status_code == 201, res.text
    assert res.json()["warnings"] == []
    url = f"/api/v1/interfaces/{res.json()['id']}/components"

    bad = await client.post(f"{url}/form/action", json={"values": {"importe": "mucho"}})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "factura"
    ok = (await client.post(f"{url}/form/action", json={"values": {"factura": "F-9", "importe": "120"}})).json()
    assert ok["status"] == "success", ok
    assert ok["output"] == {"registrada": "F-9", "importe": 120, "por": "olga@acme.example"}

    row = (
        await client.post(f"{url}/tabla/action", json={"row_action": True, "row": {"numero": "F-002", "importe": 300}})
    ).json()
    assert row["status"] == "success" and row["output"]["registrada"] == "F-002"
    assert (await client.post(f"{url}/boton/action", json={"row_action": True})).status_code == 400

    button = (await client.post(f"{url}/boton/action", json={})).json()
    assert button["status"] == "success" and button["text"]

    upload = await client.post(
        f"{url}/subida/upload", files={"file": ("notas.txt", b"Condiciones de pago: 30 dias", "text/plain")}
    )
    assert upload.status_code == 201, upload.text
    assert upload.json()["file"]["filename"] == "notas.txt"
    async with system_session() as s:
        stored = (await s.execute(select(KbFile).where(KbFile.kb_id == kb_id))).scalars().all()
    assert [f.filename for f in stored] == ["notas.txt"]
    refused = await client.post(f"{url}/subida/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert refused.status_code == 415

    # A gated tool from the chat agent lands in the approvals inbox component; deciding resumes the run.
    events = await sse(
        client,
        f"/api/v1/projects/{owner.project_id}/workforce/soporte/chat",
        {"message": 'Envía un email a x@example.com con asunto "A" y el texto "B"'},
    )
    assert events[-1]["status"] == "paused"
    inbox = (await client.post(f"{url}/aprobaciones/data", json={})).json()
    assert inbox["source"] == "approvals" and len(inbox["rows"]) == 1 and inbox["rows"][0]["can_decide"]
    approval_id = inbox["rows"][0]["id"]
    decided = await client.post(f"{url}/aprobaciones/approvals/{approval_id}/decision", json={"decision": "deny"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "denied"
    assert (await client.post(f"{url}/aprobaciones/data", json={})).json()["rows"] == []
    other = uuid.uuid4()
    assert (
        await client.post(f"{url}/aprobaciones/approvals/{other}/decision", json={"decision": "deny"})
    ).status_code == 404
