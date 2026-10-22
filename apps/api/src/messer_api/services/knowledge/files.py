"""Knowledge files: storing uploads/connector files and queueing their ingestion."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import new_id
from messer_common.db.models import KbFile, KbTable, KnowledgeBase
from messer_common.knowledge.errors import KbNotFound, KnowledgeError
from messer_common.knowledge.parsing import detect_kind, guess_mime
from messer_common.logging import get_logger
from messer_common.queue import Jobs, enqueue
from messer_common.settings import get_settings
from messer_common.storage import get_storage

from .common import file_storage_key, publish_kb_event, safe_filename

log = get_logger("messer.api.knowledge.files")


def max_file_bytes() -> int:
    return get_settings().messer_kb_max_file_mb * 1024 * 1024


async def enqueue_ingestion(file_id: uuid.UUID) -> None:
    await enqueue(Jobs.INGEST_FILE, str(file_id), _job_id=f"ingest:{file_id}:{uuid.uuid4().hex[:8]}")


async def ingest_bytes(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kb_id: uuid.UUID,
    filename: str,
    data: bytes,
    mime: str | None,
    source: str,
    connection_id: uuid.UUID | None = None,
    external_id: str | None = None,
    uploaded_by: uuid.UUID | None = None,
    queue: bool = True,
) -> KbFile:
    """Store a file and queue its ingestion (contract §3).

    A file with the same ``external_id`` in the knowledge base is replaced (unchanged content is a no-op).
    Raises KnowledgeError for unknown knowledge bases, unsupported formats and files over the size limit.
    The ingestion job is queued immediately; the worker retries briefly until this transaction commits.
    """
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != org_id:
        raise KbNotFound("Base de conocimiento no encontrada")
    name = safe_filename(filename)
    limit = max_file_bytes()
    if len(data) > limit:
        raise KnowledgeError(
            f"{name} supera el máximo de {get_settings().messer_kb_max_file_mb} MB por archivo",
            code="file_too_large",
            status=413,
            details={"filename": name, "size": len(data), "max_bytes": limit},
        )
    if not data:
        raise KnowledgeError(f"{name} está vacío", code="file_empty", details={"filename": name})
    detect_kind(name, mime, data)  # raises ParseError(unsupported_format)
    content_type = guess_mime(name, mime)
    digest = hashlib.sha256(data).hexdigest()

    existing: KbFile | None = None
    if external_id:
        existing = (
            await session.execute(
                select(KbFile).where(KbFile.kb_id == kb.id, KbFile.external_id == external_id).with_for_update()
            )
        ).scalar_one_or_none()
        if existing is not None and existing.sha256 == digest and existing.status == "ready":
            return existing

    storage = get_storage()
    if existing is not None:
        old_path = existing.path
        key = file_storage_key(org_id, kb.id, existing.id, name)
        await storage.put(key, data, content_type)
        existing.path = key
        existing.filename = name
        existing.mime = content_type
        existing.size = len(data)
        existing.sha256 = digest
        existing.source = source
        existing.connection_id = connection_id or existing.connection_id
        existing.status = "queued"
        existing.error = None
        existing.uploaded_by = uploaded_by or existing.uploaded_by
        record = existing
        await session.flush()
        if old_path != key:
            try:
                await storage.delete(old_path)
            except Exception as exc:
                log.warning("knowledge.old_blob_delete_failed", path=old_path, error=str(exc)[:200])
    else:
        file_id = new_id()
        key = file_storage_key(org_id, kb.id, file_id, name)
        await storage.put(key, data, content_type)
        record = KbFile(
            id=file_id,
            org_id=org_id,
            kb_id=kb.id,
            path=key,
            filename=name,
            mime=content_type,
            size=len(data),
            sha256=digest,
            source=source,
            connection_id=connection_id,
            external_id=external_id,
            status="queued",
            uploaded_by=uploaded_by,
            meta={},
        )
        session.add(record)
        await session.flush()
    await publish_kb_event(
        kb.id,
        {"type": "file", "file_id": str(record.id), "filename": record.filename, "status": "queued", "progress": 0},
    )
    if queue:
        await enqueue_ingestion(record.id)
    return record


async def delete_blobs(paths: list[str]) -> None:
    """Remove stored objects after the database change committed (best effort)."""
    storage = get_storage()
    for path in paths:
        try:
            await storage.delete(path)
        except Exception as exc:
            log.warning("knowledge.blob_delete_failed", path=path, error=str(exc)[:200])


async def delete_file(session: AsyncSession, kb: KnowledgeBase, file: KbFile) -> str:
    """Delete a file, its chunks and the tables created from it (owner session).

    Returns the storage path; call :func:`delete_blobs` once the transaction has committed.
    """
    from .tables import drop_table

    tables = (
        await session.execute(
            select(KbTable).where(KbTable.kb_id == kb.id, KbTable.schema_json["file_id"].astext == str(file.id))
        )
    ).scalars()
    for table in list(tables):
        await drop_table(session, kb, table)
    path = file.path
    await session.execute(text("DELETE FROM public.kb_files WHERE id = :id"), {"id": file.id})
    return path
