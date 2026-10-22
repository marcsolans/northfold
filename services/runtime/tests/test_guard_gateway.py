"""Guard sessions through the model gateway endpoint: semantic votes, fixed answers, output schema repair, facts
carried across runs, routing refusals, fail-closed enforcement and the calls Guard leaves alone."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from messer_api.services.projects import create_agent, create_project
from messer_common.db import system_session
from messer_common.db.models import GuardPlaybook, ModelPolicy, Project, Run
from messer_common.settings import get_settings
from messer_common.studio.agent_spec import ToolConfig, default_agent_config
from messer_common.testing.fixtures import principal_for
from messer_runtime import guard_bridge
from messer_runtime.guard.votes import VOTE_SYSTEM
from messer_runtime.testing import Harness

SMALL = "anthropic/claude-haiku-5-5"
LARGE = "anthropic/claude-opus-5-5"
AGENT_MODEL = "claude-sonnet-5-5"
TOOLS = [
    {
        "name": "create_credit_note",
        "description": "Emite un abono",
        "input_schema": {
            "type": "object",
            "properties": {"amount": {"type": "number"}, "invoice_id": {"type": "string"}},
            "required": ["amount"],
        },
    }
]


def book(*policies: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "version": 1,
        "enabled": True,
        "small_model": SMALL,
        "large_model": LARGE,
        "policies": list(policies),
        **extra,
    }


async def guarded(make_org, playbook: dict[str, Any]) -> tuple[Project, str]:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    principal = principal_for(owner.id, org.id, "owner")
    async with system_session() as s:
        project = await create_project(s, principal, name="Guard")
        cfg = default_agent_config("facturas")
        cfg.tools = [ToolConfig(type="custom", key="create_credit_note")]
        member = await create_agent(s, principal, project, config=cfg)
        member.guard_enabled = True
        s.add(GuardPlaybook(org_id=org.id, project_id=project.id, workforce_id=member.id, playbook=playbook))
    run_id = uuid.uuid4().hex
    await guard_bridge.remember_member(run_id, str(project.id), "facturas")
    return project, run_id


def body(text: str, *, tools: bool = True, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "model": AGENT_MODEL,
        "max_tokens": 512,
        "messages": [{"role": "user", "content": text}],
        **extra,
    }
    if tools:
        out["tools"] = TOOLS
    return out


async def call(runtime: Harness, project: Project, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    res = await runtime.client.post(
        f"/internal/v1/orgs/{project.org_id}/proxies/anthropic/v1/messages",
        json=payload,
        headers={"x-messer-run-id": run_id},
    )
    assert res.status_code == 200, res.text
    return res.json()


def message(content: list[dict[str, Any]], model: str, stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 1000, "output_tokens": 100},
    }


def anthropic(
    monkeypatch: pytest.MonkeyPatch,
    verdicts: list[bool],
    replies: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Mock Anthropic: vote requests get the next verdict, agent requests the next reply. Returns the requests."""
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    seen: list[dict[str, Any]] = []
    votes = iter(verdicts)
    answers = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload)
        if payload.get("system") == VOTE_SYSTEM:
            verdict = {"match": next(votes), "reason": "test"}
            return httpx.Response(200, json=message([{"type": "text", "text": json.dumps(verdict)}], payload["model"]))
        content = next(answers)
        stop = "tool_use" if any(b["type"] == "tool_use" for b in content) else "end_turn"
        return httpx.Response(200, json=message(content, payload["model"], stop))

    gateway.anthropic_transport = httpx.MockTransport(handler)
    return seen


def text(value: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": value}]


def credit_note(amount: float) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": "Voy a emitirlo."},
        {"type": "tool_use", "id": "toolu_1", "name": "create_credit_note", "input": {"amount": amount}},
    ]


COMPLEX = {
    "id": "complex_dispute",
    "condition": "El cliente disputa una factura y pide revisar varios cargos",
    "model": "large",
    "confirmation": "majority",
}


