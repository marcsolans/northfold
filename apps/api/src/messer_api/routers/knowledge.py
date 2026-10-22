"""/api/v1/knowledge-bases — knowledge bases, files, live status, chunks, search and the SQL console.

Roles: viewers read, search and run read-only SQL (their role's policies apply); builders upload, edit and
delete content; admins change governance, policies and backups and delete knowledge bases.
Tables live in ``knowledge_tables``; policies, entities and backups in ``knowledge_governance``.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from messer_common.db import Principal, rls_session, system_session
from messer_common.db.models import KbChunk, KbFile, KbTable, KnowledgeBase, Org
from messer_common.events import subscribe
from messer_common.knowledge import embeddings as emb
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.search import search as kb_search
from messer_common.knowledge.sql import relation_columns, run_readonly
from messer_common.settings import get_settings
from messer_common.storage import StorageError, get_storage

from ..deps import client_ip, get_db, require_role
from ..errors import ApiError, Forbidden, NotFound
from ..services.knowledge import (
    create_kb,
    delete_blobs,
    delete_file,
    delete_kb,
    enqueue_ingestion,
    ingest_bytes,
    kb_stats,
    update_kb,
)
from ..services.knowledge.chunks import delete_chunk, edit_chunk
from ..services.knowledge.common import api_errors, get_kb, kb_channel, publish_kb_event, record_audit, to_api_error
from ..services.knowledge.files import max_file_bytes
from ..services.knowledge.schemas import (
    ChunkList,
    ChunkOut,
    ChunkUpdate,
    EmbeddingModelOut,
    FileList,
    FileOut,
    KbCreate,
    KbOut,
    KbUpdate,
    QueryIn,
    QueryOut,
    SchemaColumn,
    SchemaOut,
    SchemaRelation,
    SearchHitOut,
    SearchIn,
    SearchOut,
    UploadError,
    UploadResult,
)
from ..services.knowledge.uploads import UPLOAD_OPENAPI, read_files

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])

SEARCH_FUNCTION_SIGNATURES = [
    "kb_vector_search(kb_id uuid, embedding vector, k int)",
    "kb_text_search(kb_id uuid, query text, k int)",
    "kb_hybrid_search(kb_id uuid, query text, embedding vector, k int)",
    "embed('texto') → vector",
]
VIEW_DESCRIPTIONS = {
    "documents": "Archivos de la base de conocimiento",
    "chunks": "Fragmentos indexados (con embedding)",
    "entities": "Registros maestros fusionados",
}


# ---------------------------------------------------------------------------------------------- bases


@router.get("/embedding-models", response_model=list[EmbeddingModelOut])
async def embedding_models(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[EmbeddingModelOut]:
    org = await db.get(Org, principal.org_id)
    residency = org.data_residency if org else "standard"
    default = await emb.default_embedding_model(data_residency=residency)
    return [
        EmbeddingModelOut(**m, default=m["id"] == default) for m in await emb.available_models(data_residency=residency)
    ]


@router.get("", response_model=list[KbOut])
async def list_knowledge_bases(
    project_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> list[KbOut]:
    stmt = select(KnowledgeBase).where(KnowledgeBase.org_id == principal.org_id)
    if principal.project_id is not None:
        stmt = stmt.where(or_(KnowledgeBase.project_id.is_(None), KnowledgeBase.project_id == principal.project_id))
    if project_id is not None:
        stmt = stmt.where(KnowledgeBase.project_id == project_id)
    if q:
        stmt = stmt.where(KnowledgeBase.name.ilike(f"%{q.strip()}%"))
    kbs = list((await db.execute(stmt.order_by(KnowledgeBase.updated_at.desc()))).scalars())
    stats = await kb_stats(db, [k.id for k in kbs])
    return [KbOut.build(k, stats.get(k.id)) for k in kbs]


@router.post("", response_model=KbOut, status_code=201)
async def create_knowledge_base(
    body: KbCreate, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> KbOut:
    with api_errors():
        kb = await create_kb(
            principal,
            name=body.name,
            description=body.description,
            embedding_model=body.embedding_model,
            project_id=body.project_id,
            chunk_size_tokens=body.chunk_size_tokens,
            chunk_overlap_tokens=body.chunk_overlap_tokens,
        )
    fresh = await db.get(KnowledgeBase, kb.id)
    if fresh is None:
        raise NotFound("Base de conocimiento no encontrada")
    return KbOut.build(fresh)


@router.get("/{kb_id}", response_model=KbOut)
async def get_knowledge_base(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> KbOut:
    kb = await get_kb(db, kb_id, principal)
    stats = await kb_stats(db, [kb.id])
    return KbOut.build(kb, stats.get(kb.id))


@router.patch("/{kb_id}", response_model=KbOut)
async def update_knowledge_base(
    kb_id: uuid.UUID,
    body: KbUpdate,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> KbOut:
    kb = await get_kb(db, kb_id, principal)
    changes = body.model_dump(exclude_unset=True)
    if "governance_mode" in changes and principal.role not in ("admin", "owner") and not principal.is_superadmin:
        raise Forbidden("Solo los administradores cambian el modo de gobierno", code="insufficient_role")
    with api_errors():
        kb = await update_kb(db, principal, kb, changes)
    stats = await kb_stats(db, [kb.id])
    await db.refresh(kb)
    return KbOut.build(kb, stats.get(kb.id))


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    await get_kb(db, kb_id, principal)
    with api_errors():
        await delete_kb(principal, kb_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- live events


async def kb_event_stream(kb_id: uuid.UUID) -> AsyncIterator[dict[str, str]]:
    """SSE messages for a knowledge base channel (recent events replayed first)."""
    async for message in subscribe(kb_channel(kb_id)):
        yield {"event": str(message.get("type", "message")), "data": json.dumps(message, default=str)}


@router.get("/{kb_id}/events")
async def knowledge_base_events(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer"))
) -> EventSourceResponse:
    # Short-lived access check: the stream must not hold a database transaction open.
    async with rls_session(principal) as db:
        await get_kb(db, kb_id, principal)
    return EventSourceResponse(kb_event_stream(kb_id), ping=15, headers={"X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------------------------- files


@router.get("/{kb_id}/files", response_model=FileList)
async def list_files(
    kb_id: uuid.UUID,
    status: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> FileList:
    await get_kb(db, kb_id, principal)
    stmt = select(KbFile).where(KbFile.kb_id == kb_id)
    if status == "processing":
        stmt = stmt.where(KbFile.status.notin_(("ready", "error")))
    elif status:
        stmt = stmt.where(KbFile.status == status)
    if q:
        stmt = stmt.where(KbFile.filename.ilike(f"%{q.strip()}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(KbFile.created_at.desc()).limit(limit).offset(offset))).scalars()
    return FileList(items=[FileOut.build(f) for f in rows], total=int(total))


@router.post("/{kb_id}/files", response_model=UploadResult, status_code=201, openapi_extra=UPLOAD_OPENAPI)
async def upload_files(
    kb_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> UploadResult:
    kb = await get_kb(db, kb_id, principal)
    settings = get_settings()
    files, _ = await read_files(
        request, max_file_bytes=max_file_bytes(), max_files=settings.messer_kb_max_files_per_upload
    )
    if not files:
        raise ApiError("Adjunta al menos un archivo", code="no_files")
    created: list[KbFile] = []
    errors: list[UploadError] = []
    try:
        for upload in files:
            try:
                record = await ingest_bytes(
                    db,
                    org_id=kb.org_id,
                    kb_id=kb.id,
                    filename=upload.filename,
                    data=upload.read(),
                    mime=upload.content_type,
                    source="upload",
                    uploaded_by=principal.user_id,
                )
                created.append(record)
            except KnowledgeError as exc:
                errors.append(UploadError(filename=upload.filename, code=exc.code, message=exc.message))
    finally:
        for upload in files:
            upload.close()
    if not created:
        first = errors[0]
        raise ApiError(first.message, code=first.code, details={"errors": [e.model_dump() for e in errors]})
    await record_audit(
        db,
        action="knowledge.file.upload",
        principal=principal,
        entity_type="knowledge_base",
        entity_id=kb.id,
        diff={"files": [{"id": str(f.id), "filename": f.filename, "size": f.size} for f in created]},
        ip=client_ip(request),
    )
    await db.flush()
    for record in created:
        await db.refresh(record)
    return UploadResult(files=[FileOut.build(f) for f in created], errors=errors)


async def _get_file(db: AsyncSession, kb_id: uuid.UUID, file_id: uuid.UUID) -> KbFile:
    record = await db.get(KbFile, file_id)
    if record is None or record.kb_id != kb_id:
        raise NotFound("Archivo no encontrado", code="file_not_found")
    return record


@router.get("/{kb_id}/files/{file_id}", response_model=FileOut)
async def get_file(
    kb_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> FileOut:
    await get_kb(db, kb_id, principal)
    return FileOut.build(await _get_file(db, kb_id, file_id))


@router.get("/{kb_id}/files/{file_id}/download")
async def download_file(
    kb_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    record = await _get_file(db, kb_id, file_id)
    try:
        data = await get_storage().get(record.path)
    except StorageError as exc:
        raise NotFound("El archivo original ya no está disponible", code="blob_missing") from exc
    ascii_name = record.filename.encode("ascii", "replace").decode().replace('"', "")
    return Response(
        content=data,
        media_type=record.mime or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(record.filename)}",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/{kb_id}/files/{file_id}/reprocess", response_model=FileOut)
async def reprocess_file(
    kb_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> FileOut:
    await get_kb(db, kb_id, principal)
    record = await _get_file(db, kb_id, file_id)
    if record.status not in ("ready", "error"):
        raise ApiError("El archivo ya se está procesando", code="file_processing", status_code=409)
    record.status = "queued"
    record.error = None
    await record_audit(
        db, action="knowledge.file.reprocess", principal=principal, entity_type="kb_file", entity_id=record.id
    )
    await db.flush()
    await publish_kb_event(
        kb_id, {"type": "file", "file_id": str(record.id), "filename": record.filename, "status": "queued"}
    )
    await enqueue_ingestion(record.id)
    return FileOut.build(record)


@router.delete("/{kb_id}/files/{file_id}", status_code=204)
async def remove_file(
    kb_id: uuid.UUID,
    file_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    record = await _get_file(db, kb_id, file_id)
    filename = record.filename
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        live = await s.get(KbFile, file_id)
        if kb is None or live is None:
            raise NotFound("Archivo no encontrado", code="file_not_found")
        path = await delete_file(s, kb, live)
        await record_audit(
            s,
            action="knowledge.file.delete",
            principal=principal,
            entity_type="kb_file",
            entity_id=file_id,
            diff={"filename": filename},
        )
    await delete_blobs([path])
    await publish_kb_event(kb_id, {"type": "file_deleted", "file_id": str(file_id)})
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- chunks


@router.get("/{kb_id}/chunks", response_model=ChunkList)
async def list_chunks(
    kb_id: uuid.UUID,
    file_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> ChunkList:
    await get_kb(db, kb_id, principal)
    stmt = select(KbChunk, KbFile.filename).join(KbFile, KbFile.id == KbChunk.file_id).where(KbChunk.kb_id == kb_id)
    if file_id is not None:
        stmt = stmt.where(KbChunk.file_id == file_id)
    if q:
        stmt = stmt.where(KbChunk.content.ilike(f"%{q.strip()}%"))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = await db.execute(
        stmt.order_by(KbFile.created_at.desc(), KbChunk.file_id, KbChunk.ordinal).limit(limit).offset(offset)
    )
    return ChunkList(items=[ChunkOut.build(c, name) for c, name in rows], total=int(total))


async def _get_chunk(db: AsyncSession, kb_id: uuid.UUID, chunk_id: uuid.UUID) -> tuple[KbChunk, str]:
    row = (
        await db.execute(
            select(KbChunk, KbFile.filename)
            .join(KbFile, KbFile.id == KbChunk.file_id)
            .where(KbChunk.id == chunk_id, KbChunk.kb_id == kb_id)
        )
    ).first()
    if row is None:
        raise NotFound("Fragmento no encontrado", code="chunk_not_found")
    return row[0], row[1]


@router.get("/{kb_id}/chunks/{chunk_id}", response_model=ChunkOut)
async def get_chunk(
    kb_id: uuid.UUID,
    chunk_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> ChunkOut:
    await get_kb(db, kb_id, principal)
    chunk, filename = await _get_chunk(db, kb_id, chunk_id)
    return ChunkOut.build(chunk, filename)


@router.patch("/{kb_id}/chunks/{chunk_id}", response_model=ChunkOut)
async def update_chunk(
    kb_id: uuid.UUID,
    chunk_id: uuid.UUID,
    body: ChunkUpdate,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> ChunkOut:
    await get_kb(db, kb_id, principal)
    chunk, filename = await _get_chunk(db, kb_id, chunk_id)
    with api_errors():
        chunk = await edit_chunk(
            db,
            principal,
            chunk,
            content=body.content,
            heading=body.heading,
            heading_set="heading" in body.model_fields_set,
        )
    return ChunkOut.build(chunk, filename)


@router.delete("/{kb_id}/chunks/{chunk_id}", status_code=204)
async def remove_chunk(
    kb_id: uuid.UUID,
    chunk_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    chunk, _ = await _get_chunk(db, kb_id, chunk_id)
    await delete_chunk(db, principal, chunk)
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- search & SQL


async def search_kb(db: AsyncSession, principal: Principal, kb_id: uuid.UUID, body: SearchIn) -> SearchOut:
    kb = await get_kb(db, kb_id, principal)
    started = time.perf_counter()
    role = None if principal.api_key_id else principal.role
    with api_errors():
        hits = await kb_search(db, kb_id=kb.id, query=body.query, mode=body.mode, k=body.k, role=role)
    return SearchOut(
        hits=[SearchHitOut(**h.to_dict()) for h in hits],
        mode=body.mode,
        took_ms=round((time.perf_counter() - started) * 1000, 1),
    )


@router.post("/{kb_id}/search", response_model=SearchOut)
async def search_knowledge_base(
    kb_id: uuid.UUID,
    body: SearchIn,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> SearchOut:
    return await search_kb(db, principal, kb_id, body)


async def query_kb(
    db: AsyncSession, principal: Principal, kb_id: uuid.UUID, body: QueryIn, ip: str | None = None
) -> QueryOut:
    kb = await get_kb(db, kb_id, principal)
    break_glass = body.break_glass is not None
    if break_glass:
        if principal.api_key_id is not None or (
            principal.role not in ("admin", "owner") and not principal.is_superadmin
        ):
            raise Forbidden("Solo un administrador puede usar el acceso de emergencia", code="insufficient_role")
    role = None if principal.api_key_id else principal.role
    try:
        result = await run_readonly(
            kb_id=kb.id,
            sql=body.sql,
            params=body.params,
            limit=body.limit,
            explain=body.explain,
            role=role,
            break_glass=break_glass,
        )
    except KnowledgeError as exc:
        raise to_api_error(exc) from exc
    if break_glass and body.break_glass is not None:
        await record_audit(
            db,
            action="knowledge.break_glass",
            principal=principal,
            entity_type="knowledge_base",
            entity_id=kb.id,
            diff={"reason": body.break_glass.reason, "sql": body.sql[:4000], "rows": result.row_count},
            ip=ip,
        )
    return QueryOut(**result.to_dict())


@router.post("/{kb_id}/query", response_model=QueryOut)
async def query_knowledge_base(
    kb_id: uuid.UUID,
    body: QueryIn,
    request: Request,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> QueryOut:
    return await query_kb(db, principal, kb_id, body, client_ip(request))


@router.get("/{kb_id}/schema", response_model=SchemaOut)
async def knowledge_base_schema(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> SchemaOut:
    """Tables, views and functions available in the SQL console (for autocomplete and the side panel)."""
    kb = await get_kb(db, kb_id, principal)
    tables = {t.name: t for t in (await db.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalars()}
    columns = await relation_columns(kb.schema_name)
    types: dict[str, dict[str, str]] = {
        name: {c["name"]: c["type"] for c in (t.schema_json or {}).get("columns", [])} for name, t in tables.items()
    }
    relations: list[SchemaRelation] = []
    for name in sorted(columns):
        table = tables.get(name)
        kind = "view" if name in VIEW_DESCRIPTIONS else "table"
        relations.append(
            SchemaRelation(
                name=name,
                kind=kind,
                columns=[
                    SchemaColumn(name=c, type=types.get(name, {}).get(c, "integer" if c == "_row_id" else ""))
                    for c in columns[name]
                ],
                row_count=table.row_count if table else None,
                description=VIEW_DESCRIPTIONS.get(name, table.description if table else ""),
            )
        )
    relations.sort(key=lambda r: (r.kind != "table", r.name))
    return SchemaOut(schema_name=kb.schema_name, relations=relations, functions=SEARCH_FUNCTION_SIGNATURES)
