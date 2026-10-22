"""Deterministic part of Guard: reading a model request, structural matching, argument constraints, tool
verdicts, vote combination and output validation. No I/O — used by the runtime gateway and the API."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator

from .playbook import ArgConstraint, Confirmation, Policy, TurnMatch, tool_matches

VOTES_PER_CONDITION = 3
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_MISSING = object()

TurnKind = Literal["user_text", "tool_result", "other"]
Verdict = Literal["allow", "deny", "approval", "pass"]


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(slots=True)
class ToolResult:
    name: str
    is_error: bool


@dataclass(slots=True)
class TurnView:
    """What Guard knows about one model call (Anthropic Messages request)."""

    last_kind: TurnKind
    user_text: str
    tool_results: list[ToolResult]
    tools_offered: list[str]
    history_calls: list[ToolCall]
    succeeded_tools: set[str]
    user_turns: int
    model: str

    @property
    def first_turn(self) -> bool:
        return self.user_turns <= 1

    def builtin_facts(self) -> set[str]:
        return {f"tool:{name}" for name in self.succeeded_tools}


def _input(block: dict[str, Any]) -> dict[str, Any]:
    value = block.get("input")
    return value if isinstance(value, dict) else {}


def blocks_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def full_model(model_id: str) -> str:
    return model_id if "/" in model_id else f"anthropic/{model_id}"


def read_turn(body: dict[str, Any]) -> TurnView:
    messages = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    names_by_id: dict[str, str] = {}
    history: list[ToolCall] = []
    succeeded: set[str] = set()
    user_turns = 0
    for message in messages:
        blocks = _blocks(message.get("content"))
        if message.get("role") == "assistant":
            for b in blocks:
                if b.get("type") == "tool_use":
                    call = ToolCall(
                        id=str(b.get("id", "")),
                        name=str(b.get("name", "")),
                        input=_input(b),
                    )
                    history.append(call)
                    names_by_id[call.id] = call.name
        elif message.get("role") == "user":
            results = [b for b in blocks if b.get("type") == "tool_result"]
            for res in results:
                name = names_by_id.get(str(res.get("tool_use_id", "")))
                if name and not res.get("is_error"):
                    succeeded.add(name)
            if not results and blocks_text(message.get("content")).strip():
                user_turns += 1

    last = messages[-1] if messages else {"role": "user", "content": ""}
    last_blocks = _blocks(last.get("content"))
    last_results = [b for b in last_blocks if b.get("type") == "tool_result"]
    kind: TurnKind
    if last.get("role") != "user":
        kind = "other"
    elif last_results:
        kind = "tool_result"
    else:
        kind = "user_text"
    user_text = ""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = blocks_text(message.get("content"))
        if text.strip():
            user_text = text
            break
    tools = [str(t.get("name", "")) for t in body.get("tools") or [] if isinstance(t, dict)]
    return TurnView(
        last_kind=kind,
        user_text=user_text.strip(),
        tool_results=[
            ToolResult(name=names_by_id.get(str(r.get("tool_use_id", "")), ""), is_error=bool(r.get("is_error")))
            for r in last_results
        ],
        tools_offered=tools,
        history_calls=history,
        succeeded_tools=succeeded,
        user_turns=user_turns,
        model=full_model(str(body.get("model", ""))),
    )


def tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    return [
        ToolCall(
            id=str(b.get("id", "")),
            name=str(b.get("name", "")),
            input=_input(b),
        )
        for b in _blocks(message.get("content"))
        if b.get("type") == "tool_use"
    ]


# --------------------------------------------------------------------------------------------- matching


def match_turn(m: TurnMatch, view: TurnView) -> bool:
    if m.last_message != "any" and view.last_kind != m.last_message:
        return False
    if m.tool_results and not any(
        tool_matches(pattern, r.name) for r in view.tool_results for pattern in m.tool_results
    ):
        return False
    text = view.user_text
    if m.min_chars is not None and len(text) < m.min_chars:
        return False
    if m.max_chars is not None and len(text) > m.max_chars:
        return False
    if m.text_patterns and not any(re.search(p, text, re.IGNORECASE) for p in m.text_patterns):
        return False
    if m.text_excludes and any(re.search(p, text, re.IGNORECASE) for p in m.text_excludes):
        return False
    return not (m.first_turn is not None and view.first_turn != m.first_turn)


def arg_value(args: dict[str, Any], path: str) -> Any:
    current: Any = args
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        raw = value.strip().replace("€", "").replace("$", "").replace(" ", "")
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif "," in raw:
            raw = raw.replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def constraint_holds(c: ArgConstraint, args: dict[str, Any]) -> bool:
    """Whether the call's arguments satisfy ``c``. A missing argument satisfies only ``missing``."""
    value = arg_value(args, c.arg)
    if c.op == "exists":
        return value is not _MISSING and value is not None
    if c.op == "missing":
        return value is _MISSING or value is None
    if value is _MISSING:
        return False
    if c.op in ("<", "<=", ">", ">="):
        left = _number(value)
        right = _number(c.value)
        if left is None or right is None:
            return False
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[c.op]
    if c.op in ("==", "!="):
        left_n, right_n = _number(value), _number(c.value)
        equal = left_n == right_n if left_n is not None and right_n is not None else value == c.value
        return equal if c.op == "==" else not equal
    if c.op in ("in", "not_in"):
        options = c.value if isinstance(c.value, list) else []
        inside = value in options or str(value) in [str(o) for o in options]
        return inside if c.op == "in" else not inside
    if c.op == "contains":
        if isinstance(value, list):
            return c.value in value
        return str(c.value).lower() in str(value).lower()
    if c.op == "matches":
        return re.search(str(c.value), str(value), re.IGNORECASE) is not None
    return False


