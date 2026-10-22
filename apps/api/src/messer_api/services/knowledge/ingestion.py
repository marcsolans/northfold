"""Ingestion pipeline run by the worker: parse → chunk → embed (batched) → index.

Status is stored on ``kb_files.status`` and published on ``kb:<kb_id>``:
``queued → parsing → chunking → embedding → indexing → ready | error``.
CSV/Excel files become tables in the knowledge base schema instead of chunks.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import triggers
from messer_common.db import new_id, system_session
from messer_common.db.models import KbChunk, KbFile, KnowledgeBase
from messer_common.knowledge.chunking import chunk_blocks
from messer_common.knowledge.embeddings import embed_in_batches, get_embedder
from messer_common.knowledge.errors import KnowledgeError, ParseError
from messer_common.knowledge.parsing import TABULAR_KINDS, ParsedDocument, parse
from messer_common.logging import get_logger
from messer_common.storage import StorageError, get_storage

from .common import publish_kb_event
from .provisioning import ensure_vector_index
from .tables import create_table_from_parsed

log = get_logger("messer.api.knowledge.ingestion")
INSERT_BATCH = 500


class FileNotReady(Exception):
    """The file row is not visible yet (its transaction has not committed): retry shortly."""


def embedding_text(content: str, heading: str | None) -> str:
    """Text sent to the embedding model: the heading path gives the passage its context."""
    return f"{heading}\n\n{content}" if heading else content


async def _set_status(
    file_id: uuid.UUID,
    kb_id: uuid.UUID,
    filename: str,
    status: str,
    *,
    progress: float | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
    persist: bool = True,
) -> None:
    if persist:
        async with system_session() as s:
            values: dict[str, Any] = {"status": status}
            if status == "error":
                values["error"] = error
            elif status != "embedding":
                values["error"] = None
            await s.execute(update(KbFile).where(KbFile.id == file_id).values(**values))
    message: dict[str, Any] = {"type": "file", "file_id": str(file_id), "filename": filename, "status": status}
    if progress is not None:
        message["progress"] = round(progress, 3)
    if error:
        message["error"] = error
    if extra:
        message.update(extra)
    await publish_kb_event(kb_id, message)


async def process_file(file_id: uuid.UUID) -> str:
    """Ingest one file; returns the final status (``ready`` or ``error``). Raises FileNotReady."""
    async with system_session() as s:
        file = await s.get(KbFile, file_id)
        if file is None:
            raise FileNotReady(str(file_id))
        kb = await s.get(KnowledgeBase, file.kb_id)
        if kb is None:
            return "error"
        s.expunge(file)
        s.expunge(kb)
    started = time.perf_counter()
    filename = file.filename
    try:
        await _set_status(file.id, kb.id, filename, "parsing", progress=0.05)
        try:
            data = await get_storage().get(file.path)
        except StorageError as exc:
            raise KnowledgeError("No se encuentra el archivo almacenado", code="blob_missing") from exc
        parsed = await parse(data, filename, file.mime)
        meta: dict[str, Any] = {"parser": parsed.parser, "kind": parsed.kind, **parsed.metadata}
        table_ids: list[str] = []
        if parsed.tables:
            await _set_status(file.id, kb.id, filename, "indexing", progress=0.5)
            async with system_session() as s:
                kb_live = await s.get(KnowledgeBase, kb.id)
                file_live = await s.get(KbFile, file.id)
                if kb_live is None or file_live is None:
                    return "error"
                for parsed_table in parsed.tables:
                    table = await create_table_from_parsed(s, kb=kb_live, file=file_live, parsed=parsed_table)
                    table_ids.append(str(table.id))
            meta["tables"] = table_ids
        if parsed.kind in TABULAR_KINDS and not parsed.tables:
            raise ParseError("El archivo no contiene filas de datos", code="no_rows")
        chunk_count = 0
        if parsed.kind not in TABULAR_KINDS:
            if not parsed.has_text:
                raise ParseError(
                    "No se ha encontrado texto en el documento (¿es un PDF escaneado sin capa de texto?)",
                    code="no_text",
                )
            chunk_count = await _index_text(file, kb, parsed)
            if chunk_count < 0:
                return "error"
        elapsed = round(time.perf_counter() - started, 2)
        meta["ingest_seconds"] = elapsed
        async with system_session() as s:
            live = await s.get(KbFile, file.id)
            if live is None:
                return "error"
            live.status = "ready"
            live.error = None
            live.chunk_count = chunk_count
            live.pages = parsed.pages
            live.table_id = uuid.UUID(table_ids[0]) if table_ids else None
            live.meta = {**(live.meta or {}), **meta}
            await _emit_file_uploaded(s, live)
        await _set_status(
            file.id,
            kb.id,
            filename,
            "ready",
            progress=1.0,
            extra={"chunk_count": chunk_count, "tables": table_ids, "pages": parsed.pages},
            persist=False,
        )
        log.info("knowledge.ingested", file_id=str(file.id), chunks=chunk_count, tables=len(table_ids), seconds=elapsed)
        return "ready"
    except KnowledgeError as exc:
        await _set_status(file.id, kb.id, filename, "error", error=exc.message)
        log.info("knowledge.ingest_failed", file_id=str(file.id), code=exc.code, error=exc.message)
        return "error"
    except Exception as exc:
        log.exception("knowledge.ingest_crashed", file_id=str(file.id), error=str(exc)[:300])
        await _set_status(file.id, kb.id, filename, "error", error="Error interno al procesar el archivo")
        return "error"


async def _emit_file_uploaded(session: AsyncSession, file: KbFile) -> None:
    """Fire "file uploaded to a knowledge base" workflow triggers (never fails the ingestion)."""
    try:
        async with session.begin_nested():
            await triggers.emit(
                session,
                org_id=file.org_id,
                event="kb.file_uploaded",
                kb_id=file.kb_id,
                event_id=str(file.id),
                payload={
                    "kb_id": str(file.kb_id),
                    "file_id": str(file.id),
                    "filename": file.filename,
                    "mime": file.mime,
                    "source": file.source,
                },
            )
    except Exception as exc:
        log.warning("knowledge.trigger_emit_failed", file_id=str(file.id), error=str(exc)[:300])


async def _index_text(file: KbFile, kb: KnowledgeBase, parsed: ParsedDocument) -> int:
    """Chunk, embed and store; returns the number of chunks (-1 when the file disappeared)."""
    await _set_status(file.id, kb.id, file.filename, "chunking", progress=0.15)
    chunks = await asyncio.to_thread(
        chunk_blocks, parsed.blocks, max_tokens=kb.chunk_size_tokens, overlap_tokens=kb.chunk_overlap_tokens
    )
    if not chunks:
        raise ParseError("No se ha encontrado texto en el documento", code="no_text")
    await _set_status(file.id, kb.id, file.filename, "embedding", progress=0.2, extra={"chunks": len(chunks)})
    embedder = get_embedder(kb.embedding_model)
    last_publish = 0.0

    async def progress(done: int, total: int) -> None:
        nonlocal last_publish
        now = time.monotonic()
        if done == total or now - last_publish > 0.5:
            last_publish = now
            await _set_status(
                file.id,
                kb.id,
                file.filename,
                "embedding",
                progress=0.2 + 0.7 * done / max(total, 1),
                extra={"embedded": done, "chunks": total},
                persist=False,
            )

    vectors = await embed_in_batches(
        embedder, [embedding_text(c.content, c.heading) for c in chunks], on_progress=progress
    )
    await _set_status(file.id, kb.id, file.filename, "indexing", progress=0.92)
    await ensure_vector_index(kb)
    async with system_session() as s:
        live = (await s.execute(select(KbFile).where(KbFile.id == file.id).with_for_update())).scalar_one_or_none()
        if live is None:
            return -1
        await s.execute(delete(KbChunk).where(KbChunk.file_id == file.id))
        rows = [
            {
                "id": new_id(),
                "org_id": kb.org_id,
                "kb_id": kb.id,
                "file_id": file.id,
                "ordinal": c.ordinal,
                "content": c.content,
                "heading": c.heading,
                "page_from": c.page_from,
                "page_to": c.page_to,
                "token_count": c.token_count,
                "embedding": vector,
                "meta": c.metadata,
            }
            for c, vector in zip(chunks, vectors, strict=True)
        ]
        for start in range(0, len(rows), INSERT_BATCH):
            await s.execute(insert(KbChunk), rows[start : start + INSERT_BATCH])
    return len(chunks)


async def reembed_chunk(chunk_id: uuid.UUID) -> bool:
    """Recompute one chunk's embedding after an edit."""
    async with system_session() as s:
        chunk = await s.get(KbChunk, chunk_id)
        if chunk is None:
            return False
        kb = await s.get(KnowledgeBase, chunk.kb_id)
        if kb is None:
            return False
        content, heading, kb_id, version = chunk.content, chunk.heading, kb.id, chunk.edited_at
        model = kb.embedding_model
    vector = await get_embedder(model).embed([embedding_text(content, heading)])
    async with system_session() as s:
        chunk = (await s.execute(select(KbChunk).where(KbChunk.id == chunk_id).with_for_update())).scalar_one_or_none()
        if chunk is None:
            return False
        if chunk.edited_at != version:
            return False  # edited again meanwhile: the newer job will embed the newer text
        chunk.embedding = vector[0]
        meta = dict(chunk.meta or {})
        meta.pop("reembed_pending", None)
        meta["reembedded_at"] = datetime.now(UTC).isoformat()
        chunk.meta = meta
    await publish_kb_event(kb_id, {"type": "chunk", "chunk_id": str(chunk_id), "status": "reembedded"})
    return True