async def test_semantic_policy_votes_three_times_and_routes(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, book(COMPLEX))
    seen = anthropic(monkeypatch, [True, False, True], [text("Reviso los cargos.")])
    reply = await call(runtime, project, run_id, body("No reconozco tres cargos de la factura F-77, revísalos"))
    assert reply["content"][0]["text"] == "Reviso los cargos."
    assert [p["model"] for p in seen] == ["claude-haiku-5-5"] * 3 + ["claude-opus-5-5"]
    assert all(p["output_config"]["format"]["type"] == "json_schema" for p in seen[:3])
    assert "temperature" not in seen[0]
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["policy"] == "complex_dispute" and decision["route"] == "large" and decision["model"] == LARGE
    assert decision["votes"][0]["votes"] == [True, False, True] and decision["on_path"] is True
    assert decision["input_tokens"] == 3000 and decision["output_tokens"] == 300
    assert float(decision["cost_usd"]) > 0  # the votes are Guard's own overhead
    # Same tokens at the agent's own model (Sonnet) vs. at the routed model (Opus).
    assert float(decision["baseline_cost_usd"]) < float(decision["priced_cost_usd"])


async def test_unanimous_confirmation_needs_every_vote(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, book({**COMPLEX, "confirmation": "unanimous"}))
    seen = anthropic(monkeypatch, [True, True, False], [text("Hola.")])
    await call(runtime, project, run_id, body("No reconozco tres cargos"))
    assert seen[-1]["model"] == AGENT_MODEL
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["policy"] == "fallthrough" and decision["on_path"] is False and decision["route"] == "default"


