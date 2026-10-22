"""Chunk maintenance: edit (re-embedded in the background) and delete."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import KbChunk, KbFile
from messer_common.knowledge.chunking import estimate_tokens
from messer_common.knowledge.errors import KnowledgeError
from messer_common.queue import Jobs, enqueue

from .common import record_audit

MAX_CHUNK_CHARS = 50_000


async def edit_chunk(
    session: AsyncSession,
    principal: Principal,
    chunk: KbChunk,
    *,
    content: str | None,
    heading: str | None,
    heading_set: bool,
) -> KbChunk:
    """Update text (RLS session); the tsvector trigger refreshes keyword search, a job re-embeds."""
    before = {"content": chunk.content, "heading": chunk.heading}
    if content is not None:
        value = content.strip()
        if not value:
            raise KnowledgeError("El fragmento no puede quedar vacío", code="chunk_empty")
        if len(value) > MAX_CHUNK_CHARS:
            raise KnowledgeError("El fragmento es demasiado largo", code="chunk_too_long")
        chunk.content = value
        chunk.token_count = estimate_tokens(value)
    if heading_set:
        chunk.heading = (heading or "").strip() or None
    if chunk.content == before["content"] and chunk.heading == before["heading"]:
        return chunk
    chunk.edited_at = datetime.now(UTC)
    chunk.meta = {**(chunk.meta or {}), "reembed_pending": True, "edited_by": str(principal.user_id)}
    await record_audit(
        session,
        action="knowledge.chunk.update",
        principal=principal,
        entity_type="kb_chunk",
        entity_id=chunk.id,
        diff={"before": before, "after": {"content": chunk.content, "heading": chunk.heading}},
    )
    await session.flush()
    await enqueue(Jobs.REEMBED_CHUNK, str(chunk.id), _job_id=f"reembed:{chunk.id}:{chunk.edited_at.timestamp()}")
    return chunk


async def delete_chunk(session: AsyncSession, principal: Principal, chunk: KbChunk) -> None:
    file_id, chunk_id = chunk.file_id, chunk.id
    await session.delete(chunk)
    await session.flush()
    remaining = (await session.execute(select(func.count()).where(KbChunk.file_id == file_id))).scalar_one()
    await session.execute(update(KbFile).where(KbFile.id == file_id).values(chunk_count=int(remaining)))
    await record_audit(
        session,
        action="knowledge.chunk.delete",
        principal=principal,
        entity_type="kb_chunk",
        entity_id=chunk_id,
        diff={"file_id": file_id},
    )
