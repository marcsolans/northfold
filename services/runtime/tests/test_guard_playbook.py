"""Guard's shared kernel: playbook schema and validation, deterministic evaluator, rules-based generation."""

from __future__ import annotations

from typing import Any

import pytest

from messer_common.guard import (
    ArgConstraint,
    Policy,
    ToolAction,
    ToolCall,
    TurnMatch,
    combine_tool_verdicts,
    combine_votes,
    constraint_holds,
    match_turn,
    parse_verdict,
    policy_tool_verdict,
    read_turn,
    tools_from_config,
    validate_output,
    validate_playbook,
)
from messer_common.guard.generate import amount_thresholds, generate_playbook, rules_playbook

SMALL = "anthropic/claude-haiku-5-5"
LARGE = "anthropic/claude-sonnet-5-5"


def base(**extra: Any) -> dict[str, Any]:
    return {"small_model": SMALL, "large_model": LARGE, **extra}


CONFIG: dict[str, Any] = {
    "system_prompt": "Asistente de facturas. Pide aprobación humana antes de emitir un abono de más de 500 €.",
    "tools": [
        {
            "type": "custom",
            "key": "create_credit_note",
            "description": "Emite un abono sobre una factura",
            "input_schema": {
                "type": "object",
                "properties": {"amount": {"type": "number"}, "invoice": {"type": "string"}},
            },
        },
        {"type": "builtin", "key": "knowledge_search"},
        {"type": "builtin", "key": "send_email"},
        {"type": "connector", "key": "hubspot.create_contact", "requires_approval": True},
    ],
}


def test_schema_errors_point_at_fields() -> None:
    result = validate_playbook(
        {
            "small_model": "haiku",
            "large_model": "openai/gpt",
            "policies": [
                {"id": "Bad Id"},
                {
                    "id": "x",
                    "tool_action": {
                        "tool": "t",
                        "action": "deny",
                        "constraints": [{"arg": "a", "op": ">", "value": "n"}],
                    },
                },
                {"id": "y", "match": {"text_patterns": ["("]}},
                {"id": "z", "unknown": 1},
            ],
            "output_schema": {"type": "nope"},
        }
    )
    assert result.playbook is None and not result.ok
    paths = {i.path for i in result.issues}
    assert {
        "small_model",
        "large_model",
        "policies.0.id",
        "policies.1.tool_action.constraints.0",
        "policies.2.match.text_patterns",
        "policies.3.unknown",
        "output_schema",
    } <= paths
    assert next(i for i in result.issues if i.path == "policies.3.unknown").message == "Campo no reconocido"


def test_duplicate_ids_and_response_with_tool_action_are_rejected() -> None:
    dup = validate_playbook(base(policies=[{"id": "a", "model": "small"}, {"id": "a", "model": "large"}]))
    assert not dup.ok and "repetido" in dup.issues[0].message
    both = validate_playbook(
        base(policies=[{"id": "a", "response": "Hola", "tool_action": {"tool": "t", "action": "deny"}}])
    )
    assert not both.ok


def test_warnings_against_the_agent_tools() -> None:
    tools = tools_from_config(CONFIG)
    result = validate_playbook(
        base(
            policies=[
                {"id": "ghost", "tool_action": {"tool": "delete_everything", "action": "deny"}},
                {"id": "ungated", "tool_action": {"tool": "create_credit_note", "action": "require_approval"}},
                {
                    "id": "badarg",
                    "tool_action": {
                        "tool": "create_credit_note",
                        "action": "deny",
                        "constraints": [
                            {"arg": "importe", "op": ">", "value": 5},
                            {"arg": "invoice", "op": ">", "value": 5},
                        ],
                    },
                },
                {"id": "needs", "requires": ["identity_verified"], "model": "small", "match": {"first_turn": True}},
                {"id": "everything", "model": "large"},
            ]
        ),
        tools=tools,
    )
    assert result.ok  # warnings never prevent saving
    codes = {(i.path, i.code) for i in result.issues}
    assert ("policies.0.tool_action.tool", "unknown_tool") in codes
    assert ("policies.1.tool_action.action", "approval_not_gated") in codes
    assert ("policies.2.tool_action.constraints.0.arg", "unknown_arg") in codes
    assert ("policies.2.tool_action.constraints.1.op", "non_numeric_arg") in codes
    assert ("policies.3.requires.0", "fact_never_provided") in codes
    assert ("policies.4.match", "matches_every_turn") in codes


