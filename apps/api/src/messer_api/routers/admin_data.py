"""/api/v1/admin/data-requests — GDPR requests from the backoffice (superadmins only).

Superadmins can export or delete any organization, or any person's data account-wide, retry failed
requests and obtain download links. Every action is audited.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import DataRequest, Org, User

from ..deps import require_superadmin
from ..errors import ApiError, NotFound
from ..services import data_requests as gdpr
from .data_requests import DataRequestOut, LinkOut, serialize, submit

router = APIRouter(prefix="/admin/data-requests", tags=["admin"])


class AdminDataRequestIn(BaseModel):
    org_id: uuid.UUID
    kind: Literal["export", "delete"]
    scope: Literal["user", "org"] = "user"
    subject_user_id: uuid.UUID | None = None
    subject_email: EmailStr | None = None


@router.get("", response_model=list[DataRequestOut])
async def list_requests(
    org_id: uuid.UUID | None = None,
    status: str | None = None,
    kind: Literal["export", "delete"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_superadmin()),
) -> list[DataRequestOut]:
    q = select(DataRequest).order_by(DataRequest.created_at.desc()).limit(limit)
    if org_id is not None:
        q = q.where(DataRequest.org_id == org_id)
    if status:
        q = q.where(DataRequest.status == status)
    if kind:
        q = q.where(DataRequest.kind == kind)
    async with system_session() as s:
        rows = list((await s.execute(q)).scalars())
        return await serialize(s, rows)


@router.post("", response_model=DataRequestOut, status_code=201)
async def create_request(
    body: AdminDataRequestIn, principal: Principal = Depends(require_superadmin())
) -> DataRequestOut:
    async with system_session() as s:
        org = await s.get(Org, body.org_id)
        if org is None:
            raise NotFound("Organización no encontrada")
        subject_id: uuid.UUID | None = None
        if body.scope == "user":
            if body.subject_user_id is not None:
                subject = await s.get(User, body.subject_user_id)
            elif body.subject_email is not None:
                subject = (
                    await s.execute(select(User).where(func.lower(User.email) == str(body.subject_email).lower()))
                ).scalar_one_or_none()
            else:
                raise ApiError("Indica la persona (subject_user_id o subject_email)", code="subject_required")
            if subject is None or subject.deleted_at is not None:
                raise NotFound("Persona no encontrada")
            subject_id = subject.id
    actor = Principal(
        user_id=principal.user_id, org_id=body.org_id, role="owner", is_superadmin=True, email=principal.email
    )
    return await submit(
        actor,
        org_id=body.org_id,
        kind=body.kind,
        scope=body.scope,
        subject_user_id=subject_id,
        reach="account" if body.scope == "user" else "org",
    )


@router.get("/{request_id}", response_model=DataRequestOut)
async def get_request(request_id: uuid.UUID, _: Principal = Depends(require_superadmin())) -> DataRequestOut:
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
        if row is None:
            raise NotFound("Solicitud no encontrada")
        return (await serialize(s, [row]))[0]


@router.post("/{request_id}/retry", response_model=DataRequestOut)
async def retry_request(request_id: uuid.UUID, principal: Principal = Depends(require_superadmin())) -> DataRequestOut:
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
        if row is None:
            raise NotFound("Solicitud no encontrada")
        if row.status not in ("failed", "pending"):
            raise ApiError(
                "Solo se pueden reintentar solicitudes fallidas o pendientes", code="not_retryable", status_code=409
            )
        row.status = "pending"
        await audit.record(
            s,
            action="data_request.retried",
            principal=principal,
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
        )
        kind = row.kind
    await gdpr.dispatch(request_id, kind)
    async with system_session() as s:
        fresh = await s.get(DataRequest, request_id)
        assert fresh is not None
        return (await serialize(s, [fresh]))[0]


@router.post("/{request_id}/link", response_model=LinkOut)
async def download_link(request_id: uuid.UUID, principal: Principal = Depends(require_superadmin())) -> LinkOut:
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
        if row is None:
            raise NotFound("Solicitud no encontrada")
        if row.kind != "export" or row.status != "completed" or not row.file_path:
            raise ApiError("La exportación todavía no está lista", code="export_not_ready", status_code=409)
        await audit.record(
            s,
            action="data_request.link_issued",
            principal=principal,
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
        )
        url, expires = gdpr.download_url(row)
    return LinkOut(url=url, expires_at=expires)
