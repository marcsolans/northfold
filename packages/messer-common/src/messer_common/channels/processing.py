"""Inbound processing and reply delivery for channels.

Flow for every provider message (webhook or simulator):

1. :func:`record_inbound` (API, synchronous with the webhook) stores the message once per provider id, attaches
   it to the conversation of its thread (created on first contact) and queues ``channel_inbound``.
2. :func:`process_inbound` (worker) runs the connected agent with the conversation's memory
   (``parent_run_id = conversations.last_run_id``) in the channel's environment, serialized per conversation.
3. :func:`deliver` sends the answer through the provider adapter (split per provider limits) or, for demo
   channels and simulated messages, stores it. A run that pauses for approval gets a "pending approval" notice;
   :func:`deliver_resumed_run` (called by the ``resume_run`` job) delivers the final answer after the decision.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from redis.exceptions import LockError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import billing_state, runtime_client
from ..db import system_session
from ..db.models import Channel, Conversation, Run, Workforce
from ..db.models.channels import ChannelMessage
from ..events import get_redis, publish
from ..execution import NotDeployed, resolve_target
from ..logging import get_logger
from ..queue import Jobs, enqueue
from ..runtime_client import RuntimeUnavailable
from ..settings import get_settings
from . import demo, get_adapter, is_channel_provider
from .base import ChannelAdapter, InboundMessage, ReplyTarget, SendError
from .context import channel_context
from .formatting import text_of
from .texts import NoticeKind, notice

log = get_logger("messer.channels.processing")

SEND_ATTEMPTS = 3
SEND_BACKOFF_S = (1.0, 3.0)
MAX_THREAD_MESSAGES = 500
RUN_NAMESPACE = uuid.UUID("6f1d3c52-8d0e-4c43-9a8b-2a3e0f4c9b71")


class RetryLater(Exception):
    """Transient failure (runtime unavailable, conversation busy): the worker retries the job later."""

    def __init__(self, message: str, defer_s: float = 10.0) -> None:
        super().__init__(message)
        self.defer_s = defer_s


@dataclass(slots=True)
class Recorded:
    message_id: uuid.UUID
    conversation_id: uuid.UUID | None
    new: bool


def now() -> datetime:
    return datetime.now(UTC)


def lock_ttl_s() -> int:
    return get_settings().runtime_run_timeout_s + 120


def run_id_for(message_id: uuid.UUID) -> uuid.UUID:
    """Deterministic run id per inbound message: a retried job never runs the agent twice."""
    return uuid.uuid5(RUN_NAMESPACE, f"channel-message:{message_id}")


def conversation_channel(conversation_id: uuid.UUID) -> str:
    return f"conversation:{conversation_id}"


async def publish_event(conversation_id: uuid.UUID | None, event: dict[str, Any]) -> None:
    """Live update for the inbox and the simulator (SSE on ``conversation:<id>``)."""
    if conversation_id is None:
        return
    try:
        await publish(conversation_channel(conversation_id), {**event, "conversation_id": str(conversation_id)})
    except Exception as exc:  # live updates are best effort; processing must not fail because of them
        log.warning("channel.publish_failed", conversation_id=str(conversation_id), error=str(exc))


@asynccontextmanager
async def conversation_lock(conversation_id: uuid.UUID) -> AsyncIterator[None]:
    """One run at a time per conversation, so every message continues from the previous answer."""
    ttl = lock_ttl_s()
    lock = get_redis().lock(f"lock:conversation:{conversation_id}", timeout=ttl, blocking_timeout=ttl)
    acquired = await lock.acquire()
    if not acquired:
        raise RetryLater("La conversación está ocupada", defer_s=15)
    try:
        yield
    finally:
        try:
            await lock.release()
        except LockError:
            log.warning("channel.lock_expired", conversation_id=str(conversation_id))


# ================================================================================================ recording


async def _thread_conversation(
    s: AsyncSession, channel: Channel, key: str, *, create: bool, member_name: str, title: str, thread_id: str | None
) -> Conversation | None:
    q = select(Conversation).where(
        Conversation.project_id == channel.project_id,
        Conversation.channel_key == str(channel.id),
        Conversation.external_user_id == key,
    )
    conv = (await s.execute(q.with_for_update())).scalar_one_or_none()
    if conv is None:
        if not create:
            return None
        await s.execute(
            pg_insert(Conversation)
            .values(
                id=uuid.uuid4(),
                org_id=channel.org_id,
                project_id=channel.project_id,
                channel_id=channel.id,
                channel_key=str(channel.id),
                provider=channel.provider,
                workforce_name=member_name,
                external_user_id=key,
                external_thread_id=thread_id,
                title=title[:80],
            )
            .on_conflict_do_nothing(constraint="uq_conversations_thread")
        )
        conv = (await s.execute(q.with_for_update())).scalar_one()
    if conv.status == "closed":
        conv.status = "open"  # a new message reopens the thread (memory continues)
    if not conv.title and title:
        conv.title = title[:80]
    if thread_id and not conv.external_thread_id:
        conv.external_thread_id = thread_id
    conv.updated_at = now()
    return conv


async def record_inbound(
    channel: Channel, messages: list[InboundMessage], *, simulated: bool = False, enqueue_jobs: bool = True
) -> list[Recorded]:
    """Store inbound messages once per provider id, attach them to their conversation and queue processing.

    Duplicates (provider retries, the same Slack post delivered as two events) are not stored again; if the
    original is still waiting it is queued again (the job id collapses duplicates in the queue).
    """
    recorded: list[Recorded] = []
    if not messages:
        return recorded
    async with system_session() as s:
        member = await s.get(Workforce, channel.workforce_id)
        member_name = member.name if member else ""
        for m in messages:
            existing = (
                await s.execute(
                    select(ChannelMessage).where(
                        ChannelMessage.channel_id == channel.id,
                        ChannelMessage.direction == "inbound",
                        ChannelMessage.external_id == m.external_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                if existing.status == "received":
                    recorded.append(Recorded(existing.id, existing.conversation_id, new=False))
                continue
            conv = await _thread_conversation(
                s,
                channel,
                m.conversation_key[:255],
                create=not m.requires_existing_conversation,
                member_name=member_name,
                title=m.text,
                thread_id=m.thread_id,
            )
            if conv is None:
                continue  # thread reply in a thread the agent is not part of
            row_id = (
                await s.execute(
                    pg_insert(ChannelMessage)
                    .values(
                        id=uuid.uuid4(),
                        org_id=channel.org_id,
                        project_id=channel.project_id,
                        channel_id=channel.id,
                        conversation_id=conv.id,
                        direction="inbound",
                        provider=channel.provider,
                        external_id=m.external_id[:255],
                        kind=m.kind,
                        sender_id=m.sender_id[:255] or None,
                        sender_name=(m.sender_name or "")[:255] or None,
                        text=m.text,
                        payload=m.payload(),
                        status="received",
                        simulated=simulated,
                    )
                    .on_conflict_do_nothing(constraint="uq_channel_messages_external")
                    .returning(ChannelMessage.id)
                )
            ).scalar_one_or_none()
            if row_id is not None:
                recorded.append(Recorded(row_id, conv.id, new=True))
    for item in recorded:
        if item.new:
            await publish_event(
                item.conversation_id,
                {"type": "channel_message", "direction": "inbound", "message_id": str(item.message_id)},
            )
        if enqueue_jobs:
            await enqueue_inbound(item.message_id)
    return recorded


async def enqueue_inbound(message_id: uuid.UUID) -> None:
    await enqueue(Jobs.CHANNEL_INBOUND, str(message_id), _job_id=f"channel-inbound:{message_id}")


# ================================================================================================ processing


@dataclass(slots=True)
class _Prepared:
    channel_id: uuid.UUID
    conversation_id: uuid.UUID
    request: dict[str, Any] | None
    existing: dict[str, Any] | None
    failure: tuple[str, str] | None  # (code, message) when the agent cannot run
    fallback_environment: str | None


async def process_inbound(message_id: uuid.UUID, *, final_attempt: bool = False) -> dict[str, Any]:
    """Run the connected agent for one inbound message and deliver its answer. Idempotent per message."""
    claimed = await _claim(message_id)
    if isinstance(claimed, dict):
        return claimed
    channel_id, conversation_id = claimed
    try:
        async with conversation_lock(conversation_id):
            prepared = await _prepare(message_id)
            if prepared.failure is not None:
                code, message = prepared.failure
                await _fail(message_id, code, message)
                delivery = await deliver(
                    channel_id, conversation_id, {"status": "error", "run_id": None}, inbound_id=message_id
                )
                return {"status": "failed", "error": code, "delivery": delivery}
            result = prepared.existing
            if result is None:
                assert prepared.request is not None
                await publish_event(conversation_id, {"type": "processing", "message_id": str(message_id)})
                result = await runtime_client.run(prepared.request)
            await _processed(message_id, result, prepared.fallback_environment)
            delivery = await deliver(channel_id, conversation_id, result, inbound_id=message_id)
    except RuntimeUnavailable as exc:
        if final_attempt:
            await _fail(message_id, "runtime_unavailable", "El entorno de ejecución no está disponible")
            await deliver(channel_id, conversation_id, {"status": "error", "run_id": None}, inbound_id=message_id)
            return {"status": "failed", "error": "runtime_unavailable"}
        await _release(message_id)
        raise RetryLater(str(exc), defer_s=15) from exc
    except RetryLater:
        await _release(message_id)
        raise
    log.info(
        "channel.processed",
        message_id=str(message_id),
        run_id=result.get("run_id"),
        status=result.get("status"),
        delivery=delivery.get("status"),
    )
    return {
        "status": "processed",
        "run_id": result.get("run_id"),
        "run_status": result.get("status"),
        "delivery": delivery,
    }


async def _claim(message_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID] | dict[str, Any]:
    async with system_session() as s:
        msg = (
            await s.execute(
                select(ChannelMessage)
                .where(ChannelMessage.id == message_id, ChannelMessage.direction == "inbound")
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if msg is None:
            return {"status": "skipped", "reason": "missing_or_locked"}
        stale = (
            msg.status == "processing"
            and msg.claimed_at is not None
            and msg.claimed_at < now() - timedelta(seconds=lock_ttl_s())
        )
        if msg.status != "received" and not stale:
            return {"status": "skipped", "reason": msg.status}
        channel = await s.get(Channel, msg.channel_id)
        if channel is None or channel.status == "disabled" or msg.conversation_id is None:
            msg.status = "ignored"
            msg.error_code = "channel_disabled" if msg.conversation_id else "no_conversation"
            msg.error = "El canal está pausado" if msg.conversation_id else "Mensaje sin conversación"
            msg.processed_at = now()
            return {"status": "ignored", "reason": msg.error_code}
        msg.status = "processing"
        msg.claimed_at = now()
        msg.attempts = (msg.attempts or 0) + 1
        return channel.id, msg.conversation_id


async def _release(message_id: uuid.UUID) -> None:
    async with system_session() as s:
        msg = await s.get(ChannelMessage, message_id, with_for_update=True)
        if msg is not None and msg.status == "processing":
            msg.status = "received"
            msg.claimed_at = None


async def _prepare(message_id: uuid.UUID) -> _Prepared:
    async with system_session() as s:
        msg = await s.get(ChannelMessage, message_id)
        assert msg is not None and msg.conversation_id is not None
        channel = await s.get(Channel, msg.channel_id)
        conv = await s.get(Conversation, msg.conversation_id, with_for_update=True)
        assert channel is not None and conv is not None
        base = _Prepared(channel.id, conv.id, None, None, None, None)
        member = await s.get(Workforce, channel.workforce_id)
        if member is None or member.kind != "agent":
            base.failure = ("member_missing", "El agente conectado a este canal ya no existe")
            return base
        state = await billing_state.load_state(s, channel.org_id)
        if state.blocked or state.read_only:
            base.failure = ("org_unavailable", "La organización no puede ejecutar agentes ahora mismo (facturación)")
            return base
        try:
            target = await resolve_target(s, channel.project_id, channel.environment)
        except NotDeployed:
            if not channel.demo:
                base.failure = (
                    "not_deployed",
                    "El proyecto no está desplegado en producción: despliégalo o conecta el canal a desarrollo",
                )
                return base
            target = await resolve_target(s, channel.project_id, "development")
            base.fallback_environment = "development"
        conv.workforce_name = member.name
        run_id = run_id_for(msg.id)
        existing = await s.get(Run, run_id)
        if existing is not None and existing.ended_at is not None:
            base.existing = {"run_id": run_id.hex, "status": existing.status, "output": existing.output}
            return base
        base.request = {
            "org_id": str(channel.org_id),
            "project_id": str(channel.project_id),
            "workforce": member.name,
            "ref": target.ref,
            "input": {"prompt": msg.text},
            "run_id": run_id.hex,
            "parent_run_id": conv.last_run_id.hex if conv.last_run_id else None,
            "environment": target.environment,
            "environment_id": str(target.environment_id) if target.environment_id else None,
            "version_id": str(target.version_id) if target.version_id else None,
            "channel": channel.provider,
            "external_user_id": (msg.sender_id or "")[:255] or None,
            "conversation_id": str(conv.id),
        }
        return base


async def _processed(message_id: uuid.UUID, result: dict[str, Any], fallback: str | None) -> None:
    async with system_session() as s:
        msg = await s.get(ChannelMessage, message_id, with_for_update=True)
        if msg is None:
            return
        msg.status = "processed"
        msg.processed_at = now()
        msg.run_id = _uuid(result.get("run_id"))
        msg.error = None
        msg.error_code = None
        if fallback:
            msg.payload = {**(msg.payload or {}), "environment_fallback": fallback}


async def _fail(message_id: uuid.UUID, code: str, message: str) -> None:
    """The agent could not run: record why, and keep the user's message visible in the thread."""
    async with system_session() as s:
        msg = await s.get(ChannelMessage, message_id, with_for_update=True)
        if msg is None:
            return
        msg.status = "failed"
        msg.error_code = code
        msg.error = message
        msg.processed_at = now()
        if msg.conversation_id is not None:
            conv = await s.get(Conversation, msg.conversation_id, with_for_update=True)
            if conv is not None:
                entry = {
                    "role": "user",
                    "text": msg.text,
                    "at": msg.created_at.isoformat() if msg.created_at else now().isoformat(),
                    "channel_message_id": str(msg.id),
                    "error": {"code": code, "message": message},
                }
                conv.messages = [*list(conv.messages or []), entry][-MAX_THREAD_MESSAGES:]
    log.warning("channel.inbound_failed", message_id=str(message_id), code=code)


