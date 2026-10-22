"""Shared helpers for the knowledge control plane: error mapping, access checks, events, storage keys."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import AuditLog, KnowledgeBase
from messer_common.events import publish
from messer_common.knowledge.errors import KnowledgeError
from messer_common.logging import get_logger

from ...errors import ApiError, Forbidden, NotFound

log = get_logger("messer.api.knowledge")


def to_api_error(exc: KnowledgeError) -> ApiError:
    if exc.status == 404:
        return NotFound(exc.message, code=exc.code, details=exc.details)
    return ApiError(exc.message, code=exc.code, status_code=exc.status, details=exc.details)


@contextmanager
def api_errors() -> Iterator[None]:
    """Convert data-plane KnowledgeError into the API error envelope."""
    try:
        yield
    except KnowledgeError as exc:
        raise to_api_error(exc) from exc


async def get_kb(db: AsyncSession, kb_id: uuid.UUID, principal: Principal) -> KnowledgeBase:
    """Knowledge base visible to the principal (RLS session) or 404; project-scoped API keys are limited."""
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != principal.org_id:
        raise NotFound("Base de conocimiento no encontrada", code="kb_not_found")
    if principal.project_id is not None and kb.project_id is not None and kb.project_id != principal.project_id:
        raise Forbidden("La API key está limitada a otro proyecto", code="project_scope")
    return kb


async def record_audit(session: AsyncSession, **kwargs: Any) -> None:
    """``audit.record`` with a client-side timestamp.

    Without it the INSERT uses ``RETURNING created_at``, which row level security refuses for members who
    cannot read the audit log (only admins can), so non-admin mutations would fail.
    """
    await audit.record(session, **kwargs)
    now = datetime.now(UTC)
    for obj in session.new:
        if isinstance(obj, AuditLog) and obj.created_at is None:
            obj.created_at = now


def kb_channel(kb_id: uuid.UUID | str) -> str:
    return f"kb:{kb_id}"


async def publish_kb_event(kb_id: uuid.UUID | str, message: dict[str, Any]) -> None:
    """Best-effort real-time event (Redis may be briefly unavailable; state is in the database)."""
    try:
        await publish(kb_channel(kb_id), message)
    except Exception as exc:
        log.warning("knowledge.event_publish_failed", kb_id=str(kb_id), error=str(exc)[:200])


_UNSAFE = re.compile(r"[^\w.\- ()]+")


def safe_filename(name: str) -> str:
    """Basename without path separators or control characters (keeps accents), at most 200 chars."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    base = _UNSAFE.sub("_", base).strip(" .") or "archivo"
    if len(base) > 200:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: 200 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else base[:200]
    return base


def file_storage_key(org_id: uuid.UUID, kb_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/kb/{kb_id}/files/{file_id}/{safe_filename(filename)}"


def backup_storage_key(org_id: uuid.UUID, kb_id: uuid.UUID, backup_id: uuid.UUID) -> str:
    return f"{org_id}/kb/{kb_id}/backups/{backup_id}.jsonl.gz"
