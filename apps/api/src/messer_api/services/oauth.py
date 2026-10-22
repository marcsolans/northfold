"""OAuth 2.1 authorization server for the Messer MCP server and other developer tools.

* Authorization code + PKCE (S256 only), dynamic client registration (RFC 7591), metadata (RFC 8414), token
  revocation (RFC 7009), resource indicators (RFC 8707, informative: tokens are valid for the whole API).
* Access tokens are API-key equivalents: an ``api_keys`` row bound to an ``oauth_grants`` row (user + organization
  + scopes), shown in Settings → API keys, revocable, expiring after one hour, acting with the user's current
  role in the organization (at most builder). Refresh tokens rotate on every use (30-day sliding lifetime).
* Authorization codes live ten minutes in Redis and are single use.

The consent screen is the web page ``/oauth/authorize``; ``GET {issuer}/oauth/authorize`` validates the request
and sends the browser there.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import ApiKey, Membership, Org, User
from messer_common.db.models.developers import OAuthClient, OAuthGrant
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.roles import at_least
from messer_common.security import hash_token
from messer_common.settings import get_settings

log = get_logger("messer.api.oauth")

SCOPES: tuple[str, ...] = (
    "projects:read",
    "projects:write",
    "runs:read",
    "runs:write",
    "knowledge:read",
    "knowledge:write",
    "deployments:write",
    "evals:run",
)
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 30 * 24 * 3600
CODE_TTL_S = 600
CLIENT_PREFIX = "mcl_"
REFRESH_PREFIX = "msrt_"
AUTH_METHODS = ("none", "client_secret_post", "client_secret_basic")
GRANT_TYPES = ("authorization_code", "refresh_token")
_BLOCKED_SCHEMES = {"javascript", "data", "file", "vbscript", "about", "blob", "ws", "wss", "ftp", "mailto", "tel"}
_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]{1,62}$")
_VERIFIER = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_LOOPBACK = ("localhost", "127.0.0.1", "::1")


class OAuthError(Exception):
    """RFC 6749 error. ``redirectable``: the client and redirect URI are trusted, so the error goes back to it."""

    def __init__(self, error: str, description: str, *, status: int = 400, redirectable: bool = False) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status
        self.redirectable = redirectable

    def body(self) -> dict[str, str]:
        return {"error": self.error, "error_description": self.description}


# --------------------------------------------------------------------------------------------- metadata


def issuer() -> str:
    return get_settings().messer_api_url.rstrip("/")


def metadata() -> dict[str, Any]:
    base = issuer()
    web = get_settings().messer_web_url.rstrip("/")
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "scopes_supported": list(SCOPES),
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": list(GRANT_TYPES),
        "token_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": list(AUTH_METHODS),
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        "service_documentation": f"{web}/docs/mcp",
        "ui_locales_supported": ["es", "en"],
    }


def parse_scope(raw: str | None, *, allowed: list[str] | None = None) -> list[str]:
    """Space-separated scopes → known scopes (all of them when empty), limited to ``allowed`` when given."""
    requested = [s for s in (raw or "").split() if s]
    pool = [s for s in SCOPES if allowed is None or not allowed or s in allowed]
    if not requested:
        return pool
    unknown = [s for s in requested if s not in SCOPES]
    if unknown:
        raise OAuthError("invalid_scope", f"Permisos desconocidos: {' '.join(unknown)}", redirectable=True)
    return [s for s in pool if s in requested]


# ---------------------------------------------------------------------------------- client registration


def valid_redirect_uri(uri: str) -> bool:
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.fragment or not parts.scheme or len(uri) > 2000:
        return False
    if parts.scheme == "https":
        return bool(parts.hostname)
    if parts.scheme == "http":
        return parts.hostname in _LOOPBACK
    # Private-use URI schemes of native apps (RFC 8252 §7.1), e.g. cursor://…, vscode://…
    return bool(_SCHEME.match(parts.scheme)) and parts.scheme not in _BLOCKED_SCHEMES


def redirect_matches(registered: list[str], uri: str) -> bool:
    """Exact match, except that loopback redirects may use any port (RFC 8252 §7.3)."""
    if uri in registered:
        return True
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.scheme != "http" or parts.hostname not in _LOOPBACK:
        return False
    for candidate in registered:
        c = urlsplit(candidate)
        if c.scheme == "http" and c.hostname == parts.hostname and c.path == parts.path and c.query == parts.query:
            return True
    return False


async def register_client(body: dict[str, Any]) -> dict[str, Any]:
    uris = body.get("redirect_uris")
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        raise OAuthError("invalid_redirect_uri", "redirect_uris debe ser una lista de 1 a 10 URIs")
    redirect_uris = [str(u) for u in uris]
    bad = [u for u in redirect_uris if not valid_redirect_uri(u)]
    if bad:
        raise OAuthError(
            "invalid_redirect_uri", f"URI de redirección no permitida: {bad[0]} (usa https o http://localhost)"
        )
    method = str(body.get("token_endpoint_auth_method") or "client_secret_basic")
    if method not in AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", f"token_endpoint_auth_method no admitido: {method}")
    grant_types = [str(g) for g in (body.get("grant_types") or ["authorization_code"])]
    if any(g not in GRANT_TYPES for g in grant_types) or "authorization_code" not in grant_types:
        raise OAuthError("invalid_client_metadata", "grant_types admitidos: authorization_code, refresh_token")
    response_types = [str(r) for r in (body.get("response_types") or ["code"])]
    if response_types != ["code"]:
        raise OAuthError("invalid_client_metadata", "response_types admitido: code")
    raw_scope = body.get("scope")
    try:
        scopes = parse_scope(str(raw_scope) if raw_scope else None)
    except OAuthError as exc:
        raise OAuthError("invalid_client_metadata", exc.description) from exc
    name = str(body.get("client_name") or "Cliente MCP").strip()[:200] or "Cliente MCP"

    def _url(key: str) -> str | None:
        value = body.get(key)
        if not value:
            return None
        text = str(value)[:2000]
        return text if urlsplit(text).scheme == "https" else None

    client_id = CLIENT_PREFIX + secrets.token_urlsafe(24)
    secret = secrets.token_urlsafe(32) if method != "none" else None
    client = OAuthClient(
        id=client_id,
        client_name=name,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        token_endpoint_auth_method=method,
        client_secret_hash=hash_token(secret) if secret else None,
        scope=" ".join(scopes),
        client_uri=_url("client_uri"),
        logo_uri=_url("logo_uri"),
        software_id=str(body["software_id"])[:200] if body.get("software_id") else None,
        software_version=str(body["software_version"])[:80] if body.get("software_version") else None,
    )
    async with system_session() as s:
        s.add(client)
    log.info("oauth.client_registered", client_id=client_id, name=name, method=method)
    out: dict[str, Any] = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "client_name": name,
        "redirect_uris": redirect_uris,
        "grant_types": grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": method,
        "scope": " ".join(scopes),
    }
    for key in ("client_uri", "logo_uri", "software_id", "software_version"):
        if getattr(client, key):
            out[key] = getattr(client, key)
    if secret:
        out["client_secret"] = secret
        out["client_secret_expires_at"] = 0
    return out


async def get_client(client_id: str | None) -> OAuthClient | None:
    if not client_id or not client_id.startswith(CLIENT_PREFIX) or len(client_id) > 64:
        return None
    async with system_session() as s:
        return await s.get(OAuthClient, client_id)


# ----------------------------------------------------------------------------------------- authorization


@dataclass(slots=True)
class AuthorizeRequest:
    client_id: str
    redirect_uri: str
    code_challenge: str
    state: str | None
    scopes: list[str] = field(default_factory=list)
    resource: str | None = None


def _allowed_resource(resource: str) -> bool:
    settings = get_settings()
    prefixes = [settings.messer_mcp_url.rstrip("/"), settings.messer_api_url.rstrip("/")]
    return any(resource == p or resource.startswith(p + "/") for p in prefixes)


async def validate_authorize(params: dict[str, str]) -> tuple[OAuthClient, AuthorizeRequest]:
    client = await get_client(params.get("client_id"))
    if client is None:
        raise OAuthError("invalid_client", "Aplicación desconocida: vuelve a conectarla desde tu herramienta")
    redirect_uri = params.get("redirect_uri") or ""
    if not redirect_uri and len(client.redirect_uris or []) == 1:
        redirect_uri = str(client.redirect_uris[0])
    if not redirect_matches([str(u) for u in client.redirect_uris or []], redirect_uri):
        raise OAuthError("invalid_request", "La URI de redirección no está registrada para esta aplicación")
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "Solo se admite response_type=code", redirectable=True)
    challenge = params.get("code_challenge") or ""
    if params.get("code_challenge_method") != "S256" or not _CHALLENGE.match(challenge):
        raise OAuthError("invalid_request", "PKCE obligatorio: code_challenge con code_challenge_method=S256", redirectable=True)
    scopes = parse_scope(params.get("scope"), allowed=(client.scope or "").split())
    resource = params.get("resource") or None
    if resource is not None and not _allowed_resource(resource):
        raise OAuthError("invalid_target", "Recurso desconocido para este servidor de autorización", redirectable=True)
    return client, AuthorizeRequest(
        client_id=client.id,
        redirect_uri=redirect_uri,
        code_challenge=challenge,
        state=params.get("state"),
        scopes=scopes,
        resource=resource,
    )


def error_redirect(redirect_uri: str, error: str, description: str, state: str | None) -> str:
    query = {"error": error, "error_description": description, "iss": issuer()}
    if state:
        query["state"] = state
    sep = "&" if urlsplit(redirect_uri).query else "?"
    return f"{redirect_uri}{sep}{urlencode(query)}"


def consent_url(params: dict[str, str]) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/oauth/authorize?{urlencode(params)}"


async def consent_view(user_id: uuid.UUID, client: OAuthClient, req: AuthorizeRequest) -> dict[str, Any]:
    async with system_session() as s:
        user = await s.get(User, user_id)
        rows = (
            await s.execute(
                select(Org, Membership.role)
                .join(Membership, Membership.org_id == Org.id)
                .where(Membership.user_id == user_id)
                .order_by(Org.name)
            )
        ).all()
    redirect = urlsplit(req.redirect_uri)
    return {
        "client": {
            "client_id": client.id,
            "client_name": client.client_name,
            "client_uri": client.client_uri,
            "logo_uri": client.logo_uri,
            "redirect_host": redirect.netloc or f"{redirect.scheme}:",
            "registered_at": client.created_at.isoformat() if client.created_at else None,
        },
        "scopes": req.scopes,
        "resource": req.resource,
        "user": {"email": user.email if user else None, "name": user.name if user else None},
        "orgs": [
            {
                "id": str(org.id),
                "name": org.name,
                "slug": org.slug,
                "role": role,
                "effective_role": role if not at_least(role, "builder") else "builder",
                "blocked": org.status == "blocked",
            }
            for org, role in rows
        ],
    }


async def approve(
    principal: Principal, client: OAuthClient, req: AuthorizeRequest, org_id: uuid.UUID, ip: str | None
) -> str:
    """Record the user's consent and return the client redirect carrying a single-use authorization code."""
    assert principal.user_id is not None
    async with system_session() as s:
        role = (
            await s.execute(
                select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == principal.user_id)
            )
        ).scalar_one_or_none()
        if role is None:
            raise OAuthError("access_denied", "No perteneces a esa organización", status=403)
        org = await s.get(Org, org_id)
        if org is None or org.status == "blocked":
            raise OAuthError("access_denied", "Esta organización está bloqueada", status=403)
        await audit.record(
            s,
            action="oauth.authorized",
            principal=Principal(user_id=principal.user_id, org_id=org_id, role=role, impersonated_by=principal.impersonated_by),
            entity_type="oauth_client",
            entity_id=client.id,
            diff={"client_name": client.client_name, "scopes": req.scopes, "resource": req.resource},
            ip=ip,
        )
    code = secrets.token_urlsafe(32)
    payload = {
        "client_id": client.id,
        "redirect_uri": req.redirect_uri,
        "code_challenge": req.code_challenge,
        "scopes": req.scopes,
        "resource": req.resource,
        "user_id": str(principal.user_id),
        "org_id": str(org_id),
    }
    await get_redis().set(f"oauth:code:{hash_token(code)}", json.dumps(payload), ex=CODE_TTL_S)
    query = {"code": code, "iss": issuer()}
    if req.state:
        query["state"] = req.state
    sep = "&" if urlsplit(req.redirect_uri).query else "?"
    return f"{req.redirect_uri}{sep}{urlencode(query)}"


