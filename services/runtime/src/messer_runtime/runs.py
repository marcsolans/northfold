"""Run orchestration: sandbox execution, streaming, finalization (trace, spans, cost, credits, approvals)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from messer_common import credits
from messer_common.db import system_session
from messer_common.db.base import new_id
from messer_common.db.models import Approval, Conversation, Membership, Notification, Run, Secret, Workforce
from messer_common.events import get_redis, publish
from messer_common.logging import get_logger
from messer_common.pricing import usd_to_credits
from messer_common.queue import Jobs, enqueue
from messer_common.security import DecryptionError, decrypt
from messer_common.settings import get_settings

from .code_cache import ensure_checkout
from .gateway import CallContext, GatewayRefusal, check_spend
from .persistence import gateway_totals, now, persist_spans, to_uuid
from .sandbox.manager import SandboxPool

log = get_logger("messer.runtime.runs")

APPROVAL_TTL = timedelta(hours=72)
ROLE_RANK = {"viewer": 1, "builder": 2, "admin": 3, "owner": 4}
_trace_events: dict[str, asyncio.Event] = {}


class RunRequest(BaseModel):
    org_id: uuid.UUID
    project_id: uuid.UUID
    workforce: str
    ref: str = "HEAD"
    input: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    parent_run_id: str | None = None
    resume: dict[str, Any] | None = None
    environment: str = "development"
    environment_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None
    channel: str = "studio"
    user_id: uuid.UUID | None = None
    external_user_id: str | None = None
    conversation_id: uuid.UUID | None = None
    trigger_id: uuid.UUID | None = None
    rerun_of: uuid.UUID | None = None


def trace_stored(run_id: str) -> None:
    _trace_events.setdefault(run_id, asyncio.Event()).set()


async def _wait_trace(run_id: str, wait_s: float) -> None:
    event = _trace_events.setdefault(run_id, asyncio.Event())
    try:
        await asyncio.wait_for(event.wait(), timeout=wait_s)
    except TimeoutError:
        log.warning("run.trace_missing", run_id=run_id)
    finally:
        _trace_events.pop(run_id, None)


async def _project_secrets(project_id: uuid.UUID) -> dict[str, str]:
    async with system_session() as s:
        rows = (await s.execute(select(Secret).where(Secret.project_id == project_id))).scalars().all()
    out: dict[str, str] = {}
    for row in rows:
        try:
            out[row.name] = decrypt(row.encrypted_value)
        except DecryptionError:
            log.error("run.secret_undecryptable", project=str(project_id), name=row.name)
    return out


async def _parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    event = "message"
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                try:
                    yield event, json.loads("\n".join(data))
                except json.JSONDecodeError:
                    pass
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())


def _status_from_output(output: dict[str, Any] | None, error: dict[str, Any] | None) -> str:
    if error is not None and output is None:
        return "error"
    if output is None:
        return "error"
    status = output.get("status") or {}
    code = status.get("code", "success")
    reason = status.get("reason")
    if code == "success":
        return "success"
    if code == "cancelled" and reason in ("approval_required", "input_required"):
        return "paused"
    if code in ("blocked", "timeout", "cancelled"):
        return code
    return "error"


def _text_of(output: Any) -> str:
    if isinstance(output, dict):
        content = output.get("content")
        if isinstance(content, list):
            return "".join(str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text")
        if "text" in output:
            return str(output["text"])
    if isinstance(output, str):
        return output
    return ""


def _prompt_parts(prompt: Any) -> tuple[str, list[str]]:
    """Text and attachment names of an agent prompt (a string or a user message with content blocks)."""
    if isinstance(prompt, str):
        return prompt, []
    if isinstance(prompt, dict):
        raw = prompt.get("content")
        blocks: list[Any] = raw if isinstance(raw, list) else []
        names = [str(b.get("name") or "archivo") for b in blocks if isinstance(b, dict) and b.get("type") == "file"]
        return _text_of(prompt), names
    return "", []


class RunExecutor:
    def __init__(self, pool: SandboxPool) -> None:
        self.pool = pool

    async def execute(self, req: RunRequest) -> AsyncIterator[dict[str, Any]]:
        run_id = req.run_id or new_id().hex
        run_uuid = to_uuid(run_id)
        started = time.monotonic()
        ctx = CallContext(org_id=req.org_id, project_id=req.project_id, run_id=run_id, environment=req.environment)

        async with system_session() as s:
            member = (
                await s.execute(
                    select(Workforce).where(Workforce.project_id == req.project_id, Workforce.name == req.workforce)
                )
            ).scalar_one_or_none()
        if member is None:
            yield {
                "type": "RUN_ERROR",
                "run_id": run_id,
                "error": {"type": "not_found", "message": f"«{req.workforce}» no existe"},
            }
            return
        root_kind = member.kind

        refusal: GatewayRefusal | None = None
        try:
            await check_spend(ctx)
        except GatewayRefusal as exc:
            refusal = exc

        try:
            commit, project_dir = await ensure_checkout(req.project_id, req.ref)
        except Exception as exc:
            yield {"type": "RUN_ERROR", "run_id": run_id, "error": {"type": "code_unavailable", "message": str(exc)}}
            return

        async with system_session() as s:
            run = Run(
                id=run_uuid,
                org_id=req.org_id,
                project_id=req.project_id,
                environment=req.environment,
                environment_id=req.environment_id,
                version_id=req.version_id,
                workforce_id=member.id,
                workforce_name=member.name,
                parent_run_id=to_uuid(req.parent_run_id) if req.parent_run_id else None,
                trigger_id=req.trigger_id,
                conversation_id=req.conversation_id,
                status="budget_exceeded" if refusal else "running",
                input=req.input,
                user_id=req.user_id,
                external_user_id=req.external_user_id,
                channel=req.channel,
                git_commit=commit,
                rerun_of=req.rerun_of,
                error={"type": refusal.error_type, "message": refusal.message} if refusal else None,
                ended_at=now() if refusal else None,
            )
            await s.merge(run)
        yield {"type": "RUN_STARTED", "run_id": run_id, "commit": commit, "workforce": member.name, "kind": root_kind}
        if refusal is not None:
            yield {
                "type": "RUN_FINISHED",
                "run_id": run_id,
                "status": "budget_exceeded",
                "error": {"type": refusal.error_type, "message": refusal.message},
                "cost_usd": "0",
                "credits": "0",
                "approvals": [],
            }
            return

        approvals: list[dict[str, Any]] = []
        final_output: dict[str, Any] | None = None
        sandbox_error: dict[str, Any] | None = None
        secrets = await _project_secrets(req.project_id)
        try:
            sbx = await self.pool.get(
                org_id=req.org_id,
                project_id=req.project_id,
                commit=commit,
                project_dir=project_dir,
                secrets=secrets,
                environment=req.environment,
            )
            async with self.pool.lease(sbx), sbx.client(timeout=None) as client:
                payload = {"run_id": run_id, "parent_id": req.parent_run_id, "input": req.input, "resume": req.resume}
                async with asyncio.timeout(get_settings().runtime_run_timeout_s):
                    async with client.stream("POST", f"/members/{member.name}/stream", json=payload) as resp:
                        if resp.status_code != 200:
                            sandbox_error = {"type": "sandbox_http", "message": (await resp.aread()).decode()[:2000]}
                        else:
                            async for event_name, data in _parse_sse(resp.aiter_lines()):
                                if event_name == "sandbox_error":
                                    sandbox_error = data
                                    yield {"type": "RUN_ERROR", "run_id": run_id, "error": data}
                                    continue
                                if data.get("type") == "APPROVAL":
                                    approvals.append(data)
                                if data.get("type") == "OUTPUT" and data.get("parent_call_id") is None:
                                    final_output = data
                                yield data
        except TimeoutError:
            sandbox_error = {"type": "timeout", "message": "La ejecución superó el tiempo máximo"}
            yield {"type": "RUN_ERROR", "run_id": run_id, "error": sandbox_error}
        except Exception as exc:
            sandbox_error = {"type": type(exc).__name__, "message": str(exc)[:2000]}
            yield {"type": "RUN_ERROR", "run_id": run_id, "error": sandbox_error}

        if final_output is not None or sandbox_error is None:
            await _wait_trace(run_id, wait_s=10)
        summary = await self.finalize(
            req=req,
            run_id=run_id,
            member=member,
            final_output=final_output,
            sandbox_error=sandbox_error,
            approvals=approvals,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        yield {"type": "RUN_FINISHED", **summary}

    async def finalize(
        self,
        *,
        req: RunRequest,
        run_id: str,
        member: Workforce,
        final_output: dict[str, Any] | None,
        sandbox_error: dict[str, Any] | None,
        approvals: list[dict[str, Any]],
        duration_ms: int,
    ) -> dict[str, Any]:
        cost, providers, calls, budget_flag = await gateway_totals(run_id)
        demo = providers == {"demo"}
        status = _status_from_output(final_output, sandbox_error)
        if sandbox_error and sandbox_error.get("type") == "timeout":
            status = "timeout"
        if budget_flag:
            status = "budget_exceeded"
        approval_rows: list[dict[str, Any]] = []
        async with system_session() as s:
            run = await s.get(Run, to_uuid(run_id))
            assert run is not None
            span_cost = Decimal("0")
            models: list[str] = []
            if run.trace:
                span_cost, models = await persist_spans(s, run=run, trace=run.trace, root_kind=member.kind, demo=demo)
            total_cost = cost if cost > 0 else span_cost
            run_credits = usd_to_credits(total_cost) if total_cost > 0 else Decimal("0")
            run.status = status
            run.output = final_output.get("output") if final_output else None
            run.error = (final_output or {}).get("error") or (
                {"type": "budget_exceeded", "message": budget_flag} if budget_flag else sandbox_error
            )
            run.usage = (final_output or {}).get("usage") or {}
            run.models = [{"model": m, "providers": sorted(providers)} for m in models] or (
                [{"model": c["model"], "providers": [c["provider"]]} for c in calls[:1]]
            )
            run.cost_usd = total_cost
            run.credits = run_credits
            run.duration_ms = duration_ms
            run.ended_at = now()
            if run_credits > 0:
                await credits.charge_usage(
                    s,
                    org_id=run.org_id,
                    run_id=run.id,
                    project_id=run.project_id,
                    cost_usd=total_cost,
                    credits=run_credits,
                    note=f"{member.name} · {run.channel}",
                )
            if status == "paused" and approvals:
                approval_rows = await self._create_approvals(s, run=run, member=member, approvals=approvals, req=req)
            if req.conversation_id:
                conv = await s.get(Conversation, req.conversation_id)
                if conv is not None:
                    conv.last_run_id = run.id
                    messages = list(conv.messages or [])
                    prompt_text, attachments = _prompt_parts(req.input.get("prompt"))
                    if (prompt_text or attachments) and not req.resume:
                        entry: dict[str, Any] = {
                            "role": "user",
                            "text": prompt_text,
                            "run_id": run_id,
                            "at": now().isoformat(),
                        }
                        if attachments:
                            entry["attachments"] = attachments
                        messages.append(entry)
                    text = _text_of(run.output)
                    if text:
                        messages.append(
                            {
                                "role": "assistant",
                                "text": text,
                                "run_id": run_id,
                                "model": models[0] if models else None,
                                "at": now().isoformat(),
                            }
                        )
                    conv.messages = messages[-500:]
        if run_credits > 0:
            async with system_session() as s:
                await credits.maybe_auto_topup(s, req.org_id)
        for row in approval_rows:
            await enqueue(Jobs.NOTIFY_APPROVAL, row["id"])
        await get_redis().delete(f"gw:spend_ok:{req.org_id}:{req.project_id}")
        summary = {
            "run_id": run_id,
            "status": status,
            "cost_usd": str(total_cost),
            "credits": str(run_credits),
            "duration_ms": duration_ms,
            "demo": demo,
            "providers": sorted(providers),
            "approvals": approval_rows,
            "error": run.error if status not in ("success", "paused") else None,
        }
        await publish(f"run:{run_id}", {"type": "run_finished", **summary})
        if req.conversation_id:
            await publish(f"conversation:{req.conversation_id}", {"type": "run_finished", **summary})
        return summary

    async def _create_approvals(
        self, s: Any, *, run: Run, member: Workforce, approvals: list[dict[str, Any]], req: RunRequest
    ) -> list[dict[str, Any]]:
        tools_cfg = {str(t.get("name") or t.get("key")): t for t in (member.config_json or {}).get("tools", [])}
        prompt, _ = _prompt_parts(req.input.get("prompt"))
        rows: list[dict[str, Any]] = []
        for event in approvals:
            tool_name = str(event.get("runnable_name") or event.get("path", "").rsplit(".", 1)[-1])
            cfg = tools_cfg.get(tool_name) or next(
                (t for t in tools_cfg.values() if str(t.get("key", "")).replace(".", "_") == tool_name), {}
            )
            role = str(cfg.get("approver_role") or "admin")
            approval = Approval(
                org_id=run.org_id,
                project_id=run.project_id,
                run_id=run.id,
                span_id=event.get("call_id"),
                engine_approval_id=str(event["approval_id"]),
                workforce_name=member.name,
                tool_name=tool_name,
                title=str(event.get("prompt") or f"{member.name} quiere ejecutar {tool_name}"),
                payload=event.get("input") or {},
                input_schema=event.get("input_schema"),
                context_summary=(prompt or "")[:2000],
                assigned_role=role,
                environment=run.environment,
                expires_at=now() + APPROVAL_TTL,
                channel_context={
                    "channel": run.channel,
                    "conversation_id": str(req.conversation_id) if req.conversation_id else None,
                    "external_user_id": req.external_user_id,
                    "tool_call_id": event.get("tool_call_id"),
                    "input": req.input,
                },
            )
            s.add(approval)
            await s.flush()
            members = (await s.execute(select(Membership).where(Membership.org_id == run.org_id))).scalars().all()
            for m in members:
                if ROLE_RANK.get(m.role, 0) >= ROLE_RANK.get(role, 3):
                    s.add(
                        Notification(
                            org_id=run.org_id,
                            user_id=m.user_id,
                            kind="approval_requested",
                            payload={
                                "title": approval.title,
                                "body": f"{member.name} · {tool_name}",
                                "url": f"/app/approvals?id={approval.id}",
                                "approval_id": str(approval.id),
                            },
                        )
                    )
            rows.append(
                {
                    "id": str(approval.id),
                    "engine_approval_id": approval.engine_approval_id,
                    "tool_name": tool_name,
                    "title": approval.title,
                    "payload": approval.payload,
                    "assigned_role": role,
                    "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
                }
            )
            await publish(f"org:{run.org_id}", {"type": "approval_requested", "approval_id": str(approval.id)})
        return rows
