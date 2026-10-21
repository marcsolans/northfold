"""End to end through a real sandbox process: streaming run, approval pause → resume, trace, spans, cost, credits."""

from __future__ import annotations

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from messer_api.services.projects import create_agent, create_project
from messer_common import credits
from messer_common.db import system_session
from messer_common.db.models import Approval, CreditLedger, Notification, Project, Run, Span
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import get_settings
from messer_common.studio.agent_spec import ToolConfig, default_agent_config
from messer_common.testing.fixtures import principal_for
from messer_runtime.testing import Harness, anthropic_reply


async def _project_with_agent(make_org, tools: list[ToolConfig]) -> tuple[Project, str]:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    principal = principal_for(owner.id, org.id, "owner")
    async with system_session() as s:
        project = await create_project(s, principal, name="Facturas", description="Soporte de facturas")
        cfg = default_agent_config("soporte", "Atiende dudas de facturas")
        cfg.system_prompt = "Eres el asistente de facturas de Acme. Responde en español."
        cfg.tools = tools
        await create_agent(s, principal, project, config=cfg)
    return project, "soporte"


async def test_streaming_run_with_approval_pause_and_resume(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project, name = await _project_with_agent(
        make_org, [ToolConfig(type="builtin", key="send_email", requires_approval=True, approver_role="admin")]
    )
    ConsoleEmailAdapter.sent.clear()
    prompt = 'Envía un email a ana@example.com con asunto "Factura 1043" y el texto "Su factura ya está pagada"'
    body = {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": name,
        "input": {"prompt": prompt},
        "channel": "studio",
    }
    events = await runtime.stream_run(body)
    kinds = [e.get("type") for e in events]
    assert kinds[0] == "RUN_STARTED", events[:3]
    assert "RUN_ERROR" not in kinds, [e for e in events if e.get("type") == "RUN_ERROR"]
    assert "DELTA" in kinds and "APPROVAL" in kinds
    finished = events[-1]
    assert finished["type"] == "RUN_FINISHED" and finished["status"] == "paused", finished
    assert len(finished["approvals"]) == 1 and finished["demo"] is True
    run_id = finished["run_id"]
    assert ConsoleEmailAdapter.sent == []  # nothing is sent before the human decides

    async with system_session() as s:
        run = await s.get(Run, uuid.UUID(run_id))
        assert run is not None and run.status == "paused" and run.trace and run.git_commit
        approval = (await s.execute(select(Approval).where(Approval.run_id == run.id))).scalar_one()
        assert approval.tool_name == "send_email" and approval.payload["to"] == "ana@example.com"
        notes = (await s.execute(select(Notification).where(Notification.kind == "approval_requested"))).scalars().all()
        assert len(notes) == 1  # the owner (≥ admin) is notified

    resumed = await runtime.client.post(
        "/internal/v1/runs",
        json={
            **body,
            "parent_run_id": run_id,
            "resume": {approval.engine_approval_id: {"approved": True}},
        },
    )
    assert resumed.status_code == 200, resumed.text
    result = resumed.json()
    assert result["status"] == "success", result
    assert [e.to for e in ConsoleEmailAdapter.sent] == ["ana@example.com"]
    assert ConsoleEmailAdapter.sent[0].subject == "Factura 1043"

    async with system_session() as s:
        child = await s.get(Run, uuid.UUID(result["run_id"]))
        assert child is not None and child.parent_run_id == uuid.UUID(run_id) and child.status == "success"
        spans = (await s.execute(select(Span).where(Span.run_id == child.id))).scalars().all()
        assert {"agent", "llm", "tool"} <= {sp.kind for sp in spans}, {sp.kind for sp in spans}


async def test_denied_approval_does_not_execute(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project, name = await _project_with_agent(
        make_org, [ToolConfig(type="builtin", key="send_email", requires_approval=True)]
    )
    ConsoleEmailAdapter.sent.clear()
    body = {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": name,
        "input": {"prompt": 'Envía un email a luis@example.com con asunto "Hola" y el texto "Prueba"'},
    }
    first = (await runtime.client.post("/internal/v1/runs", json=body)).json()
    assert first["status"] == "paused", first
    approval_id = first["approvals"][0]["engine_approval_id"]
    denied = (
        await runtime.client.post(
            "/internal/v1/runs",
            json={
                **body,
                "parent_run_id": first["run_id"],
                "resume": {approval_id: {"approved": False, "reason": "No"}},
            },
        )
    ).json()
    assert denied["status"] in ("success", "cancelled"), denied
    assert ConsoleEmailAdapter.sent == []


async def test_run_cost_and_credits_with_a_real_model_response(
    runtime: Harness,
    make_org,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    gateway.anthropic_transport = httpx.MockTransport(
        anthropic_reply("Su factura vence el día 30.", {"input_tokens": 200_000, "output_tokens": 20_000})
    )
    project, name = await _project_with_agent(make_org, [])
    async with system_session() as s:
        before = await credits.balance(s, project.org_id)
    result = (
        await runtime.client.post(
            "/internal/v1/runs",
            json={
                "org_id": str(project.org_id),
                "project_id": str(project.id),
                "workforce": name,
                "input": {"prompt": "¿Cuándo vence mi factura?"},
            },
        )
    ).json()
    assert result["status"] == "success", result
    assert result["providers"] == ["anthropic"] and result["demo"] is False
    cost = Decimal(result["cost_usd"])
    assert cost > 0 and Decimal(result["credits"]) > 0
    async with system_session() as s:
        after = await credits.balance(s, project.org_id)
        entry = (await s.execute(select(CreditLedger).where(CreditLedger.kind == "usage"))).scalar_one()
        run = await s.get(Run, uuid.UUID(result["run_id"]))
    assert before - after == Decimal(result["credits"])
    assert entry.amount == -Decimal(result["credits"]) and entry.run_id == uuid.UUID(result["run_id"])
    assert run is not None and run.cost_usd == cost and run.models[0]["model"] == "anthropic/claude-sonnet-5-5"


async def test_unknown_member_is_a_run_error(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project, _ = await _project_with_agent(make_org, [])
    events = await runtime.stream_run(
        {
            "org_id": str(project.org_id),
            "project_id": str(project.id),
            "workforce": "no_existe",
            "input": {"prompt": "Hola"},
        }
    )
    assert events == [
        {
            "type": "RUN_ERROR",
            "run_id": events[0]["run_id"],
            "error": {"type": "not_found", "message": "«no_existe» no existe"},
        }
    ]