def deny(req: AuthorizeRequest) -> str:
    return error_redirect(req.redirect_uri, "access_denied", "El usuario ha denegado el acceso", req.state)


# ---------------------------------------------------------------------------------------------- tokens


def _client_credentials(form: dict[str, str], authorization: str | None) -> tuple[str | None, str | None, bool]:
    """(client_id, client_secret, used_basic) from HTTP Basic or the form body."""
    if authorization and authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:].strip(), validate=True).decode()
        except (ValueError, UnicodeDecodeError) as exc:
            raise OAuthError("invalid_client", "Credenciales de cliente mal formadas", status=401) from exc
        cid, _, secret = decoded.partition(":")
        return unquote(cid), unquote(secret), True
    return form.get("client_id"), form.get("client_secret"), False


async def authenticate_client(form: dict[str, str], authorization: str | None) -> OAuthClient:
    client_id, secret, basic = _client_credentials(form, authorization)
    client = await get_client(client_id)
    if client is None:
        raise OAuthError("invalid_client", "Cliente desconocido", status=401)
    if client.token_endpoint_auth_method != "none":
        if not secret or not client.client_secret_hash or not hmac.compare_digest(
            hash_token(secret), client.client_secret_hash
        ):
            raise OAuthError("invalid_client", "Autenticación de cliente no válida", status=401)
    elif basic and secret:
        raise OAuthError("invalid_client", "Este cliente es público: no envíes un secreto", status=401)
    return client


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not _VERIFIER.match(verifier):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _new_access_token() -> tuple[str, str]:
    body = secrets.token_urlsafe(32)
    token = f"msr_{body}"
    return token, token[:12]