def _uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


# ================================================================================================ delivery


def _reply_for(status: str, output: Any, config: dict[str, Any]) -> tuple[NoticeKind | None, str, str | None]:
    """(notice kind or None for a plain answer, text to send, notice text appended to the thread)."""
    text = text_of(output)
    if status == "success":
        return None, text, None
    if status == "paused":
        pending = notice(config, "approval_pending")
        return "approval_pending", f"{text}\n\n{pending}" if text else pending, pending
    if status == "blocked" and text:
        return None, text, None
    error = notice(config, "error")
    return "error", error, error


async def _send_with_retry(adapter: ChannelAdapter, ctx: Any, target: ReplyTarget, text: str) -> list[str]:
    for attempt in range(SEND_ATTEMPTS):
        try:
            return await adapter.send_text(ctx, target, text)
        except SendError as exc:
            if not exc.retryable or attempt == SEND_ATTEMPTS - 1:
                raise
            await asyncio.sleep(SEND_BACKOFF_S[min(attempt, len(SEND_BACKOFF_S) - 1)])
    return []


async def deliver(
    channel_id: uuid.UUID, conversation_id: uuid.UUID, result: dict[str, Any], *, inbound_id: uuid.UUID | None
) -> dict[str, Any]:
    """Send the outcome of a run to the user (or store it for demo channels and simulated messages).

    ``inbound_id`` is the message being answered; for resumed runs (after an approval) it is the latest inbound
    message of the conversation. Idempotent per (inbound message, run, kind).
    """
    status = str(result.get("status") or "error")
    run_id = _uuid(result.get("run_id"))
    async with system_session() as s:
        channel = await s.get(Channel, channel_id)
        conv = await s.get(Conversation, conversation_id, with_for_update=True)
        if channel is None or conv is None or not is_channel_provider(channel.provider):
            return {"status": "skipped", "reason": "channel_missing"}
        latest = (
            await s.execute(
                select(ChannelMessage)
                .where(ChannelMessage.conversation_id == conv.id, ChannelMessage.direction == "inbound")
                .order_by(ChannelMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        inbound = await s.get(ChannelMessage, inbound_id) if inbound_id else latest
        if inbound is None:
            return {"status": "skipped", "reason": "no_inbound_message"}
        ctx = channel_context(channel)
        kind, body, thread_notice = _reply_for(status, result.get("output"), ctx.config)
        if not body.strip():
            return {"status": "skipped", "reason": "empty_answer"}
        outbound_kind = kind or "answer"
        duplicate = (
            await s.execute(
                select(ChannelMessage.id).where(
                    ChannelMessage.reply_to_id == inbound.id,
                    ChannelMessage.direction == "outbound",
                    ChannelMessage.kind == outbound_kind,
                    ChannelMessage.status.in_(("sent", "stored")),
                    ChannelMessage.run_id == run_id if run_id is not None else ChannelMessage.run_id.is_(None),
                )
            )
        ).first()
        if duplicate is not None:
            return {"status": "skipped", "reason": "already_delivered"}
        if thread_notice:
            entry: dict[str, Any] = {
                "role": "assistant",
                "text": thread_notice,
                "notice": kind,
                "run_id": run_id.hex if run_id else None,
                "at": now().isoformat(),
            }
            conv.messages = [*list(conv.messages or []), entry][-MAX_THREAD_MESSAGES:]
        payload = dict(inbound.payload or {})
        last_inbound_at = _inbound_time(latest) if latest is not None else None
        target = ReplyTarget(
            conversation_key=str(payload.get("conversation_key") or conv.external_user_id),
            reply=dict(payload.get("reply") or {}),
            thread_id=payload.get("thread_id"),
            last_inbound_at=last_inbound_at,
        )
        stored = channel.demo or inbound.simulated
        inbound_ref = inbound.id
    adapter = get_adapter(channel.provider)
    formatted = adapter.format_text(body)
    error: SendError | None = None
    if stored:
        parts, ids = demo.store(adapter, formatted)
        out_status = "stored"
    else:
        parts = adapter.parts(formatted)
        try:
            ids = await _send_with_retry(adapter, ctx, target, formatted)
            out_status = "sent"
        except SendError as exc:
            ids, out_status, error = [], "failed", exc
    async with system_session() as s:
        row = ChannelMessage(
            org_id=channel.org_id,
            project_id=channel.project_id,
            channel_id=channel.id,
            conversation_id=conversation_id,
            direction="outbound",
            provider=channel.provider,
            external_id=(ids[0][:255] if ids else None),
            kind=outbound_kind,
            text=body,
            payload={
                "parts": len(parts),
                "provider_ids": ids,
                "reason": ("demo" if channel.demo else "simulated") if stored else None,
                "run_status": status,
            },
            status=out_status,
            error=error.message if error else None,
            error_code=error.code if error else None,
            run_id=run_id,
            reply_to_id=inbound_ref,
            processed_at=now(),
        )
        s.add(row)
        if error is not None and error.auth:
            stored_channel = await s.get(Channel, channel.id, with_for_update=True)
            if stored_channel is not None and stored_channel.status != "disabled":
                stored_channel.status = "error"
                stored_channel.error = error.message
        await s.flush()
        row_id = row.id
    if error is not None:
        log.warning("channel.delivery_failed", channel_id=str(channel.id), code=error.code, error=error.message)
    await publish_event(
        conversation_id,
        {
            "type": "channel_message",
            "direction": "outbound",
            "message_id": str(row_id),
            "status": out_status,
            "kind": outbound_kind,
        },
    )
    return {"status": out_status, "kind": outbound_kind, "parts": len(parts), "error": error.code if error else None}


def _inbound_time(msg: ChannelMessage) -> datetime | None:
    sent = (msg.payload or {}).get("sent_at")
    if isinstance(sent, str):
        try:
            return datetime.fromisoformat(sent)
        except ValueError:
            pass
    return msg.created_at


async def deliver_resumed_run(request: dict[str, Any], result: dict[str, Any]) -> dict[str, Any] | None:
    """After an approval decision, send the resumed run's answer to the channel the conversation came from.

    Never raises: delivery problems are recorded on the outbound message, not on the resume job.
    """
    if not is_channel_provider(str(request.get("channel") or "")) or not request.get("conversation_id"):
        return None
    try:
        conversation_id = uuid.UUID(str(request["conversation_id"]))
        async with system_session() as s:
            conv = await s.get(Conversation, conversation_id)
            channel_id = conv.channel_id if conv is not None else None
        if channel_id is None:
            return None
        async with conversation_lock(conversation_id):
            return await deliver(channel_id, conversation_id, result, inbound_id=None)
    except Exception as exc:
        log.error("channel.resume_delivery_failed", run_id=request.get("run_id"), error=str(exc))
        return {"status": "failed", "error": str(exc)}


async def pending_inbound_count(channel_id: uuid.UUID) -> int:
    async with system_session() as s:
        return int(
            (
                await s.execute(
                    select(func.count())
                    .select_from(ChannelMessage)
                    .where(
                        ChannelMessage.channel_id == channel_id,
                        ChannelMessage.direction == "inbound",
                        ChannelMessage.status.in_(("received", "processing")),
                    )
                )
            ).scalar_one()
        )
