"""/api/v1/knowledge-bases/{kb_id}/tables — structured data: list, schema, rows, cell edits, types, uploads."""

from __future__ import annotations

import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, system_session
from messer_common.db.models import KbFile, KbTable, KnowledgeBase
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.parsing import TABULAR_KINDS, detect_kind

from ..deps import client_ip, get_db, require_role
from ..errors import ApiError, NotFound
from ..services.knowledge import ingest_bytes
from ..services.knowledge.common import api_errors, get_kb, publish_kb_event, record_audit
from ..services.knowledge.files import max_file_bytes
from ..services.knowledge.ingestion import process_file
from ..services.knowledge.schemas import (
    CellUpdate,
    ColumnTypeUpdate,
    RowsColumn,
    RowsOut,
    TableOut,
    TableUpdate,
)
from ..services.knowledge.tables import (
    RowFilter,
    alter_column_type,
    column_types,
    drop_table,
    query_rows,
    table_primary_key,
    update_cell,
)
from ..services.knowledge.uploads import UPLOAD_OPENAPI, read_files

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])

_FILTERS = TypeAdapter(list[dict[str, object]])


async def _get_table(db: AsyncSession, kb_id: uuid.UUID, table_id: uuid.UUID) -> KbTable:
    table = await db.get(KbTable, table_id)
    if table is None or table.kb_id != kb_id:
        raise NotFound("Tabla no encontrada", code="table_not_found")
    return table