async def test_semantic_policies_abstain_in_demo_mode(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.persistence import gateway_totals

    project, run_id = await guarded(make_org, book(COMPLEX))
    await call(runtime, project, run_id, body("No reconozco tres cargos"))
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["votes"][0]["skipped"] == "demo" and decision["policy"] == "fallthrough"
    assert decision["demo"] is True
    _, _, calls, _ = await gateway_totals(run_id)
    assert len(calls) == 1  # no vote reached a model


async def test_fixed_response_answers_without_a_model(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.persistence import gateway_totals

    policy = {
        "id": "opening_hours",
        "match": {"text_patterns": ["horario"]},
        "response": "Atendemos de lunes a viernes de 9:00 a 18:00.",
        "provides": ["asked_hours"],
    }
    project, run_id = await guarded(make_org, book(policy))
    reply = await call(runtime, project, run_id, body("¿Cuál es vuestro horario?"))
    assert reply["content"] == [{"type": "text", "text": policy["response"]}]
    _, _, calls, _ = await gateway_totals(run_id)
    assert calls == []
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["action"] == "answer" and decision["model"] is None and "asked_hours" in decision["facts"]


SCHEMA = {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}


async def test_output_schema_is_repaired_with_one_reask(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, book(output_schema=SCHEMA))
    seen = anthropic(monkeypatch, [], [text("El total es 12 €"), text('```json\n{"total": 12}\n```')])
    reply = await call(runtime, project, run_id, body("¿Total de la factura F-1?"))
    assert reply["content"][0]["text"].endswith("```")
    assert "JSON Schema" in seen[1]["messages"][-1]["content"]
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["action"] == "repair" and decision["status"] == "success"
    assert decision["output"]["schema"]["valid"] is True and decision["output"]["schema"]["reasked"] is True


async def test_output_still_invalid_is_flagged(runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, book(output_schema=SCHEMA))
    anthropic(monkeypatch, [], [text("doce"), text('{"total": "doce"}')])
    await call(runtime, project, run_id, body("¿Total?"))
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["status"] == "invalid_output"


VERIFY = {
    "id": "identity",
    "match": {"text_patterns": [r"\bDNI\b"]},
    "provides": ["identity_verified"],
    "model": "small",
}
NOTE_NEEDS_IDENTITY = {
    "id": "credit_note_identity",
    "requires": ["identity_verified"],
    "tool_action": {"tool": "create_credit_note", "action": "allow"},
}


async def test_requires_blocks_until_a_fact_holds_and_facts_follow_the_conversation(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    project, first = await guarded(make_org, book(VERIFY, NOTE_NEEDS_IDENTITY))
    anthropic(monkeypatch, [], [credit_note(100), text("Gracias, verificado."), credit_note(100)])

    blocked = await call(runtime, project, first, body("Quiero un abono de 100"))
    assert [b["type"] for b in blocked["content"]] == ["text"] and blocked["stop_reason"] == "end_turn"
    assert "identity_verified" in blocked["content"][0]["text"]
    assert (await guard_bridge.decisions(first))[-1]["status"] == "blocked"

    await call(runtime, project, first, body("Mi DNI es 12345678Z"))
    assert "identity_verified" in (await guard_bridge.decisions(first))[-1]["facts"]

    # A follow-up run of the same conversation starts with the parent's facts.
    second = uuid.uuid4().hex
    async with system_session() as s:
        for rid, parent in ((first, None), (second, first)):
            s.add(
                Run(
                    id=uuid.UUID(rid),
                    org_id=project.org_id,
                    project_id=project.id,
                    status="success",
                    parent_run_id=uuid.UUID(parent) if parent else None,
                )
            )
    await guard_bridge.remember_member(second, str(project.id), "facturas")
    allowed = await call(runtime, project, second, body("Quiero un abono de 100"))
    assert any(b["type"] == "tool_use" for b in allowed["content"]) and allowed["stop_reason"] == "tool_use"
    decision = (await guard_bridge.decisions(second))[-1]
    assert decision["status"] == "success" and decision["output"]["tool_calls"][0]["verdict"] == "allow"


async def test_evaluation_errors_fail_closed_for_restricted_tools(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.guard import session as guard_session

    project, run_id = await guarded(
        make_org,
        book(
            {
                "id": "limit",
                "tool_action": {
                    "tool": "create_credit_note",
                    "action": "deny",
                    "constraints": [{"arg": "amount", "op": ">", "value": 500}],
                },
            }
        ),
    )
    anthropic(monkeypatch, [], [credit_note(10)])

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("evaluator down")

    monkeypatch.setattr(guard_session, "policy_tool_verdict", boom)
    reply = await call(runtime, project, run_id, body("Abono de 10"))
    assert not any(b["type"] == "tool_use" for b in reply["content"])
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["status"] == "error" and decision["blocked_count"] == 1 and decision["errors"]


async def test_routing_respects_the_org_model_policy(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    small_talk = {"id": "small_talk", "match": {"text_patterns": ["^hola$"]}, "model": "small"}
    project, run_id = await guarded(make_org, book(small_talk))
    async with system_session() as s:
        s.add(ModelPolicy(org_id=project.org_id, rules={"deny": ["anthropic/claude-haiku*"]}))
    gateway.invalidate_caches()
    await call(runtime, project, run_id, body("hola"))
    decision = (await guard_bridge.decisions(run_id))[-1]
    assert decision["route_refused"] == "model_policy" and decision["model"] == "anthropic/claude-sonnet-5-5"


async def test_engine_helper_calls_and_unguarded_runs_pass_through(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, book({"id": "x", "match": {"text_patterns": ["."]}, "model": "small"}))
    # An LLM-judge style call of the same run: another model, no tools.
    await call(runtime, project, run_id, {**body("¿Es seguro?", tools=False), "model": "claude-haiku-5-5"})
    assert await guard_bridge.decisions(run_id) == []
    other = uuid.uuid4().hex  # a run that belongs to no member
    await call(runtime, project, other, body("hola"))
    assert await guard_bridge.decisions(other) == []


async def test_invalid_stored_playbook_is_reported_once_and_passes_through(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    project, run_id = await guarded(make_org, {"version": 1, "enabled": True, "policies": "nope"})
    await call(runtime, project, run_id, body("hola"))
    await call(runtime, project, run_id, body("hola otra vez"))
    decisions = await guard_bridge.decisions(run_id)
    assert len(decisions) == 1 and decisions[0]["policy"] == "invalid_playbook" and decisions[0]["status"] == "error"


async def test_routed_call_uses_the_routed_models_request_defaults(
    runtime: Harness, make_org, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    small_talk = {"id": "small_talk", "match": {"text_patterns": ["^hola$"]}, "model": "small"}
    project, run_id = await guarded(make_org, book(small_talk))
    seen = anthropic(monkeypatch, [], [text("¡Hola!")])
    await call(runtime, project, run_id, body("hola"))
    assert seen[0]["model"] == "claude-haiku-5-5" and seen[0]["output_config"] == {"effort": "low"}