def test_tools_from_config_knows_names_side_effects_and_gates() -> None:
    tools = {t.name: t for t in tools_from_config(CONFIG)}
    assert set(tools) == {"create_credit_note", "knowledge_search", "send_email", "hubspot_create_contact"}
    assert tools["create_credit_note"].side_effect and not tools["create_credit_note"].gated
    assert not tools["knowledge_search"].side_effect
    assert tools["send_email"].gated and tools["hubspot_create_contact"].gated


def _body(*messages: dict[str, Any]) -> dict[str, Any]:
    return {"model": "claude-sonnet-5-5", "messages": list(messages), "tools": [{"name": "lookup"}]}


def test_read_turn_and_structural_match() -> None:
    first = read_turn(_body({"role": "user", "content": "hola"}))
    assert first.last_kind == "user_text" and first.first_turn and first.model == "anthropic/claude-sonnet-5-5"
    after_tool = read_turn(
        _body(
            {"role": "user", "content": "Busca la factura F-1"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "lookup", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        )
    )
    assert after_tool.last_kind == "tool_result" and after_tool.user_text == "Busca la factura F-1"
    assert after_tool.builtin_facts() == {"tool:lookup"} and after_tool.tool_results[0].name == "lookup"
    assert match_turn(TurnMatch(last_message="tool_result", tool_results=["look*"]), after_tool)
    assert not match_turn(TurnMatch(last_message="user_text"), after_tool)
    assert match_turn(TurnMatch(text_patterns=["^HOLA$"], max_chars=10, first_turn=True), first)
    assert not match_turn(TurnMatch(text_excludes=["hola"]), first)
    assert not match_turn(TurnMatch(min_chars=10), first)


@pytest.mark.parametrize(
    ("op", "value", "args", "expected"),
    [
        (">", 500, {"amount": 900}, True),
        (">", 500, {"amount": "1.200,50"}, True),
        (">", 500, {"amount": 200}, False),
        (">", 500, {}, False),
        ("<=", 500, {"amount": 500}, True),
        ("==", 1, {"amount": "1"}, True),
        ("!=", "EUR", {"amount": "USD"}, True),
        ("in", ["ES", "PT"], {"amount": "ES"}, True),
        ("not_in", ["ES"], {"amount": "FR"}, True),
        ("contains", "urgente", {"amount": "Pago URGENTE"}, True),
        ("matches", r"^F-\d+$", {"amount": "F-1043"}, True),
        ("exists", None, {"amount": 0}, True),
        ("missing", None, {}, True),
    ],
)
def test_constraints(op: str, value: Any, args: dict[str, Any], expected: bool) -> None:
    assert constraint_holds(ArgConstraint(arg="amount", op=op, value=value), args) is expected  # type: ignore[arg-type]


def test_nested_argument_paths() -> None:
    c = ArgConstraint(arg="lines.0.amount", op=">", value=10)
    assert constraint_holds(c, {"lines": [{"amount": 11}]})
    assert not constraint_holds(c, {"lines": []})


def _tool_policy(action: str, constraints: list[dict[str, Any]] | None = None, **extra: Any) -> Policy:
    return Policy(
        id=f"p_{action}",
        tool_action=ToolAction.model_validate({"tool": "pay", "action": action, "constraints": constraints or []}),
        **extra,
    )


def test_tool_verdicts() -> None:
    big = ToolCall(id="1", name="pay", input={"amount": 900})
    small = ToolCall(id="2", name="pay", input={"amount": 10})
    limit = [{"arg": "amount", "op": ">", "value": 500}]
    assert policy_tool_verdict(_tool_policy("deny", limit), big, set(), gated=False).verdict == "deny"
    assert policy_tool_verdict(_tool_policy("deny", limit), small, set(), gated=False).verdict == "pass"
    within = [{"arg": "amount", "op": "<=", "value": 500}]
    assert policy_tool_verdict(_tool_policy("allow", within), small, set(), gated=False).verdict == "allow"
    assert policy_tool_verdict(_tool_policy("allow", within), big, set(), gated=False).reason == "constraints"
    approval = _tool_policy("require_approval", limit)
    assert policy_tool_verdict(approval, big, set(), gated=True).reason == "gated"
    assert policy_tool_verdict(approval, big, {"approval:pay"}, gated=False).reason == "approved"
    assert policy_tool_verdict(approval, big, set(), gated=False).reason == "approval_required"
    needs = _tool_policy("allow", requires=["kyc"])
    verdict = policy_tool_verdict(needs, small, set(), gated=False)
    assert verdict.verdict == "deny" and verdict.missing == ["kyc"]
    assert policy_tool_verdict(needs, small, {"kyc"}, gated=False).verdict == "allow"
    a, d = (
        policy_tool_verdict(_tool_policy("allow"), big, set(), gated=False),
        policy_tool_verdict(_tool_policy("deny", limit), big, set(), gated=False),
    )
    assert combine_tool_verdicts([a, d]) == "deny" and combine_tool_verdicts([a]) == "allow"
    assert combine_tool_verdicts([]) == "pass"


def test_votes_and_verdict_parsing() -> None:
    assert combine_votes([True, None, None], "none")
    assert combine_votes([True, True, False], "majority") and not combine_votes([True, None, False], "majority")
    assert combine_votes([True, True, True], "unanimous") and not combine_votes([True, True, None], "unanimous")
    assert parse_verdict('{"match": true, "reason": "x"}') is True
    assert parse_verdict('```json\n{"match": false}\n```') is False
    assert parse_verdict('Claro: {"match": "yes"}') is None and parse_verdict("no sé") is None


def test_output_validation() -> None:
    schema = {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}
    assert validate_output(schema, '{"total": 3}') == (True, [])
    ok, errors = validate_output(schema, '{"total": "3"}')
    assert not ok and errors[0].startswith("total:")
    assert validate_output(schema, "tres")[0] is False


def test_amount_thresholds() -> None:
    found = amount_thresholds("Los abonos de más de 500 € y los reembolsos over €1,000 necesitan revisión; >= 20")
    assert [(t.value, t.op) for t in found] == [(500.0, ">"), (1000.0, ">"), (20.0, ">=")]


def test_rules_playbook_for_the_demo_agent() -> None:
    tools = tools_from_config(CONFIG)
    playbook, notes = rules_playbook(tools=tools, system_prompt=str(CONFIG["system_prompt"]))
    by_id = {p.id: p for p in playbook.policies}
    assert by_id["small_talk"].model == "small" and by_id["small_talk"].condition is None
    limit = by_id["create_credit_note_limit"].tool_action
    assert limit is not None and limit.action == "deny"  # not approval-gated in the agent → Guard blocks it
    assert limit.constraints[0].model_dump() == {"arg": "amount", "op": ">", "value": 500.0}
    assert by_id["knowledge_search_allow"].tool_action.action == "allow"  # type: ignore[union-attr]
    assert by_id["send_email_approval"].tool_action.action == "require_approval"  # type: ignore[union-attr]
    assert by_id["hubspot_create_contact_approval"].tool_action is not None
    assert all(p.condition is None for p in playbook.policies)  # works without any model
    assert notes and validate_playbook(playbook.model_dump(), tools=tools).ok

    gated = {**CONFIG, "tools": [{**CONFIG["tools"][0], "requires_approval": True}]}
    gated_book, _ = rules_playbook(tools=tools_from_config(gated), system_prompt=str(CONFIG["system_prompt"]))
    action = next(p for p in gated_book.policies if p.id == "create_credit_note_limit").tool_action
    assert action is not None and action.action == "require_approval" and action.message is None


async def test_generation_without_provider_keys_uses_rules() -> None:
    import uuid

    result = await generate_playbook(
        org_id=uuid.uuid4(), project_id=None, config=CONFIG, code="", tools=tools_from_config(CONFIG)
    )
    assert result.generated_by == "rules" and result.meta["demo"] is True
    assert any(p.id == "create_credit_note_limit" for p in result.playbook.policies)