def constraints_hold(constraints: list[ArgConstraint], args: dict[str, Any]) -> bool:
    return all(constraint_holds(c, args) for c in constraints)


def missing_facts(requires: list[str], facts: set[str]) -> list[str]:
    return [f for f in requires if f not in facts]


# ------------------------------------------------------------------------------------------ tool verdicts


@dataclass(slots=True)
class PolicyVerdict:
    policy_id: str
    verdict: Verdict
    reason: str  # constraints | requires | approval_required | gated | approved | allowed | not_applicable
    message: str | None = None
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"policy": self.policy_id, "verdict": self.verdict, "reason": self.reason}
        if self.missing:
            out["missing"] = self.missing
        return out


def policy_tool_verdict(policy: Policy, call: ToolCall, facts: set[str], *, gated: bool) -> PolicyVerdict:
    """Verdict of one tool policy whose trigger (match/condition) already holds for ``call``."""
    action = policy.tool_action
    assert action is not None
    missing = missing_facts(policy.requires, facts)
    if missing:
        return PolicyVerdict(policy.id, "deny", "requires", action.message, missing)
    holds = constraints_hold(action.constraints, call.input)
    if action.action == "deny":
        return PolicyVerdict(
            policy.id, "deny" if holds else "pass", "constraints" if holds else "not_applicable", action.message
        )
    if action.action == "allow":
        return PolicyVerdict(
            policy.id, "allow" if holds else "deny", "allowed" if holds else "constraints", action.message
        )
    if not holds:
        return PolicyVerdict(policy.id, "pass", "not_applicable", action.message)
    if gated:
        return PolicyVerdict(policy.id, "approval", "gated", action.message)
    if f"approval:{call.name}" in facts:
        return PolicyVerdict(policy.id, "approval", "approved", action.message)
    return PolicyVerdict(policy.id, "deny", "approval_required", action.message)


def combine_tool_verdicts(verdicts: list[PolicyVerdict]) -> Verdict:
    """Any deny blocks the call; otherwise approval > allow > pass (no policy decided)."""
    kinds = {v.verdict for v in verdicts}
    for kind in ("deny", "approval", "allow"):
        if kind in kinds:
            return kind  # type: ignore[return-value]
    return "pass"


def block_explanation(call: ToolCall, verdict: PolicyVerdict) -> str:
    if verdict.message:
        return verdict.message
    if verdict.reason == "requires":
        return (
            f"No puedo ejecutar «{call.name}» todavía: la política «{verdict.policy_id}» exige antes "
            + ", ".join(f"«{m}»" for m in verdict.missing)
            + "."
        )
    if verdict.reason == "approval_required":
        return (
            f"No puedo ejecutar «{call.name}» sin aprobación humana (política «{verdict.policy_id}»). "
            "Hay que solicitarla por el circuito de aprobación."
        )
    return f"No puedo ejecutar «{call.name}» con estos datos: lo impide la política «{verdict.policy_id}»."


# ----------------------------------------------------------------------------------------------- votes


def required_yes(confirmation: Confirmation, votes: int = VOTES_PER_CONDITION) -> int:
    return {"none": 1, "majority": votes // 2 + 1, "unanimous": votes}[confirmation]


def combine_votes(votes: list[bool | None], confirmation: Confirmation) -> bool:
    """Abstentions (invalid or failed votes) count as "no", so a policy never holds on missing evidence."""
    yes = sum(1 for v in votes if v is True)
    return yes >= required_yes(confirmation, max(len(votes), VOTES_PER_CONDITION))


def parse_json_text(text: str) -> Any:
    raw = _FENCE.sub("", text.strip())
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
        if not starts:
            raise
        start = min(starts)
        end = max(raw.rfind("}"), raw.rfind("]"))
        return json.loads(raw[start : end + 1])


def parse_verdict(text: str) -> bool | None:
    """Strict verdict ``{"match": true|false, ...}``; anything else is an abstention."""
    try:
        data = parse_json_text(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("match"), bool):
        return bool(data["match"])
    return None


# ----------------------------------------------------------------------------------------- output schema


def validate_output(schema: dict[str, Any], text: str) -> tuple[bool, list[str]]:
    """Validate a final answer against the playbook's JSON Schema (the text must be JSON)."""
    try:
        data = parse_json_text(text)
    except (json.JSONDecodeError, ValueError):
        return False, ["La respuesta no es JSON válido"]
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
    messages = [f"{'/'.join(str(p) for p in e.path) or '(raíz)'}: {e.message}" for e in errors[:10]]
    return not messages, messages
