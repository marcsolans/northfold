"""OpenID Connect relying party for enterprise SSO (authorization code + PKCE).

* Provider metadata from ``.well-known/openid-configuration`` (cached), JWKS (cached, refreshed once on an
  unknown ``kid`` for key rotation).
* ``id_token`` validation with PyJWT: asymmetric algorithms only, signature against the JWKS key, ``iss``,
  ``aud`` (and ``azp`` with several audiences), ``exp``/``iat`` with leeway, ``nonce``.
* All HTTP goes through :func:`http_client`, whose transport tests replace with ``httpx.MockTransport``.
"""

from __future__ import annotations

import base64
import hashlib
import ipaddress
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from pydantic import BaseModel, Field

from messer_common.logging import get_logger
from messer_common.security import random_token
from messer_common.settings import get_settings

log = get_logger("messer.sso.oidc")

ALLOWED_ALGORITHMS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
CACHE_TTL_S = 3600
LEEWAY_S = 60


class SsoProtocolError(Exception):
    """A login cannot be completed. ``code`` is stable (shown to the user and in the audit log)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class OidcConfig(BaseModel):
    """Stored (encrypted) configuration of an OIDC connection."""

    preset: Literal["generic", "entra", "google", "okta"] = "generic"
    issuer: str = Field(min_length=8, max_length=500)
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str = Field(default="", max_length=2000)
    discovery_url: str | None = Field(default=None, max_length=500)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile"])
    email_claim: str = "email"
    fallback_email_claims: list[str] = Field(default_factory=list)
    name_claim: str = "name"
    groups_claim: str = "groups"
    hosted_domain_claim: str | None = None  # Google Workspace: "hd" must equal the connection domain
    token_auth_method: Literal["client_secret_basic", "client_secret_post"] | None = None
    jit_provisioning: bool = True


@dataclass(slots=True)
class ProviderMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    token_auth_methods: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SsoIdentity:
    """What an identity provider asserted about the person logging in."""

    subject: str
    email: str
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    groups: list[str] = field(default_factory=list)
    mfa: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- HTTP

_transport: httpx.AsyncBaseTransport | None = None
_metadata_cache: dict[str, tuple[float, ProviderMetadata]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def set_http_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Tests inject an ``httpx.MockTransport`` (fake identity provider)."""
    global _transport
    _transport = transport
    clear_caches()


def clear_caches() -> None:
    _metadata_cache.clear()
    _jwks_cache.clear()


def http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=_transport, timeout=15, follow_redirects=False)


def validate_remote_url(url: str, *, what: str) -> str:
    """Identity provider URLs come from organization admins: https only outside local/test, no internal hosts."""
    parts = urlsplit(url)
    settings = get_settings()
    local = settings.messer_env in ("local", "test")
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise SsoProtocolError("invalid_url", f"URL no válida para {what}")
    if parts.scheme != "https" and not local:
        raise SsoProtocolError("insecure_url", f"La URL de {what} debe usar https")
    if not local:
        host = parts.hostname.lower()
        if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
            raise SsoProtocolError("internal_url", f"La URL de {what} apunta a una red interna")
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            ip = None
        if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved):
            raise SsoProtocolError("internal_url", f"La URL de {what} apunta a una red interna")
    return url


