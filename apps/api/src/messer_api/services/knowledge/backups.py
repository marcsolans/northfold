"""On-demand knowledge base backups and restore.

A backup is a gzip-compressed JSON-lines document in storage (``<org>/kb/<kb>/backups/<id>.jsonl.gz``):
a header, every table (definition and rows), the files manifest (metadata and storage paths, not the
blobs), every chunk with its embedding, policies and entity decisions. Restore replaces the knowledge
base's contents in a single transaction.
"""

from __future__ import annotations

import gzip
import io
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from psycopg.types.json import Jsonb
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import system_session
from messer_common.db.models import KbBackup, KbChunk, KbEntity, KbFile, KbPolicy, KbTable, KnowledgeBase
from messer_common.knowledge import coltypes as ct
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.sql import jsonable
from messer_common.knowledge.sqlcheck import quote_ident
from messer_common.logging import get_logger
from messer_common.storage import StorageError, get_storage

from .common import backup_storage_key, publish_kb_event
from .tables import _create_table, _lock, table_columns

log = get_logger("messer.api.knowledge.backups")
FORMAT = "messer-kb-backup"
VERSION = 1
BATCH = 500


def _line(obj: dict[str, Any]) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, default=str, separators=(",", ":")) + "\n").encode("utf-8")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _dump(session: AsyncSession, kb: KnowledgeBase, out: io.BufferedIOBase) -> dict[str, int]:
    counts = {"tables": 0, "rows": 0, "files": 0, "chunks": 0, "policies": 0, "entities": 0}
    out.write(
        _line(
            {
                "type": "header",
                "format": FORMAT,
                "version": VERSION,
                "kb_id": str(kb.id),
                "created_at": datetime.now(UTC).isoformat(),
                "kb": {
                    "name": kb.name,
                    "description": kb.description,
                    "embedding_model": kb.embedding_model,
                    "embedding_dim": kb.embedding_dim,
                    "governance_mode": kb.governance_mode,
                    "chunk_size_tokens": kb.chunk_size_tokens,
                    "chunk_overlap_tokens": kb.chunk_overlap_tokens,
                },
            }
        )
    )
    tables = (await session.execute(select(KbTable).where(KbTable.kb_id == kb.id).order_by(KbTable.name))).scalars()
    for table in list(tables):
        columns = [c["name"] for c in table_columns(table)]
        has_row_id = not (table.schema_json or {}).get("primary_key")
        order = ([ct.ROW_ID] if has_row_id else []) + columns
        out.write(
            _line(
                {
                    "type": "table",
                    "id": str(table.id),
                    "name": table.name,
                    "description": table.description,
                    "schema_json": table.schema_json,
                    "source": table.source,
                    "sync_id": str(table.sync_id) if table.sync_id else None,
                    "column_order": order,
                }
            )
        )
        counts["tables"] += 1
        result = await session.stream(
            text(
                "SELECT "
                + ", ".join(quote_ident(c) for c in order)
                + f" FROM {quote_ident(kb.schema_name)}.{quote_ident(table.name)}"
            )
        )
        async for row in result:
            out.write(_line({"type": "row", "table": table.name, "values": [jsonable(v) for v in row]}))
            counts["rows"] += 1
    files = (await session.execute(select(KbFile).where(KbFile.kb_id == kb.id).order_by(KbFile.created_at))).scalars()
    for f in files:
        out.write(
            _line(
                {
                    "type": "file",
                    "id": str(f.id),
                    "path": f.path,
                    "filename": f.filename,
                    "mime": f.mime,
                    "size": f.size,
                    "sha256": f.sha256,
                    "source": f.source,
                    "connection_id": str(f.connection_id) if f.connection_id else None,
                    "external_id": f.external_id,
                    "status": f.status,
                    "error": f.error,
                    "pages": f.pages,
                    "chunk_count": f.chunk_count,
                    "table_id": str(f.table_id) if f.table_id else None,
                    "metadata": f.meta,
                    "uploaded_by": str(f.uploaded_by) if f.uploaded_by else None,
                    "created_at": _iso(f.created_at),
                }
            )
        )
        counts["files"] += 1
    chunks = await session.stream(
        select(KbChunk)
        .where(KbChunk.kb_id == kb.id)
        .order_by(KbChunk.file_id, KbChunk.ordinal)
        .execution_options(yield_per=BATCH)
    )
    async for (c,) in chunks:
        embedding = c.embedding
        out.write(
            _line(
                {
                    "type": "chunk",
                    "id": str(c.id),
                    "file_id": str(c.file_id),
                    "ordinal": c.ordinal,
                    "content": c.content,
                    "heading": c.heading,
                    "page_from": c.page_from,
                    "page_to": c.page_to,
                    "token_count": c.token_count,
                    "embedding": [float(x) for x in embedding] if embedding is not None else None,
                    "metadata": c.meta,
                    "edited_at": _iso(c.edited_at),
                }
            )
        )
        counts["chunks"] += 1
    for p in (await session.execute(select(KbPolicy).where(KbPolicy.kb_id == kb.id))).scalars():
        out.write(
            _line(
                {
                    "type": "policy",
                    "id": str(p.id),
                    "table": p.table,
                    "role": p.role,
                    "row_filter_sql": p.row_filter_sql,
                    "masked_columns": p.masked_columns,
                    "compliance_tags": p.compliance_tags,
                    "break_glass": p.break_glass,
                    "enabled": p.enabled,
                }
            )
        )
        counts["policies"] += 1
    for e in (await session.execute(select(KbEntity).where(KbEntity.kb_id == kb.id))).scalars():
        out.write(
            _line(
                {
                    "type": "entity",
                    "id": str(e.id),
                    "entity_type": e.entity_type,
                    "match_key": e.match_key,
                    "method": e.method,
                    "score": e.score,
                    "records": e.records,
                    "status": e.status,
                    "golden_record": e.golden_record,
                    "decided_by": str(e.decided_by) if e.decided_by else None,
                    "decided_at": _iso(e.decided_at),
                }
            )
        )
        counts["entities"] += 1
    out.write(_line({"type": "footer", "counts": counts}))
    return counts


