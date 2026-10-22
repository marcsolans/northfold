"""/api/v1/syncs — connector → knowledge base syncs: CRUD, run now, schedule (cron, UTC)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import Connection, KnowledgeBase, Sync
from messer_common.logging import get_logger

from ..deps import get_db, get_org_principal, require_role
from ..errors import ApiError, Conflict, NotFound
from ..services import connector_syncs as sync_svc
from ..services.connections import get_connection
from ..services.connections import record_audit as svc_audit

log = get_logger("messer.api.syncs")

router = APIRouter(prefix="/syncs", tags=["syncs"])


class SyncCreateIn(BaseModel):
    connection_id: uuid.UUID
    kb_id: uuid.UUID
    resource: str = Field(min_length=1, max_length=1000)
    mode: Literal["full", "incremental"] = "full"
    cursor_field: str | None = Field(default=None, max_length=120)
    primary_key: list[str] = Field(default_factory=list, max_length=10)
    schedule: str | None = Field(default=None, max_length=120)
    options: dict[str, Any] = Field(default_factory=dict)
    run_now: bool = False


class SyncUpdateIn(BaseModel):
    kb_id: uuid.UUID | None = None
    resource: str | None = Field(default=None, min_length=1, max_length=1000)
    mode: Literal["full", "incremental"] | None = None
    cursor_field: str | None = Field(default=None, max_length=120)
    primary_key: list[str] | None = Field(default=None, max_length=10)
    schedule: str | None = Field(default=None, max_length=120)
    options: dict[str, Any] | None = None
    reset_cursor: bool = False


def sync_out(sync: Sync, *, connection: Connection | None = None, kb: KnowledgeBase | None = None) -> dict[str, Any]:
    return {
        "id": sync.id,
        "connection_id": sync.connection_id,
        "connection_name": connection.name if connection else None,
        "connector_key": connection.connector_key if connection else None,
        "kb_id": sync.kb_id,
        "kb_name": kb.name if kb else None,
        "resource": sync.resource,
        "mode": sync.mode,
        "cursor_field": sync.cursor_field,
        "cursor": sync.cursor,
        "primary_key": sync.primary_key or [],
        "schedule": sync.schedule,
        "options": sync.options or {},
        "status": sync.status,
        "last_run_at": sync.last_run_at,
        "next_run_at": sync.next_run_at,
        "last_error": sync.last_error,
        "stats": sync.stats or {},
        "created_at": sync.created_at,
        "updated_at": sync.updated_at,
    }


async def _kb(db: AsyncSession, principal: Principal, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != principal.org_id:
        raise NotFound("Base de conocimiento no encontrada", code="kb_not_found")
    return kb


async def _sync(db: AsyncSession, principal: Principal, sync_id: uuid.UUID) -> Sync:
    assert principal.org_id is not None
    sync = await sync_svc.sync_for_api(db, principal.org_id, sync_id)
    if sync is None:
        raise NotFound("Sincronización no encontrada", code="sync_not_found")
    return sync


def _check_mode(connection: Connection, mode: str, cursor_field: str | None) -> None:
    if mode == "incremental" and connection.connector_key in ("postgresql", "mysql", "sqlserver") and not cursor_field:
        raise ApiError(
            "La sincronización incremental de tablas necesita un campo cursor (p. ej. updated_at)",
            code="cursor_field_required",
            status_code=422,
            details={"field": "cursor_field"},
        )


@router.get("")
async def list_syncs(
    connection_id: uuid.UUID | None = None,
    kb_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(get_org_principal),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    q = (
        select(Sync, Connection, KnowledgeBase)
        .join(Connection, Connection.id == Sync.connection_id)
        .join(KnowledgeBase, KnowledgeBase.id == Sync.kb_id)
        .where(Sync.org_id == principal.org_id)
    )
    if connection_id:
        q = q.where(Sync.connection_id == connection_id)
    if kb_id:
        q = q.where(Sync.kb_id == kb_id)
    rows = (await db.execute(q.order_by(Sync.created_at.desc()).limit(limit))).all()
    return [sync_out(s, connection=c, kb=k) for s, c, k in rows]


@router.post("", status_code=201)
async def create_sync(
    body: SyncCreateIn, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    connection = await get_connection(db, principal, body.connection_id)
    kb = await _kb(db, principal, body.kb_id)
    resource = sync_svc.validate_resource(connection, body.resource)
    _check_mode(connection, body.mode, body.cursor_field)
    schedule = sync_svc.validate_schedule(body.schedule)
    sync = Sync(
        org_id=principal.org_id,
        connection_id=connection.id,
        kb_id=kb.id,
        resource=resource,
        mode=body.mode,
        cursor_field=body.cursor_field or None,
        primary_key=[k.strip() for k in body.primary_key if k.strip()],
        schedule=schedule,
        next_run_at=sync_svc.next_run(schedule),
        options=body.options,
        status="queued" if body.run_now else "idle",
    )
    db.add(sync)
    await db.flush()
    await db.refresh(sync)
    await svc_audit(
        db,
        action="sync.created",
        principal=principal,
        entity_type="sync",
        entity_id=sync.id,
        diff={
            "connection_id": connection.id,
            "kb_id": kb.id,
            "resource": resource,
            "mode": body.mode,
            "schedule": schedule,
        },
    )
    if body.run_now:
        sync_svc.enqueue_after_commit(db, sync.id)
    return sync_out(sync, connection=connection, kb=kb)


@router.get("/{sync_id}")
async def get_sync(
    sync_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    sync = await _sync(db, principal, sync_id)
    return sync_out(
        sync, connection=await db.get(Connection, sync.connection_id), kb=await db.get(KnowledgeBase, sync.kb_id)
    )


@router.patch("/{sync_id}")
async def update_sync(
    sync_id: uuid.UUID,
    body: SyncUpdateIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sync = await _sync(db, principal, sync_id)
    connection = await get_connection(db, principal, sync.connection_id)
    fields = body.model_dump(exclude_unset=True)
    if "kb_id" in fields and body.kb_id is not None:
        sync.kb_id = (await _kb(db, principal, body.kb_id)).id
    if body.resource is not None:
        new_resource = sync_svc.validate_resource(connection, body.resource)
        if new_resource != sync.resource:
            sync.cursor = None
        sync.resource = new_resource
    if body.mode is not None:
        sync.mode = body.mode
    if "cursor_field" in fields:
        if (body.cursor_field or None) != sync.cursor_field:
            sync.cursor = None
        sync.cursor_field = body.cursor_field or None
    if body.primary_key is not None:
        sync.primary_key = [k.strip() for k in body.primary_key if k.strip()]
    if "schedule" in fields:
        sync.schedule = sync_svc.validate_schedule(body.schedule)
        sync.next_run_at = sync_svc.next_run(sync.schedule)
    if body.options is not None:
        sync.options = body.options
    if body.reset_cursor:
        sync.cursor = None
    _check_mode(connection, sync.mode, sync.cursor_field)
    sync.updated_at = datetime.now(UTC)
    await svc_audit(
        db,
        action="sync.updated",
        principal=principal,
        entity_type="sync",
        entity_id=sync.id,
        diff={"fields": sorted(fields)},
    )
    await db.flush()
    await db.refresh(sync)
    return sync_out(sync, connection=connection, kb=await db.get(KnowledgeBase, sync.kb_id))


@router.delete("/{sync_id}", status_code=204)
async def delete_sync(
    sync_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> Response:
    sync = await _sync(db, principal, sync_id)
    await svc_audit(
        db,
        action="sync.deleted",
        principal=principal,
        entity_type="sync",
        entity_id=sync.id,
        diff={"resource": sync.resource, "kb_id": sync.kb_id},
    )
    await db.delete(sync)
    return Response(status_code=204)


@router.post("/{sync_id}/run")
async def run_sync_now(
    sync_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    sync = await _sync(db, principal, sync_id)
    if sync.status in ("queued", "running"):
        raise Conflict("La sincronización ya está en cola o en curso", code="sync_busy")
    sync.status = "queued"
    sync.updated_at = datetime.now(UTC)
    await svc_audit(db, action="sync.run_requested", principal=principal, entity_type="sync", entity_id=sync.id)
    await db.flush()
    await db.refresh(sync)
    sync_svc.enqueue_after_commit(db, sync.id)
    return sync_out(
        sync, connection=await db.get(Connection, sync.connection_id), kb=await db.get(KnowledgeBase, sync.kb_id)
    )