async def _get_json(url: str, *, what: str) -> dict[str, Any]:
    validate_remote_url(url, what=what)
    try:
        async with http_client() as client:
            res = await client.get(url, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise SsoProtocolError(
            "idp_unreachable", f"No se pudo contactar con el proveedor de identidad ({what})"
        ) from exc
    if res.status_code >= 400:
        raise SsoProtocolError("idp_error", f"El proveedor de identidad respondió {res.status_code} ({what})")
    try:
        data = res.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise SsoProtocolError("idp_invalid_response", f"Respuesta no válida del proveedor ({what})") from exc
    if not isinstance(data, dict):
        raise SsoProtocolError("idp_invalid_response", f"Respuesta no válida del proveedor ({what})")
    return data


def discovery_url(config: OidcConfig) -> str:
    if config.discovery_url:
        return config.discovery_url
    return config.issuer.rstrip("/") + "/.well-known/openid-configuration"


async def provider_metadata(config: OidcConfig) -> ProviderMetadata:
    url = discovery_url(config)
    cached = _metadata_cache.get(url)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    data = await _get_json(url, what="discovery")
    try:
        meta = ProviderMetadata(
            issuer=str(data["issuer"]),
            authorization_endpoint=str(data["authorization_endpoint"]),
            token_endpoint=str(data["token_endpoint"]),
            jwks_uri=str(data["jwks_uri"]),
            userinfo_endpoint=str(data["userinfo_endpoint"]) if data.get("userinfo_endpoint") else None,
            token_auth_methods=[str(m) for m in data.get("token_endpoint_auth_methods_supported") or []],
        )
    except KeyError as exc:
        raise SsoProtocolError("idp_invalid_metadata", f"Falta {exc.args[0]} en la configuración OIDC") from exc
    if "{tenantid}" in meta.issuer.lower():
        raise SsoProtocolError(
            "multi_tenant_issuer",
            "El emisor es multiinquilino. Usa el ID de tu inquilino de Entra ID en lugar de common/organizations.",
        )
    if meta.issuer.rstrip("/") != config.issuer.rstrip("/"):
        raise SsoProtocolError("issuer_mismatch", "El emisor publicado no coincide con el configurado")
    for endpoint, what in ((meta.authorization_endpoint, "authorize"), (meta.token_endpoint, "token")):
        validate_remote_url(endpoint, what=what)
    _metadata_cache[url] = (time.monotonic() + CACHE_TTL_S, meta)
    return meta


async def _jwks(uri: str, *, refresh: bool = False) -> dict[str, Any]:
    cached = _jwks_cache.get(uri)
    if cached and cached[0] > time.monotonic() and not refresh:
        return cached[1]
    data = await _get_json(uri, what="jwks")
    if not isinstance(data.get("keys"), list):
        raise SsoProtocolError("idp_invalid_jwks", "El JWKS del proveedor no contiene claves")
    _jwks_cache[uri] = (time.monotonic() + CACHE_TTL_S, data)
    return data


def _find_key(jwks: dict[str, Any], kid: str | None, alg: str) -> jwt.PyJWK | None:
    candidates: list[jwt.PyJWK] = []
    for raw in jwks.get("keys", []):
        if not isinstance(raw, dict) or raw.get("use") == "enc":
            continue
        if kid is not None and raw.get("kid") != kid:
            continue
        try:
            candidates.append(jwt.PyJWK(raw, algorithm=raw.get("alg") or alg))
        except jwt.PyJWKError:
            continue
    if kid is None and len(candidates) != 1:
        return None  # without kid the key must be unambiguous
    return candidates[0] if candidates else None


# ----------------------------------------------------------------------------- flow


def pkce_pair() -> tuple[str, str]:
    verifier = random_token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def redirect_uri() -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/sso/oidc/callback"


def authorization_url(
    meta: ProviderMetadata,
    config: OidcConfig,
    *,
    state: str,
    nonce: str,
    code_challenge: str,
    login_hint: str | None,
) -> str:
    scopes = list(dict.fromkeys(["openid", *config.scopes]))
    params: dict[str, str] = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "scope": " ".join(scopes),
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    separator = "&" if "?" in meta.authorization_endpoint else "?"
    return f"{meta.authorization_endpoint}{separator}{urlencode(params)}"


async def exchange_code(meta: ProviderMetadata, config: OidcConfig, *, code: str, verifier: str) -> dict[str, Any]:
    method = config.token_auth_method
    if method is None:
        method = (
            "client_secret_post"
            if meta.token_auth_methods and "client_secret_basic" not in meta.token_auth_methods
            else "client_secret_basic"
        )
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "code_verifier": verifier,
        "client_id": config.client_id,
    }
    headers = {"Accept": "application/json"}
    if method == "client_secret_post":
        form["client_secret"] = config.client_secret
    try:
        async with http_client() as client:
            if method == "client_secret_post":
                res = await client.post(meta.token_endpoint, data=form, headers=headers)
            else:
                basic = httpx.BasicAuth(config.client_id, config.client_secret)
                res = await client.post(meta.token_endpoint, data=form, auth=basic, headers=headers)
    except httpx.HTTPError as exc:
        raise SsoProtocolError("idp_unreachable", "No se pudo contactar con el proveedor de identidad") from exc
    try:
        data = res.json()
    except (json.JSONDecodeError, ValueError):
        data = {}
    if res.status_code >= 400 or not isinstance(data, dict):
        reason = data.get("error_description") or data.get("error") if isinstance(data, dict) else None
        log.warning("sso.oidc.token_error", status=res.status_code, reason=reason)
        raise SsoProtocolError("token_exchange_failed", "El proveedor rechazó el código de autorización")
    if not data.get("id_token"):
        raise SsoProtocolError("missing_id_token", "El proveedor no devolvió un id_token")
    return data


