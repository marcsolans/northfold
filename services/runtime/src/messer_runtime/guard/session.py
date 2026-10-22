"""One Guard session per model call: decide the turn before the call, enforce the playbook after it.

``before``
    Reads the request (last message kind, user text, tool results), loads the conversation's facts and picks the
    first enabled *turn policy* whose ``match`` holds, whose ``requires`` facts hold and whose ``condition`` (if
    any) wins the vote. The policy routes the call to the small or large model, or answers with its fixed
    ``response`` without calling a model. No match: the call keeps the agent's model (off the declared path).

``after``
    Every ``tool_use`` of the model's message is judged by the *tool policies* of that tool (structural match,
    lazy semantic vote that sees the proposed call, ``requires``, argument constraints, action). Any deny wins:
    the call is removed from the message and replaced by a text block explaining the block, so the engine never
    executes it (``status: blocked``). ``require_approval`` keeps the call only when the tool is approval-gated in
    the agent — the engine then pauses the run for a human — or when a human already approved it in this
    conversation; otherwise it is blocked like a deny. Final answers are validated against ``output_schema``
    (one re-ask with the validation errors; still invalid → ``status: invalid_output``).

Each call leaves one decision (→ one ``guard`` span) with the policy, routed model, votes, facts and the
per-call numbers the metrics aggregate: call tokens, cost at the routed model, cost at the agent's own model (the
same call without Guard) and Guard's own overhead (votes, re-asks).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from messer_common.guard import (
    Playbook,
    Policy,
    PolicyVerdict,
    ToolCall,
    TurnView,
    combine_tool_verdicts,
    match_turn,
    policy_tool_verdict,
    read_turn,
    tool_calls,
    validate_output,
)
from messer_common.guard.evaluator import block_explanation, blocks_text, full_model, missing_facts
from messer_common.logging import get_logger
from messer_common.models_config import bedrock_model_id, request_defaults

from .. import gateway, guard_bridge
from ..gateway import CallContext
from ..guard_bridge import BeforeOutcome
from . import facts as facts_store
from . import votes
from .costs import has_price, price_usage
from .loader import GuardTarget

log = get_logger("messer.runtime.guard")

PREVIEW_CHARS = 500
FALLTHROUGH = "fallthrough"
REASK_PROMPT = (
    "Tu respuesta anterior no cumple el formato de salida obligatorio (JSON Schema). Errores:\n{errors}\n\n"
    "Responde de nuevo únicamente con un JSON válido que cumpla este esquema:\n{schema}"
)


@dataclass(slots=True)
class JudgedCall:
    call: ToolCall
    final: str  # allow | deny | approval | pass
    verdicts: list[PolicyVerdict] = field(default_factory=list)
    explanation: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.call.id,
            "tool": self.call.name,
            "input": self.call.input,
            "verdict": self.final,
            "policies": [v.as_dict() for v in self.verdicts],
        }
        if self.explanation:
            out["explanation"] = self.explanation
        return out


def _blocking_policy(judged: JudgedCall) -> str:
    return next((v.policy_id for v in judged.verdicts if v.verdict == "deny"), "guard")


def _bare(model: str) -> str:
    return model.split("/", 1)[1] if model.startswith("anthropic/") else model


def _merge_text(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for block in blocks:
        if block.get("type") == "text" and out and out[-1].get("type") == "text" and set(out[-1]) == {"type", "text"}:
            joined = "\n\n".join(t for t in (str(out[-1].get("text", "")).strip(), str(block.get("text", ""))) if t)
            out[-1] = {"type": "text", "text": joined}
        else:
            out.append(block)
    return out


def deterministic_message(model: str, text: str) -> dict[str, Any]:
    return {
        "id": f"msg_guard_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": text}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


class GuardSession:
    def __init__(self, ctx: CallContext, target: GuardTarget, info: dict[str, Any]) -> None:
        self.ctx = ctx
        self.target = target
        self.info = info
        self.playbook: Playbook = target.playbook
        self.started_ms = int(time.time() * 1000)
        self.started = time.monotonic()
        self.overhead_s = 0.0
        self.requested_model = ""
        self.routed_model = ""
        self.route = "default"
        self.route_refused: str | None = None
        self.view: TurnView | None = None
        self.facts: set[str] = set()
        self.turn_policy: Policy | None = None
        self.vote_outcomes: list[votes.VoteOutcome] = []
        self.overhead_cost = Decimal("0")
        self.overhead_in = 0
        self.overhead_out = 0
        self.errors: list[str] = []
        self.demo = votes.demo_only(info)

    @property
    def run_id(self) -> str:
        assert self.ctx.run_id is not None
        return self.ctx.run_id

    # ------------------------------------------------------------------------------------------- before

    async def before(self, body: dict[str, Any]) -> BeforeOutcome:
        t0 = time.monotonic()
        self.requested_model = full_model(str(body.get("model", "")))
        self.routed_model = self.requested_model
        try:
            self.view = read_turn(body)
            self.facts = await facts_store.load(self.run_id, self.ctx.org_id) | self.view.builtin_facts()
            self.turn_policy = await self._select_turn_policy(body)
            policy = self.turn_policy
            if policy is not None and policy.response:
                message = deterministic_message(str(body.get("model", "")), policy.response)
                self.route = "answer"
                self.overhead_s += time.monotonic() - t0
                await self._record(body=body, message=message, judged=[], schema=None, action="answer")
                return BeforeOutcome(body=body, message=message, meta={"guard_policy": policy.id})
            if policy is not None and policy.model is not None:
                target_model = self.playbook.model_for(policy.model)
                refusal = self._route_refusal(target_model)
                if refusal is None:
                    self.route = policy.model
                    self.routed_model = target_model
                    routed = self._routed_body(body, target_model)
                    self.overhead_s += time.monotonic() - t0
                    return BeforeOutcome(body=routed, model=target_model, meta={"guard_policy": policy.id})
                self.route_refused = refusal
        except Exception as exc:
            log.exception("guard.before_failed", run_id=self.ctx.run_id)
            self.errors.append(f"before: {type(exc).__name__}: {exc}"[:300])
        self.overhead_s += time.monotonic() - t0
        return BeforeOutcome(body=body)

    async def _select_turn_policy(self, body: dict[str, Any]) -> Policy | None:
        assert self.view is not None
        for policy in self.playbook.turn_policies():
            if not match_turn(policy.match, self.view):
                continue
            if missing_facts(policy.requires, self.facts):
                continue
            if policy.condition:
                outcome = await self._vote(policy, body, None)
                if not outcome.matched:
                    continue
            return policy
        return None

    async def _vote(self, policy: Policy, body: dict[str, Any], call: ToolCall | None) -> votes.VoteOutcome:
        assert self.view is not None
        outcome = await votes.decide(
            self.ctx,
            self.info,
            small_model=self.playbook.small_model,
            policy=policy,
            view=self.view,
            body=body,
            call=call,
        )
        self.vote_outcomes.append(outcome)
        self.overhead_cost += outcome.cost_usd
        self.overhead_in += outcome.input_tokens
        self.overhead_out += outcome.output_tokens
        return outcome

    def _route_refusal(self, model: str) -> str | None:
        if not gateway._policy_allows(self.info.get("policy") or {}, model):
            return "model_policy"
        if self.info.get("residency") == "eu_strict" and bedrock_model_id(model) is None:
            return "residency"
        return None

    def _routed_body(self, body: dict[str, Any], model: str) -> dict[str, Any]:
        routed = dict(body)
        routed["model"] = _bare(model)
        # The gateway filled output_config with the requested model's defaults; use the routed model's instead.
        requested_effort = request_defaults(self.requested_model).get("effort")
        config = routed.get("output_config")
        if isinstance(config, dict) and requested_effort and config == {"effort": requested_effort}:
            effort = request_defaults(model).get("effort")
            if effort:
                routed["output_config"] = {"effort": effort}
            else:
                routed.pop("output_config", None)
        return routed

    # -------------------------------------------------------------------------------------------- after

    async def after(self, body: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        t0 = time.monotonic()
        judged: list[JudgedCall] = []
        schema_report: dict[str, Any] | None = None
        try:
            if self.view is None:
                self.view = read_turn(body)
                self.facts = self.facts | self.view.builtin_facts()
            judged = [await self._judge(call, body) for call in tool_calls(message)]
            blocked = {j.call.id: j for j in judged if j.final == "deny"}
            if blocked:
                message = self._strip(message, blocked)
            if self.playbook.output_schema and not tool_calls(message):
                message, schema_report = await self._enforce_schema(body, message)
        except Exception as exc:
            log.exception("guard.after_failed", run_id=self.ctx.run_id)
            self.errors.append(f"after: {type(exc).__name__}: {exc}"[:300])
            message, judged = self._fail_closed(message)
        action = "block" if any(j.final == "deny" for j in judged) else None
        self.overhead_s += time.monotonic() - t0
        try:
            await self._record(body=body, message=message, judged=judged, schema=schema_report, action=action)
        except Exception:
            log.exception("guard.record_failed", run_id=self.ctx.run_id)
        return message

    async def _judge(self, call: ToolCall, body: dict[str, Any]) -> JudgedCall:
        assert self.view is not None
        verdicts: list[PolicyVerdict] = []
        for policy in self.playbook.tool_policies(call.name):
            if not match_turn(policy.match, self.view):
                continue
            if policy.condition:
                outcome = await self._vote(policy, body, call)
                if not outcome.matched:
                    continue
            verdicts.append(policy_tool_verdict(policy, call, self.facts, gated=self.target.gated(call.name)))
        judged = JudgedCall(call=call, final=combine_tool_verdicts(verdicts), verdicts=verdicts)
        if judged.final == "deny":
            first = next(v for v in verdicts if v.verdict == "deny")
            judged.explanation = block_explanation(call, first)
        return judged

    def _strip(self, message: dict[str, Any], blocked: dict[str, JudgedCall]) -> dict[str, Any]:
        """Replace blocked tool calls by their explanation. The turn is modified, so its thinking blocks (bound to
        the original output) are dropped rather than replayed against content they no longer match."""
        content: list[dict[str, Any]] = []
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") in ("thinking", "redacted_thinking"):
                continue
            if block.get("type") == "tool_use" and str(block.get("id", "")) in blocked:
                content.append({"type": "text", "text": blocked[str(block["id"])].explanation or ""})
            else:
                content.append(block)
        stop_reason = message.get("stop_reason")
        if not any(b.get("type") == "tool_use" for b in content):
            stop_reason = "end_turn"
        return {**message, "content": _merge_text(content), "stop_reason": stop_reason}

    def _fail_closed(self, message: dict[str, Any]) -> tuple[dict[str, Any], list[JudgedCall]]:
        """Evaluation failed: block the calls of tools that some policy restricts; let the others through."""
        judged: list[JudgedCall] = []
        blocked: dict[str, JudgedCall] = {}
        for call in tool_calls(message):
            restricted = any(
                p.tool_action is not None and p.tool_action.action in ("deny", "require_approval")
                for p in self.playbook.tool_policies(call.name)
            )
            j = JudgedCall(call=call, final="deny" if restricted else "pass")
            if restricted:
                j.explanation = (
                    f"No puedo ejecutar «{call.name}» ahora mismo: Guard no ha podido comprobar el playbook. "
                    "Inténtalo de nuevo en unos minutos."
                )
                blocked[call.id] = j
            judged.append(j)
        return (self._strip(message, blocked) if blocked else message), judged

    async def _enforce_schema(
        self, body: dict[str, Any], message: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        schema = self.playbook.output_schema
        assert schema is not None
        text = blocks_text(message.get("content"))
        ok, errors = validate_output(schema, text)
        report: dict[str, Any] = {"valid": ok, "errors": errors, "reasked": False}
        if ok or message.get("stop_reason") == "max_tokens":
            return message, report
        reask = {
            **body,
            "stream": False,
            "messages": [
                *(body.get("messages") or []),
                {"role": "assistant", "content": message.get("content") or []},
                {
                    "role": "user",
                    "content": REASK_PROMPT.format(
                        errors="\n".join(f"- {e}" for e in errors), schema=json.dumps(schema, ensure_ascii=False)
                    ),
                },
            ],
        }
        response = await gateway._call(
            reask, self.routed_model, self.ctx, self.info, {"anthropic-version": "2023-06-01"}, streaming=False
        )
        report["reasked"] = True
        if response.status_code != 200:
            report["reask_error"] = response.status_code
            return message, report
        retried = json.loads(bytes(response.body))
        usage = dict(retried.get("usage") or {})
        self.overhead_in += int(usage.get("input_tokens") or 0)
        self.overhead_out += int(usage.get("output_tokens") or 0)
        self.overhead_cost += await price_usage(self.routed_model, usage)
        ok, errors = validate_output(schema, blocks_text(retried.get("content")))
        report.update({"valid": ok, "errors_after_reask": errors})
        if tool_calls(retried):
            return message, report  # a re-ask may not start new actions; keep the original answer
        return retried, report

    # ------------------------------------------------------------------------------------------- record

    async def _record(
        self,
        *,
        body: dict[str, Any],
        message: dict[str, Any],
        judged: list[JudgedCall],
        schema: dict[str, Any] | None,
        action: str | None,
    ) -> None:
        view = self.view or read_turn(body)
        blocked = [j for j in judged if j.final == "deny"]
        provided: set[str] = set()
        if self.turn_policy is not None:
            provided.update(self.turn_policy.provides)
        policies = {p.id: p for p in self.playbook.policies}
        for j in judged:
            if j.final == "deny":
                continue
            for v in j.verdicts:
                if v.verdict != "deny" and v.policy_id in policies:
                    provided.update(policies[v.policy_id].provides)
        all_facts = self.facts | provided | view.builtin_facts()
        await facts_store.add(self.run_id, provided)

        triggered = [v.policy_id for j in judged for v in j.verdicts]
        matched = ([self.turn_policy.id] if self.turn_policy else []) + list(dict.fromkeys(triggered))
        on_path = bool(matched)
        if blocked:
            name = _blocking_policy(blocked[0])
        elif self.turn_policy is not None:
            name = self.turn_policy.id
        elif triggered:
            name = triggered[0]
        else:
            name = FALLTHROUGH

        if self.errors:
            status = "error"
        elif blocked:
            status = "blocked"
        elif schema is not None and not schema.get("valid"):
            status = "invalid_output"
        else:
            status = "success"
        if action is None:
            if schema is not None and schema.get("reasked"):
                action = "repair"
            elif self.route in ("small", "large"):
                action = "route"
            elif judged:
                action = "allow"
            else:
                action = "pass"

        usage = dict(message.get("usage") or {})
        call_in = int(usage.get("input_tokens") or 0)
        call_out = int(usage.get("output_tokens") or 0)
        if self.route == "answer":
            priced = Decimal("0")
        else:
            priced = await price_usage(self.routed_model, usage)
        baseline_model = self.requested_model if await has_price(self.requested_model) else self.playbook.large_model
        baseline = await price_usage(baseline_model, usage)
        overhead = self.overhead_cost
        decision: dict[str, Any] = {
            "t": self.started_ms,
            "kind": "turn",
            "policy": name,
            "action": action,
            "status": status,
            "model": None if self.route == "answer" else self.routed_model,
            "input": {
                "turn": view.last_kind,
                "text": view.user_text[:PREVIEW_CHARS],
                "tool_results": [{"tool": r.name, "is_error": r.is_error} for r in view.tool_results],
                "requested_model": self.requested_model,
            },
            "output": {
                "route": self.route,
                "model": None if self.route == "answer" else self.routed_model,
                "text": blocks_text(message.get("content"))[:PREVIEW_CHARS],
                "tool_calls": [j.as_dict() for j in judged],
                **({"schema": schema} if schema is not None else {}),
            },
            "input_tokens": self.overhead_in,
            "output_tokens": self.overhead_out,
            "cost_usd": str(overhead),
            "latency_ms": int((time.monotonic() - self.started) * 1000),
            "overhead_ms": int(self.overhead_s * 1000),
            "member": self.target.member,
            "requested_model": self.requested_model,
            "routed_model": None if self.route == "answer" else self.routed_model,
            "route": self.route,
            "on_path": on_path,
            "matched_policies": matched,
            "votes": [v.as_dict() for v in self.vote_outcomes],
            "facts": sorted(all_facts),
            "provided": sorted(provided),
            "blocked_count": len(blocked),
            "blocked": [
                {"tool": j.call.name, "policy": _blocking_policy(j), "explanation": j.explanation} for j in blocked
            ],
            "call_input_tokens": call_in,
            "call_output_tokens": call_out,
            "priced_cost_usd": str(priced),
            "baseline_cost_usd": str(baseline),
            "baseline_model": baseline_model,
            "guarded_cost_usd": str(priced + overhead),
            "overhead_cost_usd": str(overhead),
            "demo": self.demo,
        }
        if self.route_refused:
            decision["route_refused"] = self.route_refused
        if self.errors:
            decision["errors"] = self.errors
        await guard_bridge.record_decision(self.ctx.run_id, decision)
