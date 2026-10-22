"""Workflow builder API: graph ↔ code, layout, custom nodes, palette, manual runs, and the phase 5 journey
(a workflow fires on its own via webhook and cron, pauses for approval, the approver gets the email, approves from
the link and the run completes)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from messer_common import triggers
from messer_common.db import system_session
from messer_common.db.models import Approval, Run, Trigger
from messer_common.email import ConsoleEmailAdapter
from messer_runtime.testing import Harness


async def _sse(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def _project(client: httpx.AsyncClient, email: str = "ops@acme.example") -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "Ops"})
    assert res.status_code == 200, res.text
    return str((await client.post("/api/v1/projects", json={"name": "Operaciones"})).json()["id"])


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    """Capture background jobs instead of sending them to the worker (the test runs them itself)."""
    from messer_api.routers import approvals as approvals_router
    from messer_runtime import runs

    calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        calls.append((job, args))

    for module in (triggers, approvals_router, runs):
        monkeypatch.setattr(module, "enqueue", fake_enqueue)
    return calls


# ------------------------------------------------------------------------------------------ graph & code


async def test_create_edit_graph_code_and_layout(client: httpx.AsyncClient) -> None:
    pid = await _project(client)
    base = f"/api/v1/projects/{pid}/workflows"
    created = await client.post(
        base, json={"name": "pagos", "description": "Pagos con aprobación", "template": "approval"}
    )
    assert created.status_code == 201, created.text
    detail = created.json()
    assert detail["source_mode"] == "config" and detail["config"]["name"] == "pagos"
    assert "from messer import Workflow" in detail["code"] and "wf.approval(" in detail["code"]
    assert all(n["position"] for n in detail["config"]["nodes"])
    assert [f["name"] for f in detail["custom_nodes"]["functions"]] == ["normalizar_texto"]
    assert (await client.post(base, json={"name": "pagos"})).status_code == 409

    listed = (await client.get(base)).json()
    assert listed[0]["name"] == "pagos" and listed[0]["nodes"] == 4 and listed[0]["last_run"] is None
    generic = (await client.get(f"/api/v1/projects/{pid}/workforce", params={"kind": "workflow"})).json()
    assert generic[0]["kind"] == "workflow"

    files = (await client.get(f"/api/v1/projects/{pid}/files")).json()["files"]
    assert {
        "workforce/pagos/workflow.py",
        "workforce/pagos/workflow_runtime.py",
        "workforce/pagos/layout.json",
        "workforce/pagos/nodes.py",
        "workforce/pagos/messer.yaml",
    } <= set(files)

    # Add a wait node between the approval and the output.
    config = detail["config"]
    config["nodes"].insert(
        3,
        {
            "id": "esperar",
            "type": "wait",
            "label": "Esperar",
            "config": {"seconds": 2},
            "position": {"x": 900, "y": 80},
        },
    )
    config["edges"] = [e for e in config["edges"] if e["source"] != "aprobar"] + [
        {"source": "aprobar", "target": "esperar"},
        {"source": "esperar", "target": "resultado"},
    ]
    saved = await client.put(f"{base}/pagos/graph", json={"config": config, "viewport": {"x": 5, "y": 6, "zoom": 0.9}})
    assert saved.status_code == 200, saved.text
    assert 'wf.wait("esperar", seconds=2, label="Esperar")' in saved.json()["code"]
    assert saved.json()["viewport"] == {"x": 5.0, "y": 6.0, "zoom": 0.9}

    # Invalid graphs are refused with every issue (inline errors on the canvas).
    cyclic = json.loads(json.dumps(config))
    cyclic["edges"].append({"source": "esperar", "target": "preparar"})
    bad = await client.put(f"{base}/pagos/graph", json={"config": cyclic})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_workflow"
    assert {i["code"] for i in bad.json()["error"]["details"]["issues"]} == {"cycle"}
    checked = (await client.post(f"{base}/pagos/validate", json={"config": cyclic})).json()
    assert checked["valid"] is False and checked["issues"][0]["node_id"] in {"preparar", "aprobar", "esperar"}

    moved = await client.put(f"{base}/pagos/layout", json={"positions": {"esperar": {"x": 1234, "y": 99}}})
    assert moved.status_code == 200
    again = (await client.get(f"{base}/pagos")).json()
    esperar = next(n for n in again["config"]["nodes"] if n["id"] == "esperar")
    assert esperar["position"] == {"x": 1234.0, "y": 99.0}

    # Hand-edited literals keep the canvas in sync…
    code = again["code"].replace("seconds=2", "seconds=3")
    edited = await client.put(f"{base}/pagos/code", json={"code": code})
    assert edited.status_code == 200, edited.text
    assert edited.json()["source_mode"] == "config"
    assert next(n for n in edited.json()["config"]["nodes"] if n["id"] == "esperar")["config"]["seconds"] == 3
    # …anything else switches to code mode (code wins); the generic code endpoint behaves the same.
    syntax = await client.put(f"{base}/pagos/code", json={"code": "def roto(:\n"})
    assert syntax.status_code == 400 and syntax.json()["error"]["details"]["line"] == 1
    custom = await client.put(
        f"/api/v1/projects/{pid}/workforce/pagos/code", json={"code": code + "\n\nprint('hola')\n"}
    )
    assert custom.status_code == 200
    code_mode = (await client.get(f"{base}/pagos")).json()
    assert code_mode["source_mode"] == "code" and code_mode["config"] is None
    assert code_mode["flow"] is None and code_mode["flow_error"]  # no runtime in this test

    # Versions: save, then restore back to the canvas version.
    versions = f"/api/v1/projects/{pid}/workforce/pagos/versions"
    assert (await client.post(versions, json={"message": "código"})).status_code == 201
    restore = await client.post(f"{versions}/1/restore")
    assert restore.status_code == 200
    audit = (await client.get("/api/v1/audit-log", params={"action": "workforce.code_edited"})).json()
    assert audit


async def test_custom_nodes_crud(client: httpx.AsyncClient) -> None:
    pid = await _project(client)
    base = f"/api/v1/projects/{pid}/workflows"
    await client.post(base, json={"name": "limpieza"})
    url = f"{base}/limpieza/custom-nodes"
    added = await client.post(url, json={"name": "puntuar", "description": "Puntúa un cliente"})
    assert added.status_code == 201, added.text
    assert {f["name"] for f in added.json()["functions"]} == {"normalizar_texto", "puntuar"}
    assert (await client.post(url, json={"name": "puntuar"})).status_code == 409
    assert (await client.post(url, json={"name": "Mal Nombre"})).status_code == 400

    detail = (await client.get(f"{base}/limpieza")).json()
    config = detail["config"]
    config["nodes"].insert(
        1,
        {
            "id": "limpiar",
            "type": "custom",
            "label": "Limpiar",
            "config": {"function": "normalizar_texto", "args": {"texto": "{{input.mensaje}}"}},
        },
    )
    config["edges"] = [{"source": "entrada", "target": "limpiar"}, {"source": "limpiar", "target": "resultado"}]
    config["nodes"][-1]["config"]["value"] = "{{limpiar.output.texto}}"
    saved = await client.put(f"{base}/limpieza/graph", json={"config": config})
    assert saved.status_code == 200, saved.text
    assert "from . import nodes" in saved.json()["code"] and "nodes.normalizar_texto" in saved.json()["code"]
    unknown = json.loads(json.dumps(config))
    unknown["nodes"][1]["config"]["function"] = "no_existe"
    assert (await client.put(f"{base}/limpieza/graph", json={"config": unknown})).json()["error"][
        "code"
    ] == "invalid_workflow"

    in_use = await client.delete(f"{url}/normalizar_texto")
    assert in_use.status_code == 409 and in_use.json()["error"]["details"]["nodes"] == ["limpiar"]
    removed = await client.delete(f"{url}/puntuar")
    assert removed.status_code == 200 and [f["name"] for f in removed.json()["functions"]] == ["normalizar_texto"]
    broken = await client.put(url, json={"code": "def x(:\n    pass\n"})
    assert broken.status_code == 400 and broken.json()["error"]["code"] == "syntax_error"
    code = (await client.get(url)).json()["code"] + "\n\nasync def resumir(texto: str) -> str:\n    return texto[:10]\n"
    ok = await client.put(url, json={"code": code})
    assert ok.status_code == 200 and {f["name"] for f in ok.json()["functions"]} == {"normalizar_texto", "resumir"}
    detail = (await client.get(f"{base}/limpieza")).json()
    assert set(detail["config"]["custom_nodes"]) == {"normalizar_texto", "resumir"}


async def test_palette_and_roles(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    pid = await _project(client)
    await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})
    await client.post(f"/api/v1/projects/{pid}/workflows", json={"name": "flujo"})
    palette = (await client.get(f"/api/v1/projects/{pid}/workflows/palette")).json()
    types = {t["type"]: t for t in palette["node_types"]}
    assert set(types) >= {
        "input",
        "agent",
        "llm",
        "tool",
        "connector_action",
        "knowledge_search",
        "sql_query",
        "http_request",
        "condition",
        "loop",
        "transform",
        "approval",
        "wait",
        "sub_workflow",
        "output",
        "custom",
    }
    assert types["wait"]["config_schema"]["properties"]["seconds"]["maximum"] == 240
    assert {t["key"] for t in palette["tools"]} >= {"send_email", "calculator"}
    assert "web_search" not in {t["key"] for t in palette["tools"]}
    assert palette["agents"] == [{"name": "soporte", "description": ""}]
    assert palette["workflows"][0]["name"] == "flujo"

    from messer_common.db.models import Membership, User

    viewer = await make_user(email="viewer@acme.example")
    async with system_session() as s:
        owner = (await s.execute(select(User).where(User.email == "ops@acme.example"))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == owner.id))).scalar_one()
        s.add(Membership(org_id=org_id, user_id=viewer.id, role="viewer"))
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": "viewer@acme.example", "password": "Sup3rSecret!pass"})
    ).status_code == 200
    client.headers["X-Messer-Org"] = str(org_id)
    assert (await client.get(f"/api/v1/projects/{pid}/workflows/flujo")).status_code == 200
    detail = (await client.get(f"/api/v1/projects/{pid}/workflows/flujo")).json()
    denied = await client.put(f"/api/v1/projects/{pid}/workflows/flujo/graph", json={"config": detail["config"]})
    assert denied.status_code == 403
    assert (await client.post(f"/api/v1/projects/{pid}/workflows/flujo/run", json={})).status_code == 403


# ------------------------------------------------------------------------------------------------- runs


async def test_manual_run_streams_nodes_and_resumes_after_approval(client: httpx.AsyncClient, runtime: Harness) -> None:
    pid = await _project(client)
    base = f"/api/v1/projects/{pid}/workflows"
    assert (await client.post(base, json={"name": "pagos", "template": "approval"})).status_code == 201
    events = await _sse(client, f"{base}/pagos/run", {"input": {"importe": 1200, "concepto": "Licencias"}})
    assert events[0]["type"] == "WORKFLOW_RUN"
    node_outputs = {e["path"]: e for e in events if e.get("type") == "OUTPUT"}
    assert node_outputs["pagos.preparar"]["output"] == {"importe": 1200, "concepto": "Licencias", "origen": "manual"}
    assert any(e.get("type") == "APPROVAL" and e["path"] == "pagos.aprobar" for e in events)
    finished = events[-1]
    assert finished["type"] == "RUN_FINISHED" and finished["status"] == "paused", finished

    inbox = (await client.get("/api/v1/approvals")).json()
    approval = inbox["items"][0]
    assert approval["title"] == "¿Aprobar Licencias por 1200 €?" and approval["assigned_role"] == "admin"
    assert approval["payload"] == {"importe": 1200, "concepto": "Licencias"}
    resumed = await _sse(
        client,
        f"/api/v1/approvals/{approval['id']}/decision?stream=true",
        {"decision": "approve_with_changes", "payload": {"importe": 1100}, "comment": "Descuento"},
    )
    assert resumed[-1]["status"] == "success", resumed[-1]
    output = next(e for e in resumed if e.get("type") == "OUTPUT" and e["path"] == "pagos")
    assert output["output"] == {"aprobado": True, "importe": 1100, "concepto": "Licencias"}
    replayed = next(e for e in resumed if e.get("type") == "OUTPUT" and e["path"] == "pagos.preparar")
    assert replayed["output"]["importe"] == 1200

    detail = (await client.get(f"/api/v1/runs/{resumed[-1]['run_id']}")).json()
    steps = {s["name"]: s for s in detail["spans"] if s["kind"] == "step"}
    assert {"entrada", "preparar", "aprobar", "resultado"} <= set(steps)
    assert steps["preparar"]["meta"].get("studio_replay")
    listed = (await client.get(base)).json()
    assert listed[0]["last_run"]["status"] == "paused"  # the root run; resumed runs are its children

    missing = await client.post(f"{base}/pagos/run", json={"input": {}})
    assert missing.status_code == 200  # optional inputs: the run itself decides
    required = (await client.post(base, json={"name": "clasificar", "template": "classify"})).json()
    assert required["config"]["inputs"][0]["required"] is True
    refused = await client.post(f"{base}/clasificar/run", json={"input": {}})
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "missing_inputs"


async def test_phase5_webhook_and_cron_fire_pause_email_approve_complete(
    client: httpx.AsyncClient, runtime: Harness, queued: list[tuple[str, tuple[Any, ...]]]
) -> None:
    from messer_scheduler.tasks.triggers import fire_due_cron
    from messer_worker.jobs.approvals import notify_approval, resume_run
    from messer_worker.jobs.triggers import fire_trigger

    pid = await _project(client, "ana@acme.example")
    base = f"/api/v1/projects/{pid}/workflows"
    detail = (await client.post(base, json={"name": "facturas", "template": "approval"})).json()
    config = detail["config"]
    prepare = next(n for n in config["nodes"] if n["id"] == "preparar")
    prepare["config"]["value"] = {
        "importe": "{{event.body.importe}}",
        "concepto": "{{event.body.concepto}}",
        "origen": "{{event.type}}",
    }
    assert (await client.put(f"{base}/facturas/graph", json={"config": config})).status_code == 200

    hook = (
        await client.post(
            f"/api/v1/projects/{pid}/triggers",
            json={"workforce": "facturas", "kind": "webhook", "environment": "development"},
        )
    ).json()
    body = json.dumps({"importe": 830, "concepto": "Factura F-77"}).encode()
    signed = await client.post(
        f"/api/hooks/{hook['id']}",
        content=body,
        headers={
            "X-Messer-Signature": triggers.sign(hook["secret"], body),
            "Content-Type": "application/json",
            "X-Messer-Event-Id": "evt-77",
        },
    )
    assert signed.status_code == 202, signed.text
    job, args = queued.pop(0)
    assert job == "fire_trigger"
    result = await fire_trigger({}, *args)
    assert result["status"] == "paused", result

    async with system_session() as s:
        approval = (
            await s.execute(select(Approval).where(Approval.run_id == uuid.UUID(result["run_id"])))
        ).scalar_one()
        assert approval.payload == {"importe": 830, "concepto": "Factura F-77"}
        trigger = await s.get(Trigger, uuid.UUID(hook["id"]))
        assert trigger is not None and trigger.state["last"]["status"] == "paused"
    notify = [a for j, a in queued if j == "notify_approval"]
    assert notify and notify[0][0] == str(approval.id)
    ConsoleEmailAdapter.sent.clear()
    assert await notify_approval({}, str(approval.id)) == 1
    email = ConsoleEmailAdapter.sent[0]
    assert email.to == "ana@acme.example"
    token = re.search(r"/approvals/email\?token=([^\s\"'<]+)", email.text)
    assert token is not None
    approve_link = token.group(1)

    # The approver opens the link on their phone (no session) and confirms.
    phone = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")  # type: ignore[attr-defined]
    async with phone:
        preview = await phone.get("/api/v1/approval-links", params={"token": approve_link})
        assert preview.status_code == 200 and preview.json()["decision"] == "approve"
        decided = await phone.post("/api/v1/approval-links", json={"token": approve_link})
        assert decided.status_code == 200 and decided.json()["resumed"] is True
    resume = next(a for j, a in queued if j == "resume_run")
    finished = await resume_run({}, resume[0])
    assert finished["status"] == "success", finished
    async with system_session() as s:
        run = await s.get(Run, uuid.UUID(finished["run_id"]))
        assert run is not None and run.output == {"aprobado": True, "importe": 830, "concepto": "Factura F-77"}
        assert run.parent_run_id == uuid.UUID(result["run_id"])

    # The same workflow on a schedule: the scheduler fires it, it pauses for approval as well.
    cron = (
        await client.post(
            f"/api/v1/projects/{pid}/triggers",
            json={
                "workforce": "facturas",
                "kind": "cron",
                "environment": "development",
                "config": {"expression": "*/5 * * * *", "timezone": "Europe/Madrid", "static_input": {"importe": 10}},
            },
        )
    ).json()
    async with system_session() as s:
        row = await s.get(Trigger, uuid.UUID(cron["id"]))
        assert row is not None
        row.next_fire_at = datetime.now(UTC) - timedelta(seconds=5)
    queued.clear()
    await fire_due_cron()
    job, args = queued.pop(0)
    assert job == "fire_trigger" and args[1]["type"] == "cron"
    scheduled = await fire_trigger({}, *args)
    assert scheduled["status"] == "paused", scheduled
    async with system_session() as s:
        pending = (
            await s.execute(select(Approval).where(Approval.run_id == uuid.UUID(scheduled["run_id"])))
        ).scalar_one()
        assert pending.title.startswith("¿Aprobar") and pending.status == "pending"