def _token_response(access: str, refresh: str | None, scopes: list[str], resource: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TTL_S,
        "scope": " ".join(scopes),
    }
    if refresh:
        out["refresh_token"] = refresh
    if resource:
        out["resource"] = resource
    return out


async def exchange_code(client: OAuthClient, form: dict[str, str], ip: str | None) -> dict[str, Any]:
    code = form.get("code") or ""
    raw = await get_redis().getdel(f"oauth:code:{hash_token(code)}") if code else None
    if not raw:
        raise OAuthError("invalid_grant", "Código de autorización no válido, caducado o ya usado")
    data = json.loads(raw)
    if data["client_id"] != client.id:
        raise OAuthError("invalid_grant", "El código pertenece a otro cliente")
    if (form.get("redirect_uri") or data["redirect_uri"]) != data["redirect_uri"]:
        raise OAuthError("invalid_grant", "redirect_uri no coincide con la autorización")
    if not _pkce_ok(form.get("code_verifier") or "", data["code_challenge"]):
        raise OAuthError("invalid_grant", "code_verifier no válido (PKCE)")
    resource = form.get("resource") or data.get("resource")
    if data.get("resource") and resource != data["resource"]:
        raise OAuthError("invalid_target", "El recurso no coincide con la autorización")
    user_id, org_id = uuid.UUID(data["user_id"]), uuid.UUID(data["org_id"])
    scopes = [str(s) for s in data["scopes"]]
    access, prefix = _new_access_token()
    refresh = REFRESH_PREFIX + secrets.token_urlsafe(32) if "refresh_token" in (client.grant_types or []) else None
    now = datetime.now(UTC)
    async with system_session() as s:
        user = await s.get(User, user_id)
        member = (
            await s.execute(select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user_id))
        ).scalar_one_or_none()
        if user is None or user.deleted_at is not None or member is None:
            raise OAuthError("invalid_grant", "El usuario ya no tiene acceso a la organización")
        grant = OAuthGrant(
            org_id=org_id,
            user_id=user_id,
            client_id=client.id,
            scopes=scopes,
            resource=resource,
            refresh_token_hash=hash_token(refresh) if refresh else None,
            refresh_expires_at=now + timedelta(seconds=REFRESH_TTL_S) if refresh else None,
        )
        s.add(grant)
        await s.flush()
        key = ApiKey(
            org_id=org_id,
            name=f"OAuth · {client.client_name} · {user.email}"[:200],
            prefix=prefix,
            hashed_key=hash_token(access),
            scopes=scopes,
            created_by=user_id,
            expires_at=now + timedelta(seconds=ACCESS_TTL_S),
            oauth_grant_id=grant.id,
        )
        s.add(key)
        await s.execute(update(OAuthClient).where(OAuthClient.id == client.id).values(last_used_at=now))
        await audit.record(
            s,
            action="oauth.token_issued",
            principal=Principal(user_id=user_id, org_id=org_id, role=member),
            entity_type="oauth_grant",
            entity_id=grant.id,
            diff={"client_id": client.id, "client_name": client.client_name, "scopes": scopes},
            ip=ip,
        )
    return _token_response(access, refresh, scopes, resource)


