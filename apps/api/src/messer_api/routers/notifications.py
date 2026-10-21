"""/api/v1/notifications — in-app notifications (bell) for the current user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.db.models import Notification

from ..deps import get_db, get_org_principal
from ..errors import NotFound

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    channel: str
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int


@router.get("", response_model=NotificationList)
async def list_notifications(
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False,
    principal: Principal = Depends(get_org_principal),
    db: AsyncSession = Depends(get_db),
) -> NotificationList:
    q = select(Notification).where(Notification.user_id == principal.user_id, Notification.org_id == principal.org_id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = (await db.execute(q.order_by(Notification.created_at.desc()).limit(limit))).scalars().all()
    unread = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == principal.user_id,
                Notification.org_id == principal.org_id,
                Notification.read_at.is_(None),
            )
        )
    ).scalar_one()
    return NotificationList(
        items=[NotificationOut.model_validate(r, from_attributes=True) for r in rows], unread=int(unread)
    )


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    row = await db.get(Notification, notification_id)
    if row is None or row.user_id != principal.user_id:
        raise NotFound("Notificación no encontrada")
    row.read_at = row.read_at or datetime.now(UTC)
    return {"ok": True}


@router.post("/read-all")
async def mark_all_read(
    principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id == principal.user_id,
            Notification.org_id == principal.org_id,
            Notification.read_at.is_(None),
        )
        .values(read_at=datetime.now(UTC))
    )
    return {"ok": True}