async def validate_id_token(meta: ProviderMetadata, config: OidcConfig, id_token: str, *, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise SsoProtocolError("invalid_id_token", "id_token mal formado") from exc
    alg = str(header.get("alg") or "")
    if alg not in ALLOWED_ALGORITHMS:
        raise SsoProtocolError("invalid_id_token", f"Algoritmo de firma no permitido: {alg or 'none'}")
    kid = header.get("kid")
    key = _find_key(await _jwks(meta.jwks_uri), kid, alg)
    if key is None:
        key = _find_key(await _jwks(meta.jwks_uri, refresh=True), kid, alg)
    if key is None:
        raise SsoProtocolError("unknown_signing_key", "La clave de firma del id_token no está en el JWKS")
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key=key.key,
            algorithms=[alg],
            audience=config.client_id,
            issuer=meta.issuer,
            leeway=LEEWAY_S,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise SsoProtocolError("id_token_expired", "El id_token ha caducado") from exc
    except jwt.InvalidAudienceError as exc:
        raise SsoProtocolError("audience_mismatch", "El id_token no está emitido para esta aplicación") from exc
    except jwt.InvalidIssuerError as exc:
        raise SsoProtocolError("issuer_mismatch", "El id_token tiene un emisor inesperado") from exc
    except jwt.PyJWTError as exc:
        raise SsoProtocolError("invalid_id_token", f"id_token no válido: {exc}") from exc
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != config.client_id:
        raise SsoProtocolError("audience_mismatch", "El id_token tiene varias audiencias sin azp válido")
    if not nonce or claims.get("nonce") != nonce:
        raise SsoProtocolError("nonce_mismatch", "El nonce del id_token no coincide (posible repetición)")
    return claims


async def fetch_userinfo(meta: ProviderMetadata, access_token: str) -> dict[str, Any]:
    if not meta.userinfo_endpoint or not access_token:
        return {}
    validate_remote_url(meta.userinfo_endpoint, what="userinfo")
    try:
        async with http_client() as client:
            res = await client.get(meta.userinfo_endpoint, headers={"Authorization": f"Bearer {access_token}"})
    except httpx.HTTPError:
        return {}
    if res.status_code >= 400:
        return {}
    try:
        data = res.json()
    except (json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(v) for v in value if v is not None]
    return [str(value)]


def identity_from_claims(config: OidcConfig, claims: dict[str, Any], userinfo: dict[str, Any]) -> SsoIdentity:
    merged = {**userinfo, **claims}
    if userinfo.get("sub") and str(userinfo["sub"]) != str(claims["sub"]):
        raise SsoProtocolError("subject_mismatch", "userinfo pertenece a otro usuario")
    email: str | None = None
    for claim in (config.email_claim, *config.fallback_email_claims):
        value = merged.get(claim)
        if isinstance(value, str) and "@" in value:
            email = value.strip().lower()
            break
    if not email:
        raise SsoProtocolError("missing_email", "El proveedor no devolvió un email")
    if merged.get("email_verified") is False or merged.get("email_verified") == "false":
        raise SsoProtocolError("email_unverified", "El proveedor indica que el email no está verificado")
    groups = _as_str_list(merged.get(config.groups_claim)) if config.groups_claim else []
    amr = _as_str_list(merged.get("amr"))
    name = merged.get(config.name_claim)
    return SsoIdentity(
        subject=str(claims["sub"]),
        email=email,
        name=str(name) if name else None,
        given_name=str(merged["given_name"]) if merged.get("given_name") else None,
        family_name=str(merged["family_name"]) if merged.get("family_name") else None,
        groups=groups,
        mfa=any(m.lower() in {"mfa", "otp", "hwk", "swk", "fido", "sms"} for m in amr),
        attributes={
            k: merged[k]
            for k in ("iss", "sub", "aud", "hd", "tid", "amr", "acr", config.groups_claim)
            if k in merged and k
        },
    )