async def _grant_by_refresh(s: AsyncSession, refresh: str) -> OAuthGrant | None:
    if not refresh.startswith(REFRESH_PREFIX):
        return None
    return (
        await s.execute(
            select(OAuthGrant).where(OAuthGrant.refresh_token_hash == hash_token(refresh)).with_for_update()
        )
    ).scalar_one_or_none()


async def _grant_key(s: AsyncSession, grant_id: uuid.UUID) -> ApiKey | None:
    return (await s.execute(select(ApiKey).where(ApiKey.oauth_grant_id == grant_id))).scalar_one_or_none()


async def refresh_tokens(client: OAuthClient, form: dict[str, str], ip: str | None) -> dict[str, Any]:
    if "refresh_token" not in (client.grant_types or []):
        raise OAuthError("unauthorized_client", "Este cliente no puede usar refresh_token")
    now = datetime.now(UTC)
    async with system_session() as s:
        grant = await _grant_by_refresh(s, form.get("refresh_token") or "")
        if grant is None or grant.client_id != client.id or grant.revoked_at is not None:
            raise OAuthError("invalid_grant", "refresh_token no válido o revocado")
        key = await _grant_key(s, grant.id)
        member = (
            await s.execute(
                select(Membership.role).where(Membership.org_id == grant.org_id, Membership.user_id == grant.user_id)
            )
        ).scalar_one_or_none()
        expired = grant.refresh_expires_at is not None and grant.refresh_expires_at <= now
        if key is None or key.revoked_at is not None or member is None or expired:
            grant.revoked_at = grant.revoked_at or now
            grant.refresh_token_hash = None
            if key is not None and key.revoked_at is None:
                key.revoked_at = now
            raise_after = OAuthError("invalid_grant", "La autorización ha caducado o se ha revocado")
        else:
            raise_after = None
        if raise_after is None:
            assert key is not None
            scopes = list(grant.scopes or [])
            if form.get("scope"):
                narrowed = [sc for sc in form["scope"].split() if sc in scopes]
                if not narrowed or len(narrowed) != len(form["scope"].split()):
                    raise OAuthError("invalid_scope", "Solo puedes pedir permisos ya concedidos")
                scopes = narrowed
            access, prefix = _new_access_token()
            refresh = REFRESH_PREFIX + secrets.token_urlsafe(32)
            key.hashed_key = hash_token(access)
            key.prefix = prefix
            key.scopes = scopes
            key.expires_at = now + timedelta(seconds=ACCESS_TTL_S)
            grant.refresh_token_hash = hash_token(refresh)
            grant.refresh_expires_at = now + timedelta(seconds=REFRESH_TTL_S)
            grant.last_refreshed_at = now
            await audit.record(
                s,
                action="oauth.token_refreshed",
                principal=Principal(user_id=grant.user_id, org_id=grant.org_id, role=member, api_key_id=key.id),
                entity_type="oauth_grant",
                entity_id=grant.id,
                diff={"client_id": client.id},
                ip=ip,
            )
            resource = grant.resource
    if raise_after is not None:
        raise raise_after
    return _token_response(access, refresh, scopes, resource)