async def run_backup(backup_id: uuid.UUID) -> str:
    """Write the backup document and mark the row ``ready`` (or ``error``). Returns the final status."""
    async with system_session() as s:
        backup = await s.get(KbBackup, backup_id)
        if backup is None:
            return "error"
        backup.status = "running"
        kb_id = backup.kb_id
    await publish_kb_event(kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "running"})
    try:
        buffer = io.BytesIO()
        async with system_session() as s:
            kb = await s.get(KnowledgeBase, kb_id)
            if kb is None:
                raise KnowledgeError("Base de conocimiento no encontrada", status=404)
            with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=6) as gz:
                counts = await _dump(s, kb, gz)  # type: ignore[arg-type]
            key = backup_storage_key(kb.org_id, kb.id, backup_id)
        data = buffer.getvalue()
        await get_storage().put(key, data, "application/gzip")
        async with system_session() as s:
            backup = await s.get(KbBackup, backup_id)
            if backup is None:
                return "error"
            backup.path = key
            backup.size = len(data)
            backup.status = "ready"
            backup.stats = {**counts, "finished_at": datetime.now(UTC).isoformat()}
        await publish_kb_event(
            kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "ready", "stats": counts}
        )
        return "ready"
    except Exception as exc:
        log.exception("knowledge.backup_failed", backup_id=str(backup_id), error=str(exc)[:300])
        message = exc.message if isinstance(exc, KnowledgeError) else "Error interno al crear la copia"
        async with system_session() as s:
            backup = await s.get(KbBackup, backup_id)
            if backup is not None:
                backup.status = "error"
                backup.stats = {**(backup.stats or {}), "error": message}
        await publish_kb_event(
            kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "error", "error": message}
        )
        return "error"


def _read_lines(data: bytes) -> Iterator[dict[str, Any]]:
    with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gz:
        for raw in gz:
            raw = raw.strip()
            if raw:
                yield json.loads(raw)


def _uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def _dt(value: Any) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def _restore_rows(session: AsyncSession, kb: KnowledgeBase, table: dict[str, Any], rows: list[list[Any]]) -> None:
    order: list[str] = table["column_order"]
    types = {c["name"]: c["type"] for c in table["schema_json"].get("columns", [])}
    types[ct.ROW_ID] = "integer"
    conn = await session.connection()
    raw = await conn.get_raw_connection()
    pg: Any = raw.driver_connection
    target = f"{quote_ident(kb.schema_name)}.{quote_ident(table['name'])}"
    pg_types = [ct.PG_TYPES[types.get(c, "text")] for c in order]
    async with pg.cursor() as cur:
        async with cur.copy(f"COPY {target} (" + ", ".join(quote_ident(c) for c in order) + ") FROM STDIN") as copy:
            copy.set_types([{"bigint": "int8", "boolean": "bool"}.get(t, t) for t in pg_types])
            for values in rows:
                out: list[Any] = []
                for column, value in zip(order, values, strict=True):
                    logical = types.get(column, "text")
                    try:
                        coerced = ct.coerce(value, logical)
                    except ct.CoercionError:
                        coerced = None
                    out.append(Jsonb(coerced) if logical == "json" and coerced is not None else coerced)
                await copy.write_row(out)
        if ct.ROW_ID in order:
            await cur.execute(
                f"SELECT setval(pg_get_serial_sequence(%s, %s), coalesce((SELECT max({quote_ident(ct.ROW_ID)}) FROM {target}), 0) + 1, false)",
                [f"{quote_ident(kb.schema_name)}.{quote_ident(table['name'])}", ct.ROW_ID],
            )


