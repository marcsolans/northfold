"""/api/v1/data-requests — GDPR data subject rights (export and verifiable deletion).

* Any member may request the export or deletion of **their own** data (account-wide).
* Admins may request it for a member (limited to this organization's data) and export the organization.
* Only owners may delete the organization, typing its identifier to confirm.
* Export downloads use a signed, expiring link: ``GET /api/v1/data-requests/{id}/download?token=…``.

These endpoints keep working when the organization is in read-only billing state: data rights do not
depend on a subscription.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import AuditLog, DataRequest, Membership, Org, User
from messer_common.logging import get_logger
from messer_common.security import TokenError, verify_signed_payload
from messer_common.storage import StorageError, get_storage

from ..deps import ROLE_RANK, client_ip, require_role
from ..errors import ApiError, Forbidden, NotFound
from ..services import data_requests as gdpr

log = get_logger("messer.api.data_requests")
router = APIRouter(prefix="/data-requests", tags=["data-requests"])


class DataRequestIn(BaseModel):
    kind: Literal["export", "delete"]
    scope: Literal["user", "org"] = "user"
    subject_user_id: uuid.UUID | None = None
    confirm: str | None = Field(default=None, max_length=320)


class PersonOut(BaseModel):
    id: uuid.UUID
    email: str | None
    name: str | None


class DataRequestOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID | None
    org_name: str | None = None
    kind: str
    scope: str
    reach: str
    status: str
    requester: PersonOut | None
    subject: PersonOut | None
    created_at: datetime
    completed_at: datetime | None
    file_ready: bool
    expires_at: str | None
    verified: bool | None
    error: dict[str, Any] | None
    report: dict[str, Any]


class LinkOut(BaseModel):
    url: str
    expires_at: datetime


async def _people(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, PersonOut]:
    if not ids:
        return {}
    rows = await session.execute(select(User.id, User.email, User.name, User.deleted_at).where(User.id.in_(ids)))
    return {
        uid: PersonOut(id=uid, email=None if deleted else email, name=None if deleted else name)
        for uid, email, name, deleted in rows
    }


async def serialize(session: AsyncSession, rows: list[DataRequest]) -> list[DataRequestOut]:
    ids = {r.user_id for r in rows if r.user_id} | {r.subject_user_id for r in rows if r.subject_user_id}
    people = await _people(session, {i for i in ids if i is not None})
    org_ids = {r.org_id for r in rows if r.org_id}
    orgs = (
        {o.id: o.name for o in (await session.execute(select(Org).where(Org.id.in_(org_ids)))).scalars()}
        if org_ids
        else {}
    )
    out: list[DataRequestOut] = []
    for r in rows:
        report = dict(r.report or {})
        deletion = report.get("deletion") or {}
        out.append(
            DataRequestOut(
                id=r.id,
                org_id=r.org_id,
                org_name=orgs.get(r.org_id) if r.org_id else (deletion.get("organization") or {}).get("name"),
                kind=r.kind,
                scope=r.scope,
                reach=gdpr.request_reach(r),
                status=r.status,
                requester=people.get(r.user_id) if r.user_id else None,
                subject=(people.get(r.subject_user_id) or PersonOut(id=r.subject_user_id, email=None, name=None))
                if r.subject_user_id
                else None,
                created_at=r.created_at,
                completed_at=r.completed_at,
                file_ready=r.kind == "export" and r.status == "completed" and bool(r.file_path),
                expires_at=report.get("expires_at"),
                verified=deletion.get("verified") if r.kind == "delete" and deletion else None,
                error=report.get("error"),
                report=report,
            )
        )
    return out


def _is_admin(principal: Principal) -> bool:
    return principal.is_superadmin or ROLE_RANK.get(principal.role or "", 0) >= ROLE_RANK["admin"]


def _can_read(principal: Principal, req: DataRequest) -> bool:
    if principal.user_id is not None and principal.user_id in (req.user_id, req.subject_user_id):
        return True
    return req.org_id == principal.org_id and _is_admin(principal)


def _can_download(principal: Principal, req: DataRequest) -> bool:
    if principal.is_superadmin or (principal.user_id is not None and principal.user_id == req.user_id):
        return True
    if principal.user_id is not None and principal.user_id == req.subject_user_id:
        return True
    # Admins can download organization-reach exports of their organization, never someone's account-wide export.
    return req.org_id == principal.org_id and _is_admin(principal) and gdpr.request_reach(req) == "org"


async def _subject_in_org(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    member = (
        await session.execute(select(Membership.id).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).first()
    if member is not None:
        return True
    acted = (
        await session.execute(
            select(AuditLog.id).where(AuditLog.org_id == org_id, AuditLog.actor_id == user_id).limit(1)
        )
    ).first()
    return acted is not None


async def submit(
    requester: Principal, *, org_id: uuid.UUID, kind: str, scope: str, subject_user_id: uuid.UUID | None, reach: str
) -> DataRequestOut:
    """Create (committed) and dispatch a request; returns its serialized state."""
    async with system_session() as s:
        req = await gdpr.create_request(
            s, org_id=org_id, requester=requester, kind=kind, scope=scope, subject_user_id=subject_user_id, reach=reach
        )
        req_id = req.id
    try:
        await gdpr.dispatch(req_id, kind)
    except Exception as exc:  # queue unavailable: leave a visible failure the backoffice can retry
        log.error("data_request.enqueue_failed", request_id=str(req_id), error=str(exc))
        async with system_session() as s:
            row = await s.get(DataRequest, req_id)
            if row is not None:
                row.status = "failed"
                row.report = {**(row.report or {}), "error": {"code": "queue_unavailable", "message": str(exc)[:300]}}
    async with system_session() as s:
        row = await s.get(DataRequest, req_id)
        assert row is not None
        return (await serialize(s, [row]))[0]


@router.get("", response_model=list[DataRequestOut])
async def list_requests(principal: Principal = Depends(require_role("viewer"))) -> list[DataRequestOut]:
    if not _is_admin(principal):
        raise Forbidden("Necesitas el rol admin o superior", code="insufficient_role")
    async with system_session() as s:
        rows = list(
            (
                await s.execute(
                    select(DataRequest)
                    .where(DataRequest.org_id == principal.org_id)
                    .order_by(DataRequest.created_at.desc())
                    .limit(200)
                )
            ).scalars()
        )
        return await serialize(s, rows)


@router.get("/mine", response_model=list[DataRequestOut])
async def my_requests(principal: Principal = Depends(require_role("viewer"))) -> list[DataRequestOut]:
    async with system_session() as s:
        rows = list(
            (
                await s.execute(
                    select(DataRequest)
                    .where(DataRequest.scope == "user", DataRequest.subject_user_id == principal.user_id)
                    .order_by(DataRequest.created_at.desc())
                    .limit(50)
                )
            ).scalars()
        )
        return await serialize(s, rows)


@router.post("", response_model=DataRequestOut, status_code=201)
async def create_request(body: DataRequestIn, principal: Principal = Depends(require_role("viewer"))) -> DataRequestOut:
    assert principal.org_id is not None
    if principal.api_key_id is not None or principal.user_id is None:
        raise Forbidden("Las solicitudes de datos requieren una sesión de usuario", code="user_session_required")
    if principal.impersonated_by is not None and body.kind == "delete":
        raise Forbidden("No se pueden solicitar borrados durante una suplantación", code="impersonation")
    async with system_session() as s:
        org = await s.get(Org, principal.org_id)
        if org is None:
            raise NotFound("Organización no encontrada")
        if body.scope == "org":
            if body.kind == "export" and not _is_admin(principal):
                raise Forbidden("Necesitas el rol admin para exportar la organización", code="insufficient_role")
            if body.kind == "delete":
                if principal.role != "owner" and not principal.is_superadmin:
                    raise Forbidden("Solo un propietario puede eliminar la organización", code="insufficient_role")
                if (body.confirm or "").strip() != org.slug:
                    raise ApiError(f"Escribe «{org.slug}» para confirmar la eliminación", code="confirmation_mismatch")
            subject_id: uuid.UUID | None = None
            reach = "org"
        else:
            subject_id = body.subject_user_id or principal.user_id
            subject = await s.get(User, subject_id)
            if subject is None or subject.deleted_at is not None:
                raise NotFound("Persona no encontrada")
            if subject_id == principal.user_id:
                reach = "account"
            else:
                if not _is_admin(principal):
                    raise Forbidden("Solo un admin puede solicitarlo para otra persona", code="insufficient_role")
                if not await _subject_in_org(s, principal.org_id, subject_id):
                    raise NotFound("Esa persona no tiene datos en esta organización")
                reach = "org"
            if body.kind == "delete" and (body.confirm or "").strip().lower() != subject.email.lower():
                raise ApiError(f"Escribe «{subject.email}» para confirmar el borrado", code="confirmation_mismatch")
    return await submit(
        principal, org_id=principal.org_id, kind=body.kind, scope=body.scope, subject_user_id=subject_id, reach=reach
    )


async def _load(request_id: uuid.UUID) -> DataRequest:
    async with system_session() as s:
        row = await s.get(DataRequest, request_id)
    if row is None:
        raise NotFound("Solicitud no encontrada")
    return row


@router.get("/{request_id}", response_model=DataRequestOut)
async def get_request(request_id: uuid.UUID, principal: Principal = Depends(require_role("viewer"))) -> DataRequestOut:
    row = await _load(request_id)
    if not _can_read(principal, row):
        raise NotFound("Solicitud no encontrada")
    async with system_session() as s:
        return (await serialize(s, [row]))[0]


@router.post("/{request_id}/link", response_model=LinkOut)
async def download_link(request_id: uuid.UUID, principal: Principal = Depends(require_role("viewer"))) -> LinkOut:
    row = await _load(request_id)
    if not _can_read(principal, row):
        raise NotFound("Solicitud no encontrada")
    if not _can_download(principal, row):
        raise Forbidden("Solo quien la solicitó puede descargar esta exportación", code="not_requester")
    if row.kind != "export" or row.status != "completed" or not row.file_path:
        raise ApiError("La exportación todavía no está lista", code="export_not_ready", status_code=409)
    url, expires = gdpr.download_url(row)
    return LinkOut(url=url, expires_at=expires)


@router.get("/{request_id}/download")
async def download(request_id: uuid.UUID, request: Request, token: str = "") -> Response:
    """Public (signed link from the email or the UI)."""
    try:
        claims = verify_signed_payload(token)
    except TokenError as exc:
        raise ApiError(
            "El enlace de descarga no es válido o ha caducado", code="invalid_link", status_code=410
        ) from exc
    if claims.get("purpose") != "data_export" or claims.get("dr") != str(request_id):
        raise ApiError("El enlace de descarga no es válido", code="invalid_link", status_code=410)
    row = await _load(request_id)
    if row.kind != "export" or row.status != "completed" or not row.file_path:
        raise ApiError("La exportación ya no está disponible", code="export_unavailable", status_code=410)
    try:
        data = await get_storage().get(row.file_path)
    except StorageError as exc:
        raise ApiError("La exportación ya no está disponible", code="export_unavailable", status_code=410) from exc
    async with system_session() as s:
        await audit.record(
            s,
            action="data_request.downloaded",
            org_id=row.org_id,
            entity_type="data_request",
            entity_id=row.id,
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    stamp = (row.completed_at or row.created_at).strftime("%Y%m%d")
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="messer-export-{stamp}-{str(row.id)[:8]}.zip"',
            "Cache-Control": "no-store",
        },
    )