async def revoke_token(client: OAuthClient, token: str, ip: str | None) -> None:
    """RFC 7009: revoking either token ends the whole grant. Unknown tokens are ignored (200)."""
    now = datetime.now(UTC)
    async with system_session() as s:
        grant: OAuthGrant | None = None
        if token.startswith(REFRESH_PREFIX):
            grant = await _grant_by_refresh(s, token)
        elif token.startswith("msr_"):
            key = (await s.execute(select(ApiKey).where(ApiKey.hashed_key == hash_token(token)))).scalar_one_or_none()
            if key is not None and key.oauth_grant_id is not None:
                grant = await s.get(OAuthGrant, key.oauth_grant_id)
        if grant is None or grant.client_id != client.id:
            return
        await revoke_grant(s, grant, now=now, actor=None, ip=ip)


async def revoke_grant(
    s: AsyncSession, grant: OAuthGrant, *, now: datetime | None = None, actor: Principal | None, ip: str | None = None
) -> None:
    now = now or datetime.now(UTC)
    if grant.revoked_at is None:
        grant.revoked_at = now
    grant.refresh_token_hash = None
    key = await _grant_key(s, grant.id)
    if key is not None and key.revoked_at is None:
        key.revoked_at = now
    await audit.record(
        s,
        action="oauth.revoked",
        principal=actor or Principal(user_id=grant.user_id, org_id=grant.org_id),
        org_id=grant.org_id,
        entity_type="oauth_grant",
        entity_id=grant.id,
        diff={"client_id": grant.client_id},
        ip=ip,
    )


async def list_grants(principal: Principal, *, all_users: bool) -> list[dict[str, Any]]:
    assert principal.org_id is not None
    async with system_session() as s:
        q = (
            select(OAuthGrant, OAuthClient, User)
            .join(OAuthClient, OAuthClient.id == OAuthGrant.client_id)
            .join(User, User.id == OAuthGrant.user_id)
            .where(OAuthGrant.org_id == principal.org_id, OAuthGrant.revoked_at.is_(None))
            .order_by(OAuthGrant.created_at.desc())
        )
        if not all_users:
            q = q.where(OAuthGrant.user_id == principal.user_id)
        rows = (await s.execute(q)).all()
        out: list[dict[str, Any]] = []
        for grant, client, user in rows:
            key = await _grant_key(s, grant.id)
            out.append(
                {
                    "id": str(grant.id),
                    "client_id": client.id,
                    "client_name": client.client_name,
                    "user": {"id": str(user.id), "email": user.email},
                    "scopes": list(grant.scopes or []),
                    "resource": grant.resource,
                    "created_at": grant.created_at.isoformat(),
                    "last_used_at": key.last_used_at.isoformat() if key and key.last_used_at else None,
                    "api_key_id": str(key.id) if key else None,
                }
            )
        return out