async def restore_into(session: AsyncSession, kb: KnowledgeBase, data: bytes) -> dict[str, int]:
    """Replace the knowledge base contents with a backup document (owner session, one transaction)."""
    lines = _read_lines(data)
    header = next(lines, None)
    if not header or header.get("type") != "header" or header.get("format") != FORMAT:
        raise KnowledgeError("El archivo no es una copia de seguridad de Messer", code="backup_invalid")
    if int(header.get("version", 0)) > VERSION:
        raise KnowledgeError("La copia es de una versión más reciente", code="backup_version")
    meta = header.get("kb", {})
    same_vectors = (
        meta.get("embedding_model") == kb.embedding_model and int(meta.get("embedding_dim", 0)) == kb.embedding_dim
    )

    await _lock(session, kb.id, "*restore*")
    for existing in (await session.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalars():
        await session.execute(text(f"DROP TABLE IF EXISTS {quote_ident(kb.schema_name)}.{quote_ident(existing.name)}"))
    await session.execute(delete(KbTable).where(KbTable.kb_id == kb.id))
    await session.execute(delete(KbEntity).where(KbEntity.kb_id == kb.id))
    await session.execute(delete(KbPolicy).where(KbPolicy.kb_id == kb.id))
    await session.execute(delete(KbFile).where(KbFile.kb_id == kb.id))  # cascades to chunks
    await session.flush()

    counts = {"tables": 0, "rows": 0, "files": 0, "chunks": 0, "policies": 0, "entities": 0, "missing_blobs": 0}
    storage = get_storage()
    current_table: dict[str, Any] | None = None
    pending_rows: list[list[Any]] = []
    chunk_batch: list[dict[str, Any]] = []

    async def flush_rows() -> None:
        nonlocal pending_rows
        if current_table is not None and pending_rows:
            await _restore_rows(session, kb, current_table, pending_rows)
            counts["rows"] += len(pending_rows)
        pending_rows = []

    async def flush_chunks() -> None:
        nonlocal chunk_batch
        if chunk_batch:
            await session.execute(insert(KbChunk), chunk_batch)
            counts["chunks"] += len(chunk_batch)
        chunk_batch = []

    for line in lines:
        kind = line.get("type")
        if kind == "table":
            await flush_rows()
            schema_json = line.get("schema_json") or {}
            pk = list(schema_json.get("primary_key") or [])
            specs = [
                ct.ColumnSpec(
                    name=c["name"],
                    type=ct.logical_type(c.get("type", "text")),
                    nullable=bool(c.get("nullable", True)),
                    comment=c.get("comment"),
                    pk=c["name"] in pk,
                )
                for c in schema_json.get("columns", [])
            ]
            await _create_table(session, kb, line["name"], specs, pk)
            session.add(
                KbTable(
                    id=_uuid(line.get("id")) or uuid.uuid4(),
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    name=line["name"],
                    description=line.get("description") or "",
                    schema_json=schema_json,
                    row_count=0,
                    source=line.get("source") or "upload",
                    sync_id=_uuid(line.get("sync_id")),
                )
            )
            current_table = line
            counts["tables"] += 1
        elif kind == "row":
            if current_table is None or line.get("table") != current_table["name"]:
                raise KnowledgeError("Copia de seguridad corrupta (filas sin tabla)", code="backup_invalid")
            pending_rows.append(list(line.get("values") or []))
            if len(pending_rows) >= 5000:
                await flush_rows()
        elif kind == "file":
            await flush_rows()
            missing = not await storage.exists(line["path"])
            counts["missing_blobs"] += int(missing)
            metadata = dict(line.get("metadata") or {})
            if missing:
                metadata["blob_missing"] = True
            session.add(
                KbFile(
                    id=uuid.UUID(line["id"]),
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    path=line["path"],
                    filename=line["filename"],
                    mime=line.get("mime") or "application/octet-stream",
                    size=int(line.get("size") or 0),
                    sha256=line.get("sha256"),
                    source=line.get("source") or "upload",
                    connection_id=_uuid(line.get("connection_id")),
                    external_id=line.get("external_id"),
                    status=line.get("status") or "ready",
                    error=line.get("error"),
                    pages=line.get("pages"),
                    chunk_count=int(line.get("chunk_count") or 0),
                    table_id=_uuid(line.get("table_id")),
                    meta=metadata,
                    uploaded_by=_uuid(line.get("uploaded_by")),
                    created_at=_dt(line.get("created_at")) or datetime.now(UTC),
                )
            )
            counts["files"] += 1
        elif kind == "chunk":
            await flush_rows()
            if not chunk_batch:
                await session.flush()  # files must exist before their chunks
            metadata = dict(line.get("metadata") or {})
            embedding = line.get("embedding") if same_vectors else None
            if not same_vectors:
                metadata["reembed_pending"] = True
            chunk_batch.append(
                {
                    "id": uuid.UUID(line["id"]),
                    "org_id": kb.org_id,
                    "kb_id": kb.id,
                    "file_id": uuid.UUID(line["file_id"]),
                    "ordinal": int(line["ordinal"]),
                    "content": line["content"],
                    "heading": line.get("heading"),
                    "page_from": line.get("page_from"),
                    "page_to": line.get("page_to"),
                    "token_count": int(line.get("token_count") or 0),
                    "embedding": embedding,
                    "meta": metadata,
                    "edited_at": _dt(line.get("edited_at")),
                }
            )
            if len(chunk_batch) >= BATCH:
                await flush_chunks()
        elif kind == "policy":
            await flush_rows()
            await flush_chunks()
            session.add(
                KbPolicy(
                    id=uuid.UUID(line["id"]),
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    table=line["table"],
                    role=line["role"],
                    row_filter_sql=line.get("row_filter_sql"),
                    masked_columns=line.get("masked_columns") or {},
                    compliance_tags=line.get("compliance_tags") or [],
                    break_glass=bool(line.get("break_glass")),
                    enabled=bool(line.get("enabled", True)),
                )
            )
            counts["policies"] += 1
        elif kind == "entity":
            await flush_rows()
            await flush_chunks()
            session.add(
                KbEntity(
                    id=uuid.UUID(line["id"]),
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    entity_type=line.get("entity_type") or "generic",
                    match_key=line["match_key"],
                    method=line.get("method") or "deterministic",
                    score=float(line.get("score") or 1.0),
                    records=line.get("records") or [],
                    status=line.get("status") or "suggested",
                    golden_record=line.get("golden_record"),
                    decided_by=_uuid(line.get("decided_by")),
                    decided_at=_dt(line.get("decided_at")),
                )
            )
            counts["entities"] += 1
    await flush_rows()
    await session.flush()
    await flush_chunks()
    await session.flush()
    for table in (await session.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalars():
        table.row_count = int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM {quote_ident(kb.schema_name)}.{quote_ident(table.name)}")
                )
            ).scalar_one()
        )
    return counts


