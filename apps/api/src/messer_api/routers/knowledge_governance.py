"""/api/v1/knowledge-bases/{kb_id} — policies, entity resolution and backups."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, system_session
from messer_common.db.models import KbBackup, KbEntity, KbPolicy
from messer_common.queue import Jobs, enqueue

from ..deps import get_db, require_role
from ..errors import ApiError, NotFound
from ..services.knowledge.common import api_errors, get_kb, record_audit
from ..services.knowledge.entities import dismiss, merge
from ..services.knowledge.files import delete_blobs
from ..services.knowledge.policies import validate_policy
from ..services.knowledge.schemas import (
    BackupOut,
    EntityList,
    EntityOut,
    MergeIn,
    PolicyIn,
    PolicyOut,
    Queued,
)

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge"])


# ---------------------------------------------------------------------------------------------- policies


@router.get("/{kb_id}/policies", response_model=list[PolicyOut])
async def list_policies(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[PolicyOut]:
    await get_kb(db, kb_id, principal)
    rows = (
        await db.execute(select(KbPolicy).where(KbPolicy.kb_id == kb_id).order_by(KbPolicy.table, KbPolicy.role))
    ).scalars()
    return [PolicyOut.build(p) for p in rows]


@router.post("/{kb_id}/policies", response_model=PolicyOut, status_code=201)
async def create_policy(
    kb_id: uuid.UUID,
    body: PolicyIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyOut:
    kb = await get_kb(db, kb_id, principal)
    with api_errors():
        row_filter, masks = await validate_policy(
            db,
            kb,
            table=body.table,
            role=body.role,
            row_filter_sql=body.row_filter_sql,
            masked_columns=body.masked_columns,
        )
    policy = KbPolicy(
        org_id=kb.org_id,
        kb_id=kb.id,
        table=body.table,
        role=body.role,
        row_filter_sql=row_filter,
        masked_columns=masks,
        compliance_tags=[t.strip() for t in body.compliance_tags if t.strip()],
        break_glass=body.break_glass,
        enabled=body.enabled,
    )
    db.add(policy)
    await db.flush()
    await record_audit(
        db,
        action="knowledge.policy.create",
        principal=principal,
        entity_type="kb_policy",
        entity_id=policy.id,
        diff=body.model_dump(),
    )
    await db.refresh(policy)
    return PolicyOut.build(policy)


async def _get_policy(db: AsyncSession, kb_id: uuid.UUID, policy_id: uuid.UUID) -> KbPolicy:
    policy = await db.get(KbPolicy, policy_id)
    if policy is None or policy.kb_id != kb_id:
        raise NotFound("Política no encontrada", code="policy_not_found")
    return policy


@router.put("/{kb_id}/policies/{policy_id}", response_model=PolicyOut)
async def replace_policy(
    kb_id: uuid.UUID,
    policy_id: uuid.UUID,
    body: PolicyIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> PolicyOut:
    kb = await get_kb(db, kb_id, principal)
    policy = await _get_policy(db, kb_id, policy_id)
    before = PolicyOut.build(policy).model_dump(mode="json")
    with api_errors():
        row_filter, masks = await validate_policy(
            db,
            kb,
            table=body.table,
            role=body.role,
            row_filter_sql=body.row_filter_sql,
            masked_columns=body.masked_columns,
        )
    policy.table = body.table
    policy.role = body.role
    policy.row_filter_sql = row_filter
    policy.masked_columns = masks
    policy.compliance_tags = [t.strip() for t in body.compliance_tags if t.strip()]
    policy.break_glass = body.break_glass
    policy.enabled = body.enabled
    await record_audit(
        db,
        action="knowledge.policy.update",
        principal=principal,
        entity_type="kb_policy",
        entity_id=policy.id,
        diff={"before": before, "after": body.model_dump()},
    )
    await db.flush()
    await db.refresh(policy)
    return PolicyOut.build(policy)


@router.delete("/{kb_id}/policies/{policy_id}", status_code=204)
async def delete_policy(
    kb_id: uuid.UUID,
    policy_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    policy = await _get_policy(db, kb_id, policy_id)
    snapshot = PolicyOut.build(policy).model_dump(mode="json")
    await db.delete(policy)
    await record_audit(
        db,
        action="knowledge.policy.delete",
        principal=principal,
        entity_type="kb_policy",
        entity_id=policy_id,
        diff=snapshot,
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------- entities


@router.get("/{kb_id}/entities", response_model=EntityList)
async def list_entities(
    kb_id: uuid.UUID,
    status: str | None = Query(default="suggested", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("viewer")),
    db: AsyncSession = Depends(get_db),
) -> EntityList:
    await get_kb(db, kb_id, principal)
    stmt = select(KbEntity).where(KbEntity.kb_id == kb_id)
    if status and status != "all":
        stmt = stmt.where(KbEntity.status == status)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(stmt.order_by(KbEntity.score.desc(), KbEntity.created_at.desc()).limit(limit).offset(offset))
    ).scalars()
    return EntityList(items=[EntityOut.build(e) for e in rows], total=int(total))


@router.post("/{kb_id}/entities/run", response_model=Queued, status_code=202)
async def run_entities(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> Queued:
    kb = await get_kb(db, kb_id, principal)
    await enqueue(Jobs.ENTITY_RESOLUTION, str(kb.id), _job_id=f"entities:{kb.id}:{uuid.uuid4().hex[:8]}")
    await record_audit(
        db, action="knowledge.entities.run", principal=principal, entity_type="knowledge_base", entity_id=kb.id
    )
    return Queued(job=Jobs.ENTITY_RESOLUTION)


async def _get_entity(db: AsyncSession, kb_id: uuid.UUID, entity_id: uuid.UUID) -> KbEntity:
    entity = await db.get(KbEntity, entity_id)
    if entity is None or entity.kb_id != kb_id:
        raise NotFound("Sugerencia no encontrada", code="entity_not_found")
    return entity


@router.post("/{kb_id}/entities/{entity_id}/merge", response_model=EntityOut)
async def merge_entity(
    kb_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: MergeIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> EntityOut:
    await get_kb(db, kb_id, principal)
    entity = await _get_entity(db, kb_id, entity_id)
    if entity.status != "suggested":
        raise ApiError("Esta sugerencia ya se ha resuelto", code="entity_decided", status_code=409)
    merge(entity, golden=body.golden_record, decided_by=principal.user_id)
    await record_audit(
        db,
        action="knowledge.entity.merge",
        principal=principal,
        entity_type="kb_entity",
        entity_id=entity.id,
        diff={"match_key": entity.match_key, "records": entity.records, "golden_record": entity.golden_record},
    )
    await db.flush()
    await db.refresh(entity)
    return EntityOut.build(entity)


@router.post("/{kb_id}/entities/{entity_id}/dismiss", response_model=EntityOut)
async def dismiss_entity(
    kb_id: uuid.UUID,
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> EntityOut:
    await get_kb(db, kb_id, principal)
    entity = await _get_entity(db, kb_id, entity_id)
    if entity.status != "suggested":
        raise ApiError("Esta sugerencia ya se ha resuelto", code="entity_decided", status_code=409)
    dismiss(entity, decided_by=principal.user_id)
    await record_audit(
        db,
        action="knowledge.entity.dismiss",
        principal=principal,
        entity_type="kb_entity",
        entity_id=entity.id,
        diff={"match_key": entity.match_key},
    )
    await db.flush()
    await db.refresh(entity)
    return EntityOut.build(entity)


# ---------------------------------------------------------------------------------------------- backups


@router.get("/{kb_id}/backups", response_model=list[BackupOut])
async def list_backups(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[BackupOut]:
    await get_kb(db, kb_id, principal)
    rows = (
        await db.execute(select(KbBackup).where(KbBackup.kb_id == kb_id).order_by(KbBackup.created_at.desc()))
    ).scalars()
    return [BackupOut.build(b) for b in rows]


@router.post("/{kb_id}/backups", response_model=BackupOut, status_code=202)
async def create_backup(
    kb_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> BackupOut:
    kb = await get_kb(db, kb_id, principal)
    running = (
        await db.execute(
            select(func.count()).where(
                KbBackup.kb_id == kb.id, KbBackup.status.in_(("pending", "running", "restoring"))
            )
        )
    ).scalar_one()
    if running:
        raise ApiError("Ya hay una copia o restauración en curso", code="backup_in_progress", status_code=409)
    backup = KbBackup(org_id=kb.org_id, kb_id=kb.id, path="", size=0, status="pending", created_by=principal.user_id)
    db.add(backup)
    await db.flush()
    await record_audit(
        db, action="knowledge.backup.create", principal=principal, entity_type="kb_backup", entity_id=backup.id
    )
    await enqueue(Jobs.KB_BACKUP, str(backup.id), _job_id=f"kb-backup:{backup.id}")
    await db.refresh(backup)
    return BackupOut.build(backup)


async def _get_backup(db: AsyncSession, kb_id: uuid.UUID, backup_id: uuid.UUID) -> KbBackup:
    backup = await db.get(KbBackup, backup_id)
    if backup is None or backup.kb_id != kb_id:
        raise NotFound("Copia no encontrada", code="backup_not_found")
    return backup


@router.post("/{kb_id}/backups/{backup_id}/restore", response_model=BackupOut, status_code=202)
async def restore_backup(
    kb_id: uuid.UUID,
    backup_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> BackupOut:
    await get_kb(db, kb_id, principal)
    backup = await _get_backup(db, kb_id, backup_id)
    if backup.status != "ready":
        raise ApiError("La copia todavía no está lista", code="backup_not_ready", status_code=409)
    backup.status = "restoring"
    await record_audit(
        db, action="knowledge.backup.restore", principal=principal, entity_type="kb_backup", entity_id=backup.id
    )
    await db.flush()
    await enqueue(Jobs.KB_RESTORE, str(backup.id), _job_id=f"kb-restore:{backup.id}:{uuid.uuid4().hex[:8]}")
    return BackupOut.build(backup)


@router.delete("/{kb_id}/backups/{backup_id}", status_code=204)
async def delete_backup(
    kb_id: uuid.UUID,
    backup_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await get_kb(db, kb_id, principal)
    backup = await _get_backup(db, kb_id, backup_id)
    if backup.status in ("running", "restoring"):
        raise ApiError("No se puede borrar una copia en curso", code="backup_in_progress", status_code=409)
    path = backup.path
    async with system_session() as s:
        live = await s.get(KbBackup, backup_id)
        if live is not None:
            await s.delete(live)
        await record_audit(
            s, action="knowledge.backup.delete", principal=principal, entity_type="kb_backup", entity_id=backup_id
        )
    if path:
        await delete_blobs([path])
    return Response(status_code=204)
