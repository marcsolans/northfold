"""Knowledge jobs: file ingestion, chunk re-embedding, entity resolution, backups and restore."""

from __future__ import annotations

import uuid
from typing import Any

from arq import Retry

from messer_api.services.knowledge.backups import run_backup, run_restore
from messer_api.services.knowledge.common import publish_kb_event
from messer_api.services.knowledge.entities import run_entity_resolution
from messer_api.services.knowledge.ingestion import FileNotReady, process_file
from messer_api.services.knowledge.ingestion import reembed_chunk as _reembed_chunk
from messer_common.db import system_session
from messer_common.db.models import KbBackup, KnowledgeBase
from messer_common.logging import get_logger

log = get_logger("messer.worker.knowledge")
MAX_VISIBILITY_RETRIES = 5


def _attempt(ctx: dict[str, Any]) -> int:
    return int(ctx.get("job_try", 1) or 1)


async def ingest_file(ctx: dict[str, Any], file_id: str) -> str:
    """Parse, chunk, embed and index one knowledge file (status published on ``kb:<id>``)."""
    try:
        return await process_file(uuid.UUID(file_id))
    except FileNotReady as exc:
        if _attempt(ctx) < MAX_VISIBILITY_RETRIES:
            raise Retry(defer=_attempt(ctx)) from exc
        log.warning("knowledge.ingest_missing_file", file_id=file_id)
        return "missing"


async def reembed_chunk(ctx: dict[str, Any], chunk_id: str) -> bool:
    """Recompute a chunk's embedding after it was edited."""
    return await _reembed_chunk(uuid.UUID(chunk_id))


async def entity_resolution(ctx: dict[str, Any], kb_id: str) -> dict[str, int]:
    """Refresh duplicate-record suggestions for a knowledge base."""
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, uuid.UUID(kb_id))
        if kb is None:
            return {}
        stats = await run_entity_resolution(s, kb)
    await publish_kb_event(kb_id, {"type": "entities", "status": "done", "stats": stats})
    return stats


async def _backup_visible(ctx: dict[str, Any], backup_id: str) -> bool:
    async with system_session() as s:
        exists = await s.get(KbBackup, uuid.UUID(backup_id)) is not None
    if not exists and _attempt(ctx) < MAX_VISIBILITY_RETRIES:
        raise Retry(defer=_attempt(ctx))
    return exists


async def kb_backup(ctx: dict[str, Any], backup_id: str) -> str:
    if not await _backup_visible(ctx, backup_id):
        return "missing"
    return await run_backup(uuid.UUID(backup_id))


async def kb_restore(ctx: dict[str, Any], backup_id: str) -> str:
    if not await _backup_visible(ctx, backup_id):
        return "missing"
    return await run_restore(uuid.UUID(backup_id))


JOBS = [ingest_file, reembed_chunk, entity_resolution, kb_backup, kb_restore]
