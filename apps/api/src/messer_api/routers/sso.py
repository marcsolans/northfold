"""/api/v1/sso — enterprise SSO (OIDC + SAML 2.0), verified domains, group mappings and SCIM tokens.

Public endpoints (browser flow): ``POST /sso/discover``, ``GET /sso/connections/{id}/start``,
``GET /sso/oidc/callback``, ``POST /sso/saml/{id}/acs``, ``GET /sso/saml/{id}/metadata``.
Everything else is for organization admins and gated by the plan features ``sso`` (Business+) and
``scim`` (Enterprise).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import Membership, OneTimeToken, ScimToken, SsoConnection, SsoGroupMapping, User
from messer_common.db.models.enterprise import OrgDomain, OrgIdentity
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.security import hash_token, random_token, sign_payload
from messer_common.settings import get_settings

from ..deps import client_ip, get_db, get_optional_principal, require_role
from ..errors import ApiError, Conflict, NotFound
from ..ratelimit import rate_limit
from ..services import auth as auth_service
from ..services import limits
from ..services import sso as sso_service
from ..services.scim import base_url as scim_base_url
from ..services.sso_oidc import (
    OidcConfig,
    SsoIdentity,
    SsoProtocolError,
    authorization_url,
    exchange_code,
    fetch_userinfo,
    identity_from_claims,
    pkce_pair,
    provider_metadata,
    redirect_uri,
    validate_id_token,
)
from ..services.sso_saml import (
    SamlConfig,
    acs_url,
    authn_request_url,
    certificate_info,
    metadata_url,
    new_request_id,
    process_response,
    sp_entity_id,
    sp_metadata_xml,
)
from .auth import set_session_cookies

log = get_logger("messer.api.sso")
router = APIRouter(prefix="/sso", tags=["sso"])

STATE_TTL = timedelta(minutes=10)
TEST_RESULT_TTL_S = 900
AssignableRole = Literal["admin", "builder", "viewer"]


# ----------------------------------------------------------------------------- schemas


class DiscoverIn(BaseModel):
    email: EmailStr
    next: str | None = Field(default=None, max_length=500)


class DiscoverOut(BaseModel):
    redirect_url: str
    connection_name: str
    type: str


class ConnectionIn(BaseModel):
    type: Literal["oidc", "saml"]
    name: str = Field(min_length=1, max_length=200)
    domain: str = Field(min_length=3, max_length=255)
    default_role: AssignableRole = "viewer"
    enforce: bool = False
    enabled: bool = True
    config: dict[str, Any]


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    domain: str | None = Field(default=None, min_length=3, max_length=255)
    default_role: AssignableRole | None = None
    enforce: bool | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class ConnectionOut(BaseModel):
    id: uuid.UUID
    type: str
    name: str
    domain: str
    domain_verified: bool
    default_role: str
    enforce: bool
    enabled: bool
    config: dict[str, Any]
    service_provider: dict[str, str]
    login_url: str
    mappings: int
    created_at: datetime
    updated_at: datetime


class MappingIn(BaseModel):
    external_group: str = Field(min_length=1, max_length=255)
    role: AssignableRole


class MappingOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    external_group: str
    role: str


class DomainIn(BaseModel):
    domain: str = Field(min_length=3, max_length=255)


class DomainOut(BaseModel):
    id: uuid.UUID
    domain: str
    verified_at: datetime | None
    verification_method: str | None
    last_checked_at: datetime | None
    record: dict[str, str]
    created_at: datetime


class VerifyIn(BaseModel):
    manual: bool = False


class ScimTokenIn(BaseModel):
    name: str = Field(default="SCIM", min_length=1, max_length=200)


class ScimTokenOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ScimTokenCreated(ScimTokenOut):
    token: str


# ----------------------------------------------------------------------------- helpers


def _web(path: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}{path}"


def _safe_next(value: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//") and "\\" not in value:
        return value[:500]
    return "/app"


def _error_redirect(code: str) -> RedirectResponse:
    return RedirectResponse(_web(f"/sso/error?code={code}"), status_code=303)


def _public_config(conn: SsoConnection, cfg: OidcConfig | SamlConfig) -> dict[str, Any]:
    data = cfg.model_dump(mode="json")
    if isinstance(cfg, OidcConfig):
        data.pop("client_secret", None)
        data["client_secret_set"] = bool(cfg.client_secret)
    else:
        data["certificates"] = [{"pem": pem, **certificate_info(pem)} for pem in cfg.idp_certificates]
        data.pop("idp_certificates", None)
    return data


def _service_provider(conn: SsoConnection, cfg: OidcConfig | SamlConfig) -> dict[str, str]:
    if isinstance(cfg, SamlConfig):
        cid = str(conn.id)
        return {"entity_id": sp_entity_id(cid, cfg), "acs_url": acs_url(cid), "metadata_url": metadata_url(cid)}
    return {"redirect_uri": redirect_uri()}


async def _connection_out(db: AsyncSession, conn: SsoConnection) -> ConnectionOut:
    cfg = sso_service.load_config(conn)
    mapping_count = int(
        (
            await db.execute(
                select(func.count()).select_from(SsoGroupMapping).where(SsoGroupMapping.connection_id == conn.id)
            )
        ).scalar_one()
    )
    return ConnectionOut(
        id=conn.id,
        type=conn.type,
        name=conn.name,
        domain=conn.domain,
        domain_verified=await sso_service.verified_domain(db, conn.org_id, conn.domain) is not None,
        default_role=conn.default_role,
        enforce=conn.enforce,
        enabled=conn.enabled,
        config=_public_config(conn, cfg),
        service_provider=_service_provider(conn, cfg),
        login_url=f"/api/v1/sso/connections/{conn.id}/start",
        mappings=mapping_count,
        created_at=conn.created_at,
        updated_at=conn.updated_at,
    )


async def _get_connection(db: AsyncSession, principal: Principal, connection_id: uuid.UUID) -> SsoConnection:
    conn = await db.get(SsoConnection, connection_id)
    if conn is None or conn.org_id != principal.org_id:
        raise NotFound("Conexión SSO no encontrada")
    return conn


async def _ensure_domain_free(db: AsyncSession, org_id: uuid.UUID, domain: str, exclude: uuid.UUID | None) -> None:
    q = select(SsoConnection.id).where(SsoConnection.org_id == org_id, func.lower(SsoConnection.domain) == domain)
    if exclude is not None:
        q = q.where(SsoConnection.id != exclude)
    if (await db.execute(q)).first() is not None:
        raise Conflict("Ya existe una conexión SSO para ese dominio", code="domain_in_use")


async def _require_verified_for_enforce(db: AsyncSession, conn: SsoConnection) -> None:
    if conn.enforce and await sso_service.verified_domain(db, conn.org_id, conn.domain) is None:
        raise Conflict("Verifica el dominio antes de exigir SSO a sus usuarios", code="domain_not_verified")


def _domain_out(row: OrgDomain) -> DomainOut:
    return DomainOut(
        id=row.id,
        domain=row.domain,
        verified_at=row.verified_at,
        verification_method=row.verification_method,
        last_checked_at=row.last_checked_at,
        record=sso_service.verification_record(row),
        created_at=row.created_at,
    )


async def _store_test_result(conn: SsoConnection, result: dict[str, Any]) -> str:
    key = random_token(18)
    payload = {"org_id": str(conn.org_id), "connection_id": str(conn.id), "at": datetime.now(UTC).isoformat(), **result}
    await get_redis().set(f"sso:test:{key}", json.dumps(payload, default=str), ex=TEST_RESULT_TTL_S)
    return key


async def _record_failure(conn: SsoConnection, code: str, message: str, request: Request) -> None:
    async with system_session() as s:
        await audit.record(
            s,
            action="sso.login_failed",
            org_id=conn.org_id,
            entity_type="sso_connection",
            entity_id=conn.id,
            diff={"code": code, "message": message[:300]},
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )


# ============================================================================= public flow


@router.post("/discover", response_model=DiscoverOut, dependencies=[Depends(rate_limit("sso_discover", 30, 60))])
async def discover(body: DiscoverIn) -> DiscoverOut:
    async with system_session() as s:
        conn = await sso_service.discover(s, body.email)
    if conn is None:
        raise NotFound(
            "No hay inicio de sesión SSO configurado para ese dominio. Entra con email y contraseña o consulta a tu administrador.",
            code="sso_not_configured",
        )
    query = urlencode({"next": _safe_next(body.next), "email": body.email})
    return DiscoverOut(
        redirect_url=f"/api/v1/sso/connections/{conn.id}/start?{query}", connection_name=conn.name, type=conn.type
    )


@router.get("/connections/{connection_id}/start", dependencies=[Depends(rate_limit("sso_start", 60, 60))])
async def start_login(
    connection_id: uuid.UUID,
    request: Request,
    next: str = "/app",
    email: str | None = None,
    test: bool = False,
) -> RedirectResponse:
    """Redirect the browser to the identity provider. ``test=1`` (admins) runs a dry-run login."""
    initiator: uuid.UUID | None = None
    principal: Principal | None = None
    if test:
        principal = await get_optional_principal(request)
        if principal is None:
            return _error_redirect("not_authenticated")
    async with system_session() as s:
        conn = await s.get(SsoConnection, connection_id)
        if conn is None or (not conn.enabled and not test):
            return _error_redirect("connection_unavailable")
        if test:
            assert principal is not None
            role = (
                await s.execute(
                    select(Membership.role).where(
                        Membership.org_id == conn.org_id, Membership.user_id == principal.user_id
                    )
                )
            ).scalar_one_or_none()
            if not principal.is_superadmin and role not in ("admin", "owner"):
                return _error_redirect("forbidden")
            initiator = principal.user_id
        elif not await sso_service.org_has_feature(s, conn.org_id, "sso"):
            return _error_redirect("plan_feature")
        cfg = sso_service.load_config(conn)
        payload: dict[str, Any] = {"connection_id": str(conn.id), "next": _safe_next(next), "test": test}
        hint = email if email and "@" in email else None
        try:
            if isinstance(cfg, OidcConfig):
                meta = await provider_metadata(cfg)
                verifier, challenge = pkce_pair()
                nonce = random_token(24)
                payload |= {"verifier": verifier, "nonce": nonce}
                state = await auth_service.create_one_time_token(
                    s, purpose="sso_state", user_id=initiator, ttl=STATE_TTL, payload=payload
                )
                url = authorization_url(meta, cfg, state=state, nonce=nonce, code_challenge=challenge, login_hint=hint)
            else:
                request_id = new_request_id()
                payload |= {"request_id": request_id}
                state = await auth_service.create_one_time_token(
                    s, purpose="sso_state", user_id=initiator, ttl=STATE_TTL, payload=payload
                )
                url = authn_request_url(str(conn.id), cfg, request_id=request_id, relay_state=state, login_hint=hint)
        except SsoProtocolError as exc:
            log.warning("sso.start_failed", connection=str(conn.id), code=exc.code)
            return _error_redirect(exc.code)
    return RedirectResponse(url, status_code=302)


async def _consume_state(token: str) -> OneTimeToken | None:
    try:
        async with system_session() as s:
            return await auth_service.consume_one_time_token(s, purpose="sso_state", token=token)
    except ApiError:
        return None


async def _finish(
    request: Request,
    conn_id: uuid.UUID,
    identity: SsoIdentity,
    state_payload: dict[str, Any],
) -> RedirectResponse:
    """Common end of both protocols: dry-run result, or provisioning + session cookies."""
    settings = get_settings()
    response: RedirectResponse | None = None
    failure: SsoProtocolError | None = None
    async with system_session() as s:
        conn = await s.get(SsoConnection, conn_id)
        if conn is None:
            return _error_redirect("connection_unavailable")
        cfg = sso_service.load_config(conn)
        if state_payload.get("test"):
            result = await sso_service.evaluate_login(s, conn, cfg, identity)
            key = await _store_test_result(conn, result)
            return RedirectResponse(_web(f"/app/settings/sso?test_result={key}"), status_code=303)
        try:
            async with s.begin_nested():
                outcome = await sso_service.complete_login(s, conn, cfg, identity)
        except SsoProtocolError as exc:
            failure = exc
        else:
            if await auth_service.mfa_enabled(s, outcome.user.id):
                challenge = sign_payload({"sub": str(outcome.user.id), "purpose": "mfa"}, ttl_s=300)
                response = RedirectResponse(
                    _web("/mfa?" + urlencode({"token": challenge, "next": _safe_next(state_payload.get("next"))})),
                    status_code=303,
                )
            else:
                tokens = await auth_service.open_session(
                    s,
                    outcome.user,
                    user_agent=request.headers.get("user-agent"),
                    ip=client_ip(request),
                    mfa_verified=identity.mfa,
                )
                target = _safe_next(state_payload.get("next"))
                response = RedirectResponse(f"{settings.messer_web_url.rstrip('/')}{target}", status_code=303)
                set_session_cookies(response, tokens, outcome.org_id)
    if failure is not None or response is None:
        code = failure.code if failure is not None else "login_failed"
        await _record_failure(conn, code, failure.message if failure is not None else code, request)
        return _error_redirect(code)
    return response


@router.get("/oidc/callback", dependencies=[Depends(rate_limit("sso_callback", 60, 60))])
async def oidc_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> RedirectResponse:
    row = await _consume_state(state) if state else None
    if row is None:
        return _error_redirect("state_expired")
    payload = dict(row.payload)
    conn_id = uuid.UUID(str(payload["connection_id"]))
    async with system_session() as s:
        conn = await s.get(SsoConnection, conn_id)
    if conn is None or conn.type != "oidc":
        return _error_redirect("connection_unavailable")
    cfg = sso_service.load_config(conn)
    assert isinstance(cfg, OidcConfig)
    try:
        if error:
            raise SsoProtocolError(
                "idp_denied", f"El proveedor de identidad devolvió {error}: {error_description}"[:300]
            )
        if not code:
            raise SsoProtocolError("missing_code", "Falta el código de autorización")
        meta = await provider_metadata(cfg)
        tokens = await exchange_code(meta, cfg, code=code, verifier=str(payload["verifier"]))
        claims = await validate_id_token(meta, cfg, str(tokens["id_token"]), nonce=str(payload["nonce"]))
        needs_userinfo = not any(isinstance(claims.get(c), str) for c in (cfg.email_claim, *cfg.fallback_email_claims))
        userinfo = await fetch_userinfo(meta, str(tokens.get("access_token") or "")) if needs_userinfo else {}
        identity = identity_from_claims(cfg, claims, userinfo)
    except SsoProtocolError as exc:
        if payload.get("test"):
            key = await _store_test_result(
                conn, {"ok": False, "problems": [{"code": exc.code, "message": exc.message}], "identity": None}
            )
            return RedirectResponse(_web(f"/app/settings/sso?test_result={key}"), status_code=303)
        await _record_failure(conn, exc.code, exc.message, request)
        return _error_redirect(exc.code)
    return await _finish(request, conn_id, identity, payload)


@router.post("/saml/{connection_id}/acs", dependencies=[Depends(rate_limit("sso_callback", 60, 60))])
async def saml_acs(connection_id: uuid.UUID, request: Request) -> RedirectResponse:
    form = await request.form()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState")
    async with system_session() as s:
        conn = await s.get(SsoConnection, connection_id)
    if conn is None or conn.type != "saml" or not isinstance(saml_response, str):
        return _error_redirect("connection_unavailable" if conn is None or conn.type != "saml" else "invalid_response")
    cfg = sso_service.load_config(conn)
    assert isinstance(cfg, SamlConfig)
    payload: dict[str, Any] = {"next": "/app", "test": False}
    expected_request_id: str | None = None
    if isinstance(relay_state, str) and relay_state:
        row = await _consume_state(relay_state)
        if row is not None:
            if row.payload.get("connection_id") != str(conn.id):
                return _error_redirect("state_mismatch")
            payload = dict(row.payload)
            expected_request_id = str(payload.get("request_id") or "") or None
        elif not cfg.allow_idp_initiated:
            return _error_redirect("state_expired")
    try:
        login = process_response(
            saml_response, cfg, connection_id=str(conn.id), expected_request_id=expected_request_id
        )
        if not payload.get("test"):
            async with system_session() as s:
                fresh = await sso_service.mark_assertion_used(
                    s, connection_id=conn.id, assertion_id=login.assertion_id, expires_at=login.expires_at
                )
            if not fresh:
                raise SsoProtocolError("assertion_replayed", "Esta aserción SAML ya se ha utilizado")
    except SsoProtocolError as exc:
        if payload.get("test"):
            key = await _store_test_result(
                conn, {"ok": False, "problems": [{"code": exc.code, "message": exc.message}], "identity": None}
            )
            return RedirectResponse(_web(f"/app/settings/sso?test_result={key}"), status_code=303)
        await _record_failure(conn, exc.code, exc.message, request)
        return _error_redirect(exc.code)
    return await _finish(request, conn.id, login.identity, payload)


@router.get("/saml/{connection_id}/metadata")
async def saml_metadata(connection_id: uuid.UUID) -> Response:
    async with system_session() as s:
        conn = await s.get(SsoConnection, connection_id)
    if conn is None or conn.type != "saml":
        raise NotFound("Conexión SAML no encontrada")
    cfg = sso_service.load_config(conn)
    assert isinstance(cfg, SamlConfig)
    return Response(
        sp_metadata_xml(str(conn.id), cfg),
        media_type="application/samlmetadata+xml",
        headers={"Content-Disposition": f'inline; filename="messer-sp-{conn.id}.xml"'},
    )


# ============================================================================= admin


@router.get("/overview")
async def overview(
    principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    sso_upgrade = await limits.cheapest_plan_with_feature(db, "sso")
    scim_upgrade = await limits.cheapest_plan_with_feature(db, "scim")
    return {
        "sso_available": await sso_service.org_has_feature(db, principal.org_id, "sso"),
        "scim_available": await sso_service.org_has_feature(db, principal.org_id, "scim"),
        "sso_upgrade_to": sso_upgrade.id if sso_upgrade else None,
        "scim_upgrade_to": scim_upgrade.id if scim_upgrade else None,
        "oidc_redirect_uri": redirect_uri(),
        "scim_base_url": scim_base_url(),
    }


@router.get("/presets")
async def presets(_: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    return {"presets": sso_service.PRESETS, "name_id_formats": list(sso_service.NAME_ID_FORMATS)}


@router.get("/connections", response_model=list[ConnectionOut])
async def list_connections(
    principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> list[ConnectionOut]:
    rows = (
        await db.execute(
            select(SsoConnection).where(SsoConnection.org_id == principal.org_id).order_by(SsoConnection.created_at)
        )
    ).scalars()
    return [await _connection_out(db, c) for c in rows]


@router.post("/connections", response_model=ConnectionOut, status_code=201)
async def create_connection(
    body: ConnectionIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> ConnectionOut:
    assert principal.org_id is not None
    await limits.require_feature(db, principal.org_id, "sso")
    domain = sso_service.normalize_domain(body.domain)
    await _ensure_domain_free(db, principal.org_id, domain, None)
    cfg = sso_service.parse_config(body.type, body.config)
    conn = SsoConnection(
        org_id=principal.org_id,
        type=body.type,
        name=body.name.strip(),
        domain=domain,
        default_role=body.default_role,
        enforce=body.enforce,
        enabled=body.enabled,
        config_encrypted="",
    )
    sso_service.store_config(conn, cfg)
    await _require_verified_for_enforce(db, conn)
    db.add(conn)
    await db.flush()
    await audit.record(
        db,
        action="sso.connection_created",
        principal=principal,
        entity_type="sso_connection",
        entity_id=conn.id,
        diff={"type": body.type, "name": conn.name, "domain": domain, "preset": cfg.preset, "enforce": conn.enforce},
    )
    await db.refresh(conn)
    return await _connection_out(db, conn)


@router.get("/connections/{connection_id}", response_model=ConnectionOut)
async def get_connection(
    connection_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> ConnectionOut:
    return await _connection_out(db, await _get_connection(db, principal, connection_id))


@router.patch("/connections/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionPatch,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ConnectionOut:
    assert principal.org_id is not None
    conn = await _get_connection(db, principal, connection_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("enabled") or changes.get("enforce") or "config" in changes:
        await limits.require_feature(db, principal.org_id, "sso")
    before = {k: getattr(conn, k) for k in ("name", "domain", "default_role", "enforce", "enabled")}
    if "domain" in changes and changes["domain"] is not None:
        domain = sso_service.normalize_domain(changes["domain"])
        await _ensure_domain_free(db, principal.org_id, domain, conn.id)
        conn.domain = domain
    for field_name in ("name", "default_role", "enforce", "enabled"):
        if changes.get(field_name) is not None:
            setattr(conn, field_name, changes[field_name])
    if body.config is not None:
        sso_service.store_config(conn, sso_service.merge_config(conn, body.config))
    await _require_verified_for_enforce(db, conn)
    conn.updated_at = datetime.now(UTC)
    after = {k: getattr(conn, k) for k in before}
    await audit.record(
        db,
        action="sso.connection_updated",
        principal=principal,
        entity_type="sso_connection",
        entity_id=conn.id,
        diff={"before": before, "after": after, "config_changed": body.config is not None},
    )
    await db.flush()
    await db.refresh(conn)
    return await _connection_out(db, conn)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    conn = await _get_connection(db, principal, connection_id)
    await db.delete(conn)
    await audit.record(
        db,
        action="sso.connection_deleted",
        principal=principal,
        entity_type="sso_connection",
        entity_id=connection_id,
        diff={"name": conn.name, "domain": conn.domain, "type": conn.type},
    )
    return Response(status_code=204)


@router.get("/test-results/{key}")
async def test_result(key: str, principal: Principal = Depends(require_role("admin"))) -> dict[str, Any]:
    raw = await get_redis().get(f"sso:test:{key}")
    if not raw:
        raise NotFound("El resultado de la prueba ha caducado", code="test_result_expired")
    data = json.loads(raw)
    if data.get("org_id") != str(principal.org_id) and not principal.is_superadmin:
        raise NotFound("El resultado de la prueba ha caducado", code="test_result_expired")
    return data


# ----------------------------------------------------------------------------- group mappings


@router.get("/connections/{connection_id}/mappings", response_model=list[MappingOut])
async def list_mappings(
    connection_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> list[MappingOut]:
    await _get_connection(db, principal, connection_id)
    rows = (
        await db.execute(
            select(SsoGroupMapping)
            .where(SsoGroupMapping.connection_id == connection_id)
            .order_by(SsoGroupMapping.external_group)
        )
    ).scalars()
    return [
        MappingOut(id=m.id, connection_id=m.connection_id, external_group=m.external_group, role=m.role) for m in rows
    ]


@router.post("/connections/{connection_id}/mappings", response_model=MappingOut, status_code=201)
async def create_mapping(
    connection_id: uuid.UUID,
    body: MappingIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> MappingOut:
    assert principal.org_id is not None
    await limits.require_feature(db, principal.org_id, "sso")
    conn = await _get_connection(db, principal, connection_id)
    group = body.external_group.strip()
    exists = (
        await db.execute(
            select(SsoGroupMapping.id).where(
                SsoGroupMapping.connection_id == conn.id,
                func.lower(SsoGroupMapping.external_group) == group.lower(),
            )
        )
    ).first()
    if exists is not None:
        raise Conflict("Ese grupo ya tiene un rol asignado", code="mapping_exists")
    mapping = SsoGroupMapping(org_id=conn.org_id, connection_id=conn.id, external_group=group, role=body.role)
    db.add(mapping)
    await db.flush()
    await audit.record(
        db,
        action="sso.mapping_created",
        principal=principal,
        entity_type="sso_group_mapping",
        entity_id=mapping.id,
        diff={"connection_id": str(conn.id), "external_group": group, "role": body.role},
    )
    return MappingOut(id=mapping.id, connection_id=conn.id, external_group=group, role=body.role)


@router.delete("/connections/{connection_id}/mappings/{mapping_id}", status_code=204)
async def delete_mapping(
    connection_id: uuid.UUID,
    mapping_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await _get_connection(db, principal, connection_id)
    mapping = await db.get(SsoGroupMapping, mapping_id)
    if mapping is None or mapping.connection_id != connection_id:
        raise NotFound("Mapeo no encontrado")
    await db.delete(mapping)
    await audit.record(
        db,
        action="sso.mapping_deleted",
        principal=principal,
        entity_type="sso_group_mapping",
        entity_id=mapping_id,
        diff={"external_group": mapping.external_group, "role": mapping.role},
    )
    return Response(status_code=204)


# ----------------------------------------------------------------------------- domains


@router.get("/domains", response_model=list[DomainOut])
async def list_domains(
    principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> list[DomainOut]:
    rows = (
        await db.execute(select(OrgDomain).where(OrgDomain.org_id == principal.org_id).order_by(OrgDomain.domain))
    ).scalars()
    return [_domain_out(r) for r in rows]


@router.post("/domains", response_model=DomainOut, status_code=201)
async def add_domain(
    body: DomainIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> DomainOut:
    row = await sso_service.create_domain(db, principal=principal, domain=body.domain)
    await db.refresh(row)
    return _domain_out(row)


@router.post("/domains/{domain_id}/verify", response_model=DomainOut)
async def verify_domain(
    domain_id: uuid.UUID, body: VerifyIn | None = None, principal: Principal = Depends(require_role("admin"))
) -> DomainOut:
    # System session: the "already verified by another organization" check must see every organization.
    async with system_session() as s:
        row = await s.get(OrgDomain, domain_id)
        if row is None or row.org_id != principal.org_id:
            raise NotFound("Dominio no encontrado")
        failure: ApiError | None = None
        try:
            async with s.begin_nested():
                await sso_service.verify_domain(s, row, principal=principal, manual=bool(body and body.manual))
        except ApiError as exc:
            failure = exc
        await s.refresh(row)  # a rolled-back savepoint expires the row
        row.last_checked_at = datetime.now(UTC)
        out = _domain_out(row)
    if failure is not None:
        raise failure
    return out


@router.delete("/domains/{domain_id}", status_code=204)
async def delete_domain(
    domain_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    row = await db.get(OrgDomain, domain_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Dominio no encontrado")
    enforced = (
        await db.execute(
            select(SsoConnection.id).where(
                SsoConnection.org_id == row.org_id,
                func.lower(SsoConnection.domain) == row.domain,
                SsoConnection.enforce.is_(True),
            )
        )
    ).first()
    if enforced is not None:
        raise Conflict(
            "Desactiva «exigir SSO» en la conexión de este dominio antes de eliminarlo", code="domain_enforced"
        )
    await db.delete(row)
    await audit.record(
        db,
        action="sso.domain_removed",
        principal=principal,
        entity_type="org_domain",
        entity_id=domain_id,
        diff={"domain": row.domain},
    )
    return Response(status_code=204)


# ----------------------------------------------------------------------------- SCIM tokens


def _token_out(t: ScimToken) -> ScimTokenOut:
    return ScimTokenOut(
        id=t.id, name=t.name, created_at=t.created_at, last_used_at=t.last_used_at, revoked_at=t.revoked_at
    )


@router.get("/scim/tokens", response_model=list[ScimTokenOut])
async def list_scim_tokens(
    principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> list[ScimTokenOut]:
    rows = (
        await db.execute(
            select(ScimToken).where(ScimToken.org_id == principal.org_id).order_by(ScimToken.created_at.desc())
        )
    ).scalars()
    return [_token_out(t) for t in rows]


@router.post("/scim/tokens", response_model=ScimTokenCreated, status_code=201)
async def create_scim_token(
    body: ScimTokenIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> ScimTokenCreated:
    assert principal.org_id is not None
    await limits.require_feature(db, principal.org_id, "scim")
    token = f"scim_{random_token(32)}"
    row = ScimToken(org_id=principal.org_id, hashed_token=hash_token(token), name=body.name.strip())
    db.add(row)
    await db.flush()
    await db.refresh(row)
    await audit.record(
        db,
        action="scim.token_created",
        principal=principal,
        entity_type="scim_token",
        entity_id=row.id,
        diff={"name": row.name},
    )
    return ScimTokenCreated(**_token_out(row).model_dump(), token=token)


@router.delete("/scim/tokens/{token_id}", status_code=204)
async def revoke_scim_token(
    token_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    row = await db.get(ScimToken, token_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Token SCIM no encontrado")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        await audit.record(
            db,
            action="scim.token_revoked",
            principal=principal,
            entity_type="scim_token",
            entity_id=row.id,
            diff={"name": row.name},
        )
    return Response(status_code=204)


@router.get("/scim/users")
async def scim_users_summary(
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[dict[str, Any]]:
    """Users provisioned by SCIM in this organization (for the settings screen)."""
    rows = (
        await db.execute(
            select(OrgIdentity, User.email)
            .join(User, User.id == OrgIdentity.user_id)
            .where(OrgIdentity.org_id == principal.org_id, OrgIdentity.scim_managed.is_(True))
            .order_by(OrgIdentity.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "user_id": str(i.user_id),
            "email": email,
            "user_name": i.scim_user_name,
            "active": i.active,
            "external_id": i.scim_external_id,
            "updated_at": i.updated_at.isoformat(),
        }
        for i, email in rows
    ]