@router.get("/{kb_id}/tables", response_model=list[TableOut])
async def list_tables(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[TableOut]:
    await get_kb(db, kb_id, principal)
    rows = (await db.execute(select(KbTable).where(KbTable.kb_id == kb_id).order_by(KbTable.name))).scalars()
    return [TableOut.build(t) for t in rows]


@router.post("/{kb_id}/tables", response_model=list[TableOut], status_code=201, openapi_extra=UPLOAD_OPENAPI)
async def create_tables_from_upload(
    kb_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> list[TableOut]:
    """Create tables from CSV/Excel files synchronously (one table per CSV or sheet)."""
    kb = await get_kb(db, kb_id, principal)
    files, _ = await read_files(request, max_file_bytes=max_file_bytes(), max_files=5)
    if not files:
        raise ApiError("Adjunta un archivo CSV o Excel", code="no_files")
    created: list[uuid.UUID] = []
    try:
        for upload in files:
            with api_errors():
                if detect_kind(upload.filename, upload.content_type) not in TABULAR_KINDS:
                    raise KnowledgeError(
                        f"{upload.filename} no es un CSV ni un Excel",
                        code="not_tabular",
                        details={"filename": upload.filename},
                    )
                async with system_session() as s:
                    record = await ingest_bytes(
                        s,
                        org_id=kb.org_id,
                        kb_id=kb.id,
                        filename=upload.filename,
                        data=upload.read(),
                        mime=upload.content_type,
                        source="upload",
                        uploaded_by=principal.user_id,
                        queue=False,
                    )
                    file_id = record.id
            status = await process_file(file_id)
            async with system_session() as s:
                live = await s.get(KbFile, file_id)
                if status != "ready" or live is None:
                    raise ApiError(
                        (live.error if live else None) or "No se ha podido crear la tabla",
                        code="table_import_failed",
                        details={"filename": upload.filename, "file_id": str(file_id)},
                    )
                created.extend(uuid.UUID(t) for t in (live.meta or {}).get("tables", []))
    finally:
        for upload in files:
            upload.close()
    await record_audit(
        db,
        action="knowledge.table.import",
        principal=principal,
        entity_type="knowledge_base",
        entity_id=kb.id,
        diff={"tables": [str(t) for t in created]},
        ip=client_ip(request),
    )
    rows = (await db.execute(select(KbTable).where(KbTable.id.in_(created)).order_by(KbTable.name))).scalars()
    return [TableOut.build(t) for t in rows]


@router.get("/{kb_id}/tables/{table_id}", response_model=TableOut)
async def get_table(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    await get_kb(db, kb_id, principal)
    return TableOut.build(await _get_table(db, kb_id, table_id))


@router.patch("/{kb_id}/tables/{table_id}", response_model=TableOut)
async def update_table(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    body: TableUpdate,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    await get_kb(db, kb_id, principal)
    table = await _get_table(db, kb_id, table_id)
    table.description = body.description.strip()
    await record_audit(
        db,
        action="knowledge.table.update",
        principal=principal,
        entity_type="kb_table",
        entity_id=table.id,
        diff={"description": table.description},
    )
    await db.flush()
    await db.refresh(table)
    return TableOut.build(table)


@router.delete("/{kb_id}/tables/{table_id}", status_code=204)
async def delete_table(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    table = await _get_table(db, kb_id, table_id)
    name = table.name
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        live = await s.get(KbTable, table_id)
        if kb is None or live is None:
            raise NotFound("Tabla no encontrada", code="table_not_found")
        await drop_table(s, kb, live)
        await record_audit(
            s,
            action="knowledge.table.delete",
            principal=principal,
            entity_type="kb_table",
            entity_id=table_id,
            diff={"name": name},
        )
    await publish_kb_event(kb_id, {"type": "table_deleted", "table_id": str(table_id)})
    return Response(status_code=204)


@router.get("/{kb_id}/tables/{table_id}/rows", response_model=RowsOut)
async def table_rows(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    filters: str | None = Query(default=None, max_length=8000, description='JSON: [{"column","op","value"}]'),
    sort: str | None = Query(default=None, max_length=63),
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> RowsOut:
    kb = await get_kb(db, kb_id, principal)
    table = await _get_table(db, kb_id, table_id)
    parsed: list[RowFilter] = []
    if filters:
        try:
            raw = _FILTERS.validate_python(json.loads(filters))
            for item in raw[:20]:
                parsed.append(RowFilter(column=str(item["column"]), op=str(item["op"]), value=item.get("value")))  # type: ignore[arg-type]
        except (ValueError, KeyError, ValidationError) as exc:
            raise ApiError("Filtros no válidos", code="invalid_filter") from exc
    role = None if principal.api_key_id else principal.role
    with api_errors():
        result, total = await query_rows(
            kb, table, role=role, filters=parsed, sort=sort, order=order, limit=limit, offset=offset
        )
    types = column_types(table)
    pk = set(table_primary_key(table))
    masked: set[str] = set()
    for applied in (result.policy or {}).get("applied", []):
        masked.update((applied.get("masked_columns") or {}).keys())
    return RowsOut(
        columns=[RowsColumn(name=c, type=types.get(c, "text"), pk=c in pk, masked=c in masked) for c in result.columns],
        rows=result.rows,
        total=total,
        limit=limit,
        offset=offset,
        policy=result.policy,
    )


@router.patch("/{kb_id}/tables/{table_id}/rows")
async def edit_cell(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    body: CellUpdate,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    await get_kb(db, kb_id, principal)
    await _get_table(db, kb_id, table_id)
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        table = await s.get(KbTable, table_id)
        if kb is None or table is None:
            raise NotFound("Tabla no encontrada", code="table_not_found")
        with api_errors():
            row = await update_cell(s, kb, table, pk=body.pk, column=body.column, value=body.value)
        await record_audit(
            s,
            action="knowledge.table.cell_update",
            principal=principal,
            entity_type="kb_table",
            entity_id=table_id,
            diff={"table": table.name, "pk": body.pk, "column": body.column, "value": row.get(body.column)},
        )
    return {"row": row}


@router.patch("/{kb_id}/tables/{table_id}/columns/{column}", response_model=TableOut)
async def change_column_type(
    kb_id: uuid.UUID,
    table_id: uuid.UUID,
    column: str,
    body: ColumnTypeUpdate,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> TableOut:
    await get_kb(db, kb_id, principal)
    await _get_table(db, kb_id, table_id)
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        table = await s.get(KbTable, table_id)
        if kb is None or table is None:
            raise NotFound("Tabla no encontrada", code="table_not_found")
        previous = column_types(table).get(column)
        with api_errors():
            table = await alter_column_type(s, kb, table, column, body.type, force=body.force)
        await record_audit(
            s,
            action="knowledge.table.alter_type",
            principal=principal,
            entity_type="kb_table",
            entity_id=table_id,
            diff={"table": table.name, "column": column, "from": previous, "to": body.type, "force": body.force},
        )
        await s.flush()
        await s.refresh(table)
        out = TableOut.build(table)
    return out
