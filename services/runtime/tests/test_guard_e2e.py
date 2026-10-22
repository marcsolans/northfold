"""Phase 12 criterion, end to end through a real sandbox and the demo model: on an invoice agent, Guard routes a
greeting to the small model, blocks a credit note that breaks the playbook (the tool never runs) and lets a
compliant one through — all visible in the trace as ``guard`` spans."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from messer_api.services.projects import create_agent, create_project, repo_for
from messer_common.db import system_session
from messer_common.db.models import Approval, GuardPlaybook, Project, Run, Span
from messer_common.guard.generate import SMALL_TALK_PATTERN
from messer_common.studio.agent_spec import ToolConfig, default_agent_config
from messer_common.testing.fixtures import principal_for
from messer_runtime.testing import Harness

SMALL = "anthropic/claude-haiku-5-5"
# The demo model picks tools by keyword overlap with the tool name, so the requests name the tool's domain.
BIG = "Create a credit note of 900 EUR for invoice F-1043"
SMALL_NOTE = "Create a credit note of 200 EUR for invoice F-1044"
LARGE = "anthropic/claude-sonnet-5-5"

TOOLS_PY = '''"""Invoice tools of the demo agent."""

from messer import Tool


def _create_credit_note(amount: float, invoice_id: str) -> dict:
    return {"credit_note": "AB-2026-001", "amount": amount, "invoice_id": invoice_id, "status": "emitido"}


# A Tool object (not a bare function) so the Studio's require_approval(...) wrapper can gate it.
create_credit_note = Tool(
    name="create_credit_note",
    description="Emite un abono (nota de crédito) sobre una factura por el importe indicado.",
    handler=_create_credit_note,
)
'''


def playbook(action: str = "deny") -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": True,
        "small_model": SMALL,
        "large_model": LARGE,
        "policies": [
            {
                "id": "small_talk",
                "description": "Saludos y agradecimientos al modelo pequeño",
                "match": {"last_message": "user_text", "max_chars": 60, "text_patterns": [SMALL_TALK_PATTERN]},
                "model": "small",
                "confirmation": "none",
            },
            {
                "id": "credit_note_limit",
                "description": "Los abonos de más de 500 € no los emite el agente",
                "tool_action": {
                    "tool": "create_credit_note",
                    "action": action,
                    "constraints": [{"arg": "amount", "op": ">", "value": 500}],
                },
            },
        ],
    }


async def invoice_agent(make_org, *, gated: bool = False, action: str = "deny") -> Project:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    principal = principal_for(owner.id, org.id, "owner")
    async with system_session() as s:
        project = await create_project(s, principal, name="Facturas", description="Atención de facturas")
        cfg = default_agent_config("facturas", "Responde dudas de facturas y emite abonos")
        cfg.system_prompt = "Eres el asistente de facturas de Acme. Los abonos de más de 500 € requieren aprobación."
        cfg.tools = [ToolConfig(type="custom", key="create_credit_note", requires_approval=gated)]
        member = await create_agent(s, principal, project, config=cfg)
        await repo_for(project).write(
            {"workforce/facturas/tools.py": TOOLS_PY}, message="Add invoice tools", author="Test", email="t@example.com"
        )
        member.guard_enabled = True
        s.add(
            GuardPlaybook(
                org_id=org.id,
                project_id=project.id,
                workforce_id=member.id,
                playbook=playbook(action),
                generated_by="manual",
            )
        )
    return project


def run_body(project: Project, prompt: str, **extra: Any) -> dict[str, Any]:
    return {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": "facturas",
        "input": {"prompt": prompt},
        **extra,
    }


async def spans_of(run_id: str) -> list[Span]:
    async with system_session() as s:
        return list(
            (await s.execute(select(Span).where(Span.run_id == uuid.UUID(run_id)).order_by(Span.t0))).scalars().all()
        )


def output_text(run: Run | None) -> str:
    assert run is not None
    content = (run.output or {}).get("content") or []
    return "".join(b.get("text", "") for b in content if isinstance(b, dict))


async def test_guard_routes_blocks_and_allows_on_the_demo_agent(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.persistence import gateway_totals

    project = await invoice_agent(make_org)

    # 1. A greeting is a simple turn: routed to the small model.
    hello = (await runtime.client.post("/internal/v1/runs", json=run_body(project, "hola"))).json()
    assert hello["status"] == "success", hello
    guard = [sp for sp in await spans_of(hello["run_id"]) if sp.kind == "guard"]
    assert len(guard) == 1, guard
    assert guard[0].name == "small_talk" and guard[0].model == SMALL and guard[0].status == "success"
    assert guard[0].meta["route"] == "small" and guard[0].meta["on_path"] is True
    _, _, calls, _ = await gateway_totals(hello["run_id"])
    assert [c["model"] for c in calls] == [SMALL]

    # 2. A €900 credit note breaks the playbook: blocked, the tool never runs, the answer explains it.
    big = (await runtime.client.post("/internal/v1/runs", json=run_body(project, BIG))).json()
    assert big["status"] == "success", big
    spans = await spans_of(big["run_id"])
    blocked = [sp for sp in spans if sp.kind == "guard"]
    assert len(blocked) == 1 and blocked[0].status == "blocked", [(sp.name, sp.status) for sp in blocked]
    assert blocked[0].name == "credit_note_limit"
    call = blocked[0].output["tool_calls"][0]
    assert call["tool"] == "create_credit_note" and call["input"]["amount"] == 900 and call["verdict"] == "deny"
    assert blocked[0].meta["blocked_count"] == 1
    assert not [sp for sp in spans if sp.kind == "tool" and sp.name == "create_credit_note"]
    async with system_session() as s:
        run = await s.get(Run, uuid.UUID(big["run_id"]))
    assert "create_credit_note" in output_text(run) and "credit_note_limit" in output_text(run)
    root = next(sp for sp in spans if sp.parent_span_id is None and sp.kind == "agent")
    assert blocked[0].parent_span_id == root.id

    # 3. A €200 credit note is within the playbook: the tool runs.
    small = (await runtime.client.post("/internal/v1/runs", json=run_body(project, SMALL_NOTE))).json()
    assert small["status"] == "success", small
    spans = await spans_of(small["run_id"])
    assert [sp for sp in spans if sp.kind == "tool" and sp.name == "create_credit_note"]
    guards = [sp for sp in spans if sp.kind == "guard"]
    assert guards and all(sp.status == "success" for sp in guards)
    first = guards[0]
    assert first.output["tool_calls"][0]["verdict"] == "pass" and first.meta["on_path"] is True
    assert guards[-1].meta["facts"] == ["tool:create_credit_note"]


async def test_require_approval_keeps_gated_calls_for_the_human(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project = await invoice_agent(make_org, gated=True, action="require_approval")
    first = (await runtime.client.post("/internal/v1/runs", json=run_body(project, BIG))).json()
    assert first["status"] == "paused", first  # the engine's approval gate stops the run
    guard = next(sp for sp in await spans_of(first["run_id"]) if sp.kind == "guard")
    assert guard.status == "success" and guard.output["tool_calls"][0]["verdict"] == "approval"
    async with system_session() as s:
        approval = (await s.execute(select(Approval).where(Approval.run_id == uuid.UUID(first["run_id"])))).scalar_one()
        approval.status = "approved"
    resumed = (
        await runtime.client.post(
            "/internal/v1/runs",
            json=run_body(
                project,
                BIG,
                parent_run_id=first["run_id"],
                resume={approval.engine_approval_id: {"approved": True}},
            ),
        )
    ).json()
    assert resumed["status"] == "success", resumed
    spans = await spans_of(resumed["run_id"])
    assert [sp for sp in spans if sp.kind == "tool" and sp.name == "create_credit_note"]
    guards = [sp for sp in spans if sp.kind == "guard"]
    assert guards and "approval:create_credit_note" in guards[-1].meta["facts"]


async def test_require_approval_blocks_tools_without_an_approval_gate(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project = await invoice_agent(make_org, gated=False, action="require_approval")
    result = (await runtime.client.post("/internal/v1/runs", json=run_body(project, BIG))).json()
    assert result["status"] == "success", result
    spans = await spans_of(result["run_id"])
    guard = next(sp for sp in spans if sp.kind == "guard")
    assert guard.status == "blocked"
    assert guard.output["tool_calls"][0]["policies"][0]["reason"] == "approval_required"
    assert not [sp for sp in spans if sp.kind == "tool" and sp.name == "create_credit_note"]


async def test_disabled_guard_leaves_calls_untouched(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project = await invoice_agent(make_org)
    async with system_session() as s:
        row = (await s.execute(select(GuardPlaybook).where(GuardPlaybook.project_id == project.id))).scalar_one()
        row.playbook = {**row.playbook, "enabled": False}
    result = (await runtime.client.post("/internal/v1/runs", json=run_body(project, BIG))).json()
    spans = await spans_of(result["run_id"])
    assert not [sp for sp in spans if sp.kind == "guard"]
    assert [sp for sp in spans if sp.kind == "tool" and sp.name == "create_credit_note"]
