"""Git smart HTTP for project repositories: ``/api/v1/orgs/{org_id}/projects/{project_id}/git``.

``git clone|fetch|push https://<api>/api/v1/orgs/<org>/projects/<project>/git``. Credentials: HTTP Basic with an
API key or OAuth token (``msr_…``) or a session access token as the password (what ``messer credential-helper``
sends), or ``Authorization: Bearer``. Fetching needs the viewer role, pushing the builder role; project-scoped
keys only reach their project. A push to the default branch is merged into the project like a GitHub pull
(see :mod:`messer_api.services.git_push`).
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select

from messer_common.db import Principal, system_session
from messer_common.db.models import Membership, Project, User
from messer_common.projects_repo import ProjectRepo
from messer_common.roles import at_least
from messer_common.security import TokenError, decode_access_token

from ..deps import _principal_from_api_key, org_billing_state
from ..errors import ApiError
from ..services import git_http as proto
from ..services.git_push import apply_push, default_branch

router = APIRouter(prefix="/orgs/{org_id}/projects/{project_id}/git", tags=["git"], include_in_schema=False)

NO_CACHE = {"Cache-Control": "no-cache, max-age=0, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
Service = Literal["git-upload-pack", "git-receive-pack"]


class GitHttpError(Exception):
    def __init__(self, status: int, message: str, *, challenge: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.challenge = challenge

    def response(self) -> Response:
        headers = dict(NO_CACHE)
        if self.challenge:
            headers["WWW-Authenticate"] = 'Basic realm="Messer", charset="UTF-8"'
        # git prints text/plain error bodies as "remote: …" lines.
        return Response(self.message + "\n", status_code=self.status, media_type="text/plain", headers=headers)


def _credential(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    value = value.strip()
    if scheme.lower() == "bearer" and value:
        return value
    if scheme.lower() == "basic" and value:
        try:
            decoded = base64.b64decode(value, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            return None
        _user, _, password = decoded.partition(":")
        return password.strip() or None
    return None


async def _session_principal(token: str, org_id: uuid.UUID) -> Principal:
    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(str(claims["sub"]))
    except (TokenError, KeyError, ValueError) as exc:
        raise GitHttpError(401, "Credenciales no válidas para Messer", challenge=True) from exc
    impersonated_by = uuid.UUID(claims["imp"]) if claims.get("imp") else None
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None or user.deleted_at is not None or user.status == "blocked":
            raise GitHttpError(401, "Credenciales no válidas para Messer", challenge=True)
        role = (
            await s.execute(select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user.id))
        ).scalar_one_or_none()
        superadmin = user.is_superadmin and impersonated_by is None
        if role is None and not superadmin:
            raise GitHttpError(404, "Repositorio no encontrado")
        return Principal(
            user_id=user.id,
            org_id=org_id,
            role=role or "owner",
            is_superadmin=superadmin,
            email=user.email,
            impersonated_by=impersonated_by,
            mfa_verified=claims.get("aal") == "aal2",
        )


async def authorize(request: Request, org_id: uuid.UUID, project_id: uuid.UUID, service: Service) -> Principal:
    token = _credential(request)
    if not token:
        raise GitHttpError(401, "Autenticación necesaria: usa una API key de Messer como contraseña", challenge=True)
    if token.startswith("msr_"):
        try:
            principal = await _principal_from_api_key(token)
        except ApiError as exc:
            raise GitHttpError(401, exc.message, challenge=True) from exc
        if principal.org_id != org_id:
            raise GitHttpError(404, "Repositorio no encontrado")
    else:
        principal = await _session_principal(token, org_id)
    if principal.project_id is not None and principal.project_id != project_id:
        raise GitHttpError(403, "La API key está limitada a otro proyecto")
    async with system_session() as s:
        project = await s.get(Project, project_id)
    if project is None or project.org_id != org_id or project.archived_at is not None:
        raise GitHttpError(404, "Repositorio no encontrado")
    if not ProjectRepo.for_project(str(project_id)).exists:
        raise GitHttpError(404, "Repositorio no encontrado")
    if service == "git-receive-pack":
        if not principal.is_superadmin and not at_least(principal.role, "builder"):
            raise GitHttpError(403, "Necesitas el rol builder para enviar cambios (push)")
        if principal.api_key_id is not None and principal.scopes and "projects:write" not in principal.scopes:
            raise GitHttpError(403, "La API key no tiene el permiso projects:write")
        state = await org_billing_state(org_id)
        if state["blocked"] and not principal.is_superadmin:
            raise GitHttpError(403, "Esta organización está bloqueada. Contacta con soporte.")
        if state["read_only"]:
            raise GitHttpError(403, "Tu organización está en modo solo lectura. Elige un plan para continuar.")
    elif (
        principal.api_key_id is not None
        and principal.scopes
        and not ({"projects:read", "projects:write"} & set(principal.scopes))
    ):
        raise GitHttpError(403, "La API key no tiene el permiso projects:read")
    return principal


@router.get("/info/refs")
async def info_refs(org_id: uuid.UUID, project_id: uuid.UUID, request: Request, service: str = "") -> Response:
    if service not in ("git-upload-pack", "git-receive-pack"):
        return GitHttpError(403, "Messer solo admite el protocolo smart HTTP de git").response()
    try:
        await authorize(request, org_id, project_id, service)  # type: ignore[arg-type]
    except GitHttpError as exc:
        return exc.response()
    repo = ProjectRepo.for_project(str(project_id))
    try:
        if service == "git-upload-pack":
            body = await proto.upload_pack_advertisement(repo, proto.git_protocol(request.headers.get("git-protocol")))
        else:
            body = await proto.receive_pack_advertisement(repo, await default_branch(repo))
    except (proto.GitProtocolError, TimeoutError):
        return GitHttpError(500, "Error interno del repositorio").response()
    return Response(body, media_type=f"application/x-{service}-advertisement", headers=NO_CACHE)


def _gzip(request: Request) -> bool:
    return request.headers.get("content-encoding", "").lower() in ("gzip", "x-gzip")


@router.post("/git-upload-pack")
async def git_upload_pack(org_id: uuid.UUID, project_id: uuid.UUID, request: Request) -> Response:
    try:
        await authorize(request, org_id, project_id, "git-upload-pack")
    except GitHttpError as exc:
        return exc.response()
    try:
        body = await proto.read_body(request.stream(), gzip=_gzip(request), limit=proto.MAX_FETCH_REQUEST_BYTES)
    except proto.BodyTooLarge:
        return GitHttpError(413, "Petición demasiado grande").response()
    except proto.GitProtocolError as exc:
        return GitHttpError(400, str(exc)).response()
    repo = ProjectRepo.for_project(str(project_id))
    stream = proto.upload_pack(repo, body or b"", proto.git_protocol(request.headers.get("git-protocol")))
    return StreamingResponse(stream, media_type="application/x-git-upload-pack-result", headers=NO_CACHE)


@router.post("/git-receive-pack")
async def git_receive_pack(org_id: uuid.UUID, project_id: uuid.UUID, request: Request) -> Response:
    try:
        principal = await authorize(request, org_id, project_id, "git-receive-pack")
    except GitHttpError as exc:
        return exc.response()
    try:
        spool = await proto.spool_body(request.stream(), gzip=_gzip(request))
    except proto.BodyTooLarge:
        return GitHttpError(413, "El push supera 200 MB").response()
    except proto.GitProtocolError as exc:
        return GitHttpError(400, str(exc)).response()
    media = "application/x-git-receive-pack-result"
    try:
        try:
            req = proto.parse_receive_request(spool)
        except proto.GitProtocolError as exc:
            return GitHttpError(400, f"Petición git no válida: {exc}").response()
        if not req.updates:
            return Response(b"", media_type=media, headers=NO_CACHE)
        caps = req.capabilities
        sideband = "side-band-64k" in caps or "side-band" in caps
        unpack_error: str | None = None
        repo = ProjectRepo.for_project(str(project_id))
        quarantine: proto.Quarantine | None = None
        started = datetime.now(UTC)
        try:
            if req.shallow:
                report = proto.empty_report(
                    req, "Messer no acepta pushes desde un clon superficial (git fetch --unshallow)"
                )
            else:
                if any(u.new != proto.ZERO_SHA for u in req.updates):
                    quarantine = proto.Quarantine.create(repo)
                    unpack_error = await proto.index_pack(quarantine, spool, req.pack_offset)
                if unpack_error is not None:
                    report = proto.empty_report(req, "unpacker error")
                else:
                    report = await apply_push(
                        project_id,
                        principal,
                        req.updates,
                        atomic="atomic" in caps,
                        object_env=quarantine.env() if quarantine else None,
                        on_accepted=quarantine.migrate if quarantine else None,
                    )
        finally:
            if quarantine is not None:
                quarantine.remove()
        proto.log.info(
            "git.receive_pack",
            project_id=str(project_id),
            refs=[r.ref for r in report.results],
            rejected=[r.ref for r in report.results if r.error],
            ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
        )
        if "report-status" not in caps:
            return Response(b"", media_type=media, headers=NO_CACHE)
        body = proto.report_status(
            report.results, unpack_error=unpack_error, sideband=sideband, messages=report.messages
        )
        return Response(body, media_type=media, headers=NO_CACHE)
    finally:
        spool.close()
