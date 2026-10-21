"""/api/v1/audit-log — immutable, filterable audit trail (admins)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import AuditLog, User

from ..deps import get_db, require_role

router = APIRouter(prefix="/audit-log", tags=["audit"])


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    actor_id: uuid.UUID | None
    actor_email: str | None
    impersonated_by: uuid.UUID | None
    api_key_id: uuid.UUID | None
    entity_type: str | None
    entity_id: str | None
    diff: dict[str, Any]
    ip: str | None


def _query(
    principal: Principal,
    action: str | None,
    actor_id: uuid.UUID | None,
    entity_type: str | None,
    since: datetime | None,
    until: datetime | None,
):  # type: ignore[no-untyped-def]
    q = (
        select(AuditLog, User.email)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.org_id == principal.org_id)
        .order_by(AuditLog.created_at.desc())
    )
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    if actor_id:
        q = q.where(AuditLog.actor_id == actor_id)
    if entity_type:
        q = q.where(AuditLog.entity_type == entity_type)
    if since:
        q = q.where(AuditLog.created_at >= since)
    if until:
        q = q.where(AuditLog.created_at <= until)
    return q


@router.get("", response_model=list[AuditOut])
async def list_audit(
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> list[AuditOut]:
    rows = (
        await db.execute(_query(principal, action, actor_id, entity_type, since, until).limit(limit).offset(offset))
    ).all()
    return [
        AuditOut(
            id=a.id,
            created_at=a.created_at,
            action=a.action,
            actor_id=a.actor_id,
            actor_email=email,
            impersonated_by=a.impersonated_by,
            api_key_id=a.api_key_id,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            diff=a.diff,
            ip=a.ip,
        )
        for a, email in rows
    ]


@router.get("/export.csv")
async def export_audit(
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    rows = (await db.execute(_query(principal, action, None, None, since, until).limit(50000))).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["created_at", "action", "actor_email", "impersonated_by", "entity_type", "entity_id", "ip", "diff"]
    )
    for a, email in rows:
        writer.writerow(
            [
                a.created_at.isoformat(),
                a.action,
                email or "",
                a.impersonated_by or "",
                a.entity_type or "",
                a.entity_id or "",
                a.ip or "",
                a.diff,
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-log.csv"},
    )