async def run_restore(backup_id: uuid.UUID) -> str:
    """Restore a ready backup into its knowledge base. Returns the final status of the backup row."""
    async with system_session() as s:
        backup = await s.get(KbBackup, backup_id)
        if backup is None or backup.status not in ("ready", "restoring"):
            return "error"
        backup.status = "restoring"
        kb_id, path = backup.kb_id, backup.path
    await publish_kb_event(kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "restoring"})
    try:
        try:
            data = await get_storage().get(path)
        except StorageError as exc:
            raise KnowledgeError("No se encuentra el archivo de la copia", code="backup_missing") from exc
        async with system_session() as s:
            kb = await s.get(KnowledgeBase, kb_id)
            if kb is None:
                raise KnowledgeError("Base de conocimiento no encontrada", status=404)
            counts = await restore_into(s, kb, data)
            backup = await s.get(KbBackup, backup_id)
            if backup is not None:
                backup.status = "ready"
                backup.restored_at = datetime.now(UTC)
                backup.stats = {**(backup.stats or {}), "last_restore": counts}
        await publish_kb_event(
            kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "restored", "stats": counts}
        )
        return "restored"
    except Exception as exc:
        log.exception("knowledge.restore_failed", backup_id=str(backup_id), error=str(exc)[:300])
        message = exc.message if isinstance(exc, KnowledgeError) else "Error interno al restaurar la copia"
        async with system_session() as s:
            backup = await s.get(KbBackup, backup_id)
            if backup is not None:
                backup.status = "ready"
                backup.stats = {**(backup.stats or {}), "last_restore_error": message}
        await publish_kb_event(
            kb_id, {"type": "backup", "backup_id": str(backup_id), "status": "restore_failed", "error": message}
        )
        return "error"
