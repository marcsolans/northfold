"""Conversations inbox: every thread of a project (channels, public chat, API, voice) with its trace links.

Studio playground conversations are private to their author and stay in the Studio; they are not listed here.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.channels.processing import conversation_channel, publish_event
from messer_common.db import Principal, rls_session
from messer_common.db.models import Approval, Channel, Conversation, Run
from messer_common.db.models.channels import ChannelMessage
from messer_common.events import get_redis

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound

router = APIRouter(tags=["conversations"])

STUDIO_PROVIDER = "studio"
STATUSES = ("open", "closed")
PREVIEW_CHARS = 160
SSE_PING_S = 15.0
SSE_MAX_S = 30 * 60


class LastMessage(BaseModel):
    role: str
    text: str
    at: str | None


class ConversationItem(BaseModel):
    id: uuid.UUID
    provider: str
    channel_id: uuid.UUID | None
    channel_name: str | None
    workforce_name: str
    contact_id: str
    contact_name: str | None
    title: str
    status: str
    message_count: int
    last_message: LastMessage | None
    last_run_id: uuid.UUID | None
    pending_approvals: int
    failed_deliveries: int
    simulated: bool
    created_at: datetime
    updated_at: datetime


class ProviderCount(BaseModel):
    provider: str
    count: int


class ConversationPage(BaseModel):
    items: list[ConversationItem]
    next_cursor: str | None
    providers: list[ProviderCount]


class Delivery(BaseModel):
    status: str
    kind: str
    error: str | None
    error_code: str | None
    parts: int | None


class ThreadMessage(BaseModel):
    index: int
    role: str
    text: str
    at: str | None
    run_id: uuid.UUID | None
    notice: str | None
    attachments: list[str]
    error: dict[str, Any] | None
    delivery: Delivery | None


class PendingApproval(BaseModel):
    id: uuid.UUID
    title: str
    tool_name: str
    created_at: datetime


class ChannelRef(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    demo: bool
    status: str


class ConversationDetail(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    channel: ChannelRef | None
    workforce_name: str
    contact_id: str
    contact_name: str | None
    title: str
    status: str
    simulated: bool
    external_thread_id: str | None
    last_run_id: uuid.UUID | None
    messages: list[ThreadMessage]
    pending_approvals: list[PendingApproval]
    created_at: datetime
    updated_at: datetime


def _uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _visible(conv: Conversation | None, principal: Principal) -> Conversation:
    if conv is None or conv.org_id != principal.org_id or conv.provider == STUDIO_PROVIDER:
        raise NotFound("Conversación no encontrada")
    ensure_project_access(principal, conv.project_id)
    return conv


def _last_message(messages: list[Any]) -> LastMessage | None:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
            text = str(m.get("text") or "")
            preview = text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1].rstrip() + "…"
            return LastMessage(role=str(m["role"]), text=preview, at=m.get("at"))
    return None


@router.get("/projects/{project_id}/conversations", response_model=ConversationPage)
async def list_conversations(
    project_id: uuid.UUID,
    provider: str | None = Query(default=None, max_length=20),
    status: str | None = Query(default=None, pattern="^(open|closed)$"),
    channel_id: uuid.UUID | None = None,
    contact: str | None = Query(default=None, max_length=255, description="Exact contact id (external user)"),
    q: str | None = Query(default=None, max_length=200, description="Search in title, contact and messages"),
    cursor: str | None = Query(default=None, description="updated_at|id of the last item of the previous page"),
    limit: int = Query(default=30, ge=1, le=100),
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> ConversationPage:
    """Inbox of the project: conversations from every channel, most recent activity first."""
    ensure_project_access(principal, project_id)
    base = select(Conversation).where(Conversation.project_id == project_id, Conversation.provider != STUDIO_PROVIDER)
    query = base
    if provider:
        query = query.where(Conversation.provider == provider)
    if status:
        query = query.where(Conversation.status == status)
    if channel_id:
        query = query.where(Conversation.channel_id == channel_id)
    if contact:
        query = query.where(Conversation.external_user_id == contact)
    if q and q.strip():
        pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                Conversation.title.ilike(pattern),
                Conversation.external_user_id.ilike(pattern),
                cast(Conversation.messages, String).ilike(pattern),
            )
        )
    if cursor:
        try:
            raw_ts, raw_id = cursor.split("|", 1)
            ts, last_id = datetime.fromisoformat(raw_ts), uuid.UUID(raw_id)
        except ValueError as exc:
            raise ApiError("Cursor no válido", code="invalid_cursor") from exc
        query = query.where(
            or_(Conversation.updated_at < ts, (Conversation.updated_at == ts) & (Conversation.id < last_id))
        )
    rows = list(
        (await session.execute(query.order_by(Conversation.updated_at.desc(), Conversation.id.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    page = rows[:limit]
    ids = [c.id for c in page]
    channel_ids = {c.channel_id for c in page if c.channel_id}
    channels = (
        {
            cid: name
            for cid, name in (
                await session.execute(select(Channel.id, Channel.name).where(Channel.id.in_(channel_ids)))
            ).all()
        }
        if channel_ids
        else {}
    )
    contacts: dict[uuid.UUID, str] = {}
    simulated: set[uuid.UUID] = set()
    failed: dict[uuid.UUID, int] = {}
    pending: dict[uuid.UUID, int] = {}
    if ids:
        name_rows = (
            await session.execute(
                select(ChannelMessage.conversation_id, ChannelMessage.sender_name, ChannelMessage.simulated)
                .where(
                    ChannelMessage.conversation_id.in_(ids),
                    ChannelMessage.direction == "inbound",
                )
                .order_by(ChannelMessage.conversation_id, ChannelMessage.created_at.desc())
                .ext(distinct_on(ChannelMessage.conversation_id))
            )
        ).all()
        for cid, name, is_simulated in name_rows:
            if cid is None:
                continue
            if name:
                contacts[cid] = name
            if is_simulated:
                simulated.add(cid)
        failed_rows = (
            await session.execute(
                select(ChannelMessage.conversation_id, func.count())
                .where(ChannelMessage.conversation_id.in_(ids), ChannelMessage.status == "failed")
                .group_by(ChannelMessage.conversation_id)
            )
        ).all()
        failed = {cid: int(n) for cid, n in failed_rows if cid is not None}
        pending_rows = (
            await session.execute(
                select(Run.conversation_id, func.count())
                .select_from(Approval)
                .join(Run, Run.id == Approval.run_id)
                .where(Run.conversation_id.in_(ids), Approval.status == "pending")
                .group_by(Run.conversation_id)
            )
        ).all()
        pending = {cid: int(n) for cid, n in pending_rows if cid is not None}
    providers: list[ProviderCount] = []
    if not cursor:
        provider_rows = (
            await session.execute(
                select(Conversation.provider, func.count())
                .where(Conversation.project_id == project_id, Conversation.provider != STUDIO_PROVIDER)
                .group_by(Conversation.provider)
                .order_by(func.count().desc())
            )
        ).all()
        providers = [ProviderCount(provider=p, count=int(n)) for p, n in provider_rows]
    items = [
        ConversationItem(
            id=c.id,
            provider=c.provider,
            channel_id=c.channel_id,
            channel_name=channels.get(c.channel_id) if c.channel_id else None,
            workforce_name=c.workforce_name,
            contact_id=c.external_user_id,
            contact_name=contacts.get(c.id),
            title=c.title,
            status=c.status,
            message_count=sum(
                1 for m in c.messages or [] if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            ),
            last_message=_last_message(list(c.messages or [])),
            last_run_id=c.last_run_id,
            pending_approvals=pending.get(c.id, 0),
            failed_deliveries=failed.get(c.id, 0),
            simulated=c.id in simulated,
            created_at=c.created_at,
            updated_at=c.updated_at,
        )
        for c in page
    ]
    next_cursor = f"{page[-1].updated_at.isoformat()}|{page[-1].id}" if len(rows) > limit and page else None
    return ConversationPage(items=items, next_cursor=next_cursor, providers=providers)


async def _detail(session: AsyncSession, conv: Conversation) -> ConversationDetail:
    channel = await session.get(Channel, conv.channel_id) if conv.channel_id else None
    rows = list(
        (
            await session.execute(
                select(ChannelMessage)
                .where(ChannelMessage.conversation_id == conv.id)
                .order_by(ChannelMessage.created_at)
            )
        )
        .scalars()
        .all()
    )
    inbound_by_run = {m.run_id: m for m in rows if m.direction == "inbound" and m.run_id}
    inbound_by_id = {m.id: m for m in rows if m.direction == "inbound"}
    outbound: dict[tuple[uuid.UUID | None, str], ChannelMessage] = {}
    for m in rows:
        if m.direction == "outbound":
            outbound[(m.run_id, m.kind)] = m  # latest attempt wins
    latest_inbound = next((m for m in reversed(rows) if m.direction == "inbound"), None)
    messages: list[ThreadMessage] = []
    for index, raw in enumerate(conv.messages or []):
        if not isinstance(raw, dict) or raw.get("role") not in ("user", "assistant"):
            continue
        run_id = _uuid(raw.get("run_id"))
        notice = raw.get("notice") if raw.get("notice") in ("approval_pending", "error") else None
        delivery: Delivery | None = None
        error = raw.get("error") if isinstance(raw.get("error"), dict) else None
        if raw["role"] == "assistant":
            sent = outbound.get((run_id, notice or "answer"))
            if sent is not None:
                delivery = Delivery(
                    status=sent.status,
                    kind=sent.kind,
                    error=sent.error,
                    error_code=sent.error_code,
                    parts=(sent.payload or {}).get("parts"),
                )
        else:
            source = inbound_by_run.get(run_id) if run_id else None
            if source is None:
                message_id = _uuid(raw.get("channel_message_id"))
                source = inbound_by_id.get(message_id) if message_id else None
            if source is not None and source.status == "failed" and error is None:
                error = {"code": source.error_code, "message": source.error}
        attachments = [str(a) for a in raw.get("attachments") or [] if isinstance(a, str | int)]
        messages.append(
            ThreadMessage(
                index=index,
                role=str(raw["role"]),
                text=str(raw.get("text") or ""),
                at=raw.get("at"),
                run_id=run_id,
                notice=notice,
                attachments=attachments,
                error=error,
                delivery=delivery,
            )
        )
    # Messages received but not processed yet are part of the thread too (the inbox shows them right away).
    for m in rows:
        if m.direction == "inbound" and m.status in ("received", "processing"):
            messages.append(
                ThreadMessage(
                    index=len(conv.messages or []) + len(messages),
                    role="user",
                    text=m.text,
                    at=m.created_at.isoformat(),
                    run_id=None,
                    notice=None,
                    attachments=[],
                    error=None,
                    delivery=Delivery(status=m.status, kind=m.kind, error=None, error_code=None, parts=None),
                )
            )
    approvals = (
        (
            await session.execute(
                select(Approval)
                .join(Run, Run.id == Approval.run_id)
                .where(Run.conversation_id == conv.id, Approval.status == "pending")
                .order_by(Approval.created_at)
            )
        )
        .scalars()
        .all()
    )
    return ConversationDetail(
        id=conv.id,
        project_id=conv.project_id,
        provider=conv.provider,
        channel=ChannelRef(
            id=channel.id, name=channel.name, provider=channel.provider, demo=channel.demo, status=channel.status
        )
        if channel
        else None,
        workforce_name=conv.workforce_name,
        contact_id=conv.external_user_id,
        contact_name=next((m.sender_name for m in reversed(rows) if m.direction == "inbound" and m.sender_name), None),
        title=conv.title,
        status=conv.status,
        simulated=bool(latest_inbound and latest_inbound.simulated),
        external_thread_id=conv.external_thread_id,
        last_run_id=conv.last_run_id,
        messages=messages,
        pending_approvals=[
            PendingApproval(id=a.id, title=a.title or a.tool_name, tool_name=a.tool_name, created_at=a.created_at)
            for a in approvals
        ],
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    """The thread with per-turn run ids (trace links), delivery status and pending approvals."""
    conv = _visible(await session.get(Conversation, conversation_id), principal)
    return await _detail(session, conv)


async def _set_status(
    session: AsyncSession, principal: Principal, conversation_id: uuid.UUID, status: str
) -> ConversationDetail:
    conv = _visible(await session.get(Conversation, conversation_id, with_for_update=True), principal)
    if conv.status != status:
        conv.status = status
        await audit.record(
            session,
            action="conversation.closed" if status == "closed" else "conversation.reopened",
            principal=principal,
            entity_type="conversation",
            entity_id=conv.id,
            diff={"status": status},
        )
        await session.flush()
        await session.refresh(conv)
        await publish_event(conv.id, {"type": "status", "status": status})
    return await _detail(session, conv)


@router.post("/conversations/{conversation_id}/close", response_model=ConversationDetail)
async def close_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    """Mark the conversation as resolved. A new message from the user reopens it (memory continues)."""
    return await _set_status(session, principal, conversation_id, "closed")


@router.post("/conversations/{conversation_id}/reopen", response_model=ConversationDetail)
async def reopen_conversation(
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> ConversationDetail:
    return await _set_status(session, principal, conversation_id, "open")


async def _events(conversation_id: uuid.UUID) -> AsyncIterator[str]:
    pubsub = get_redis().pubsub()
    await pubsub.subscribe(conversation_channel(conversation_id))
    started = asyncio.get_running_loop().time()
    try:
        yield ": connected\n\n"
        while asyncio.get_running_loop().time() - started < SSE_MAX_S:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=SSE_PING_S)
            if message is None:
                yield ": ping\n\n"
                continue
            data = message.get("data")
            try:
                event = json.loads(data) if isinstance(data, str | bytes) else {}
            except ValueError:
                continue
            yield f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"
    finally:
        await pubsub.unsubscribe()
        await pubsub.aclose()


@router.get("/conversations/{conversation_id}/events")
async def conversation_events(
    conversation_id: uuid.UUID, principal: Principal = Depends(require_role("viewer"))
) -> StreamingResponse:
    """Live updates (SSE): messages received and sent, runs finished, status changes."""
    async with rls_session(principal) as session:
        _visible(await session.get(Conversation, conversation_id), principal)
    return StreamingResponse(
        _events(conversation_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
