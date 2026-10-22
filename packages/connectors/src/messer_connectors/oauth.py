"""OAuth 2 authorization-code flow for connector providers: authorize URL, code exchange, token refresh.

Credentials are normalized to::

    {"access_token", "refresh_token", "expires_at" (epoch seconds | None), "token_type", "scope", "extra": {...}}

``extra`` keeps provider specifics (Salesforce ``instance_url``, Slack user token and team, Notion workspace).
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from messer_common.security import random_token
from messer_common.settings import get_settings

from . import http as chttp
from .base import ConnectorAuthError, ConnectorError, ConnectorSpec, OAuthSpec

REFRESH_MARGIN_S = 120


@dataclass(frozen=True, slots=True)
class OAuthApp:
    client_id: str
    client_secret: str


def oauth_app(spec: ConnectorSpec) -> OAuthApp | None:
    """The configured OAuth app for a connector, or ``None`` (→ demo mode)."""
    if spec.oauth is None:
        return None
    settings = get_settings()
    client_id = str(getattr(settings, spec.oauth.client_id_setting, "") or "")
    client_secret = str(getattr(settings, spec.oauth.client_secret_setting, "") or "")
    if not client_id or not client_secret:
        return None
    return OAuthApp(client_id=client_id, client_secret=client_secret)


def missing_env(spec: ConnectorSpec) -> list[str]:
    if spec.oauth is None:
        return []
    settings = get_settings()
    return [
        env
        for env, attr in zip(
            spec.oauth.env_vars, (spec.oauth.client_id_setting, spec.oauth.client_secret_setting), strict=True
        )
        if not getattr(settings, attr, "")
    ]


def _format_url(url: str) -> str:
    return url.replace("{tenant}", get_settings().microsoft_tenant_id or "common")


def pkce_pair() -> tuple[str, str]:
    verifier = random_token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(spec: ConnectorSpec, *, redirect_uri: str, state: str, code_challenge: str | None = None) -> str:
    oauth = _require_oauth(spec)
    app = oauth_app(spec)
    if app is None:
        raise ConnectorError(
            f"Falta configurar la app OAuth de {spec.name}",
            code="oauth_not_configured",
            details={"missing": missing_env(spec)},
        )
    params: dict[str, str] = {
        "client_id": app.client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": state,
    }
    if oauth.scopes:
        params[oauth.scope_param] = oauth.scope_separator.join(oauth.scopes)
    if oauth.user_scopes:
        params["user_scope"] = oauth.scope_separator.join(oauth.user_scopes)
    if oauth.pkce and code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    params.update(oauth.extra_authorize_params)
    return f"{_format_url(oauth.authorize_url)}?{urlencode(params)}"


def _require_oauth(spec: ConnectorSpec) -> OAuthSpec:
    if spec.oauth is None:
        raise ConnectorError(f"{spec.name} no usa OAuth", code="not_oauth")
    return spec.oauth


async def _token_request(spec: ConnectorSpec, data: dict[str, str]) -> dict[str, Any]:
    oauth = _require_oauth(spec)
    app = oauth_app(spec)
    if app is None:
        raise ConnectorAuthError(f"Falta configurar la app OAuth de {spec.name}", code="oauth_not_configured")
    headers: dict[str, str] = {"Accept": "application/json"}
    body = dict(data)
    if oauth.token_auth == "basic":  # noqa: S105
        basic = base64.b64encode(f"{app.client_id}:{app.client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    else:
        body["client_id"] = app.client_id
        body["client_secret"] = app.client_secret
    async with chttp.client(headers=headers, request_timeout=20) as c:
        try:
            if oauth.token_body == "json":  # noqa: S105
                res = await c.post(_format_url(oauth.token_url), json=body)
            else:
                res = await c.post(_format_url(oauth.token_url), data=body)
        except httpx.HTTPError as exc:
            raise ConnectorError(f"No se puede contactar con {spec.name}: {exc}", code="oauth_unreachable") from exc
    try:
        payload: dict[str, Any] = res.json()
    except ValueError:
        payload = {}
    # Slack answers 200 with {"ok": false, "error": "..."}.
    if res.status_code >= 400 or payload.get("ok") is False or ("error" in payload and not payload.get("access_token")):
        error = str(payload.get("error") or res.status_code)
        description = str(payload.get("error_description") or "")
        if error in ("invalid_grant", "invalid_token", "token_revoked", "invalid_refresh_token", "unauthorized_client"):
            raise ConnectorAuthError(
                f"{spec.name} ha revocado el acceso ({error}). Vuelve a conectar la cuenta.", code="oauth_revoked"
            )
        raise ConnectorError(
            f"{spec.name} no ha aceptado la autorización: {error} {description}".strip(), code="oauth_exchange"
        )
    return payload


def normalize_token_response(spec: ConnectorSpec, payload: dict[str, Any]) -> dict[str, Any]:
    oauth = _require_oauth(spec)
    access = payload.get("access_token")
    extra: dict[str, Any] = {}
    if oauth.provider == "slack":
        authed = payload.get("authed_user") or {}
        if not access:
            access = authed.get("access_token")
        if authed.get("access_token"):
            extra["user_token"] = authed["access_token"]
            extra["user_id"] = authed.get("id")
        team = payload.get("team") or {}
        extra["team_id"] = team.get("id")
        extra["team_name"] = team.get("name")
        extra["bot_user_id"] = payload.get("bot_user_id")
    elif oauth.provider == "salesforce":
        extra["instance_url"] = payload.get("instance_url")
        extra["id_url"] = payload.get("id")
    elif oauth.provider == "notion":
        extra["workspace_id"] = payload.get("workspace_id")
        extra["workspace_name"] = payload.get("workspace_name")
        extra["bot_id"] = payload.get("bot_id")
    elif oauth.provider == "hubspot":
        extra["hub_id"] = payload.get("hub_id")
    if not access:
        raise ConnectorError(f"{spec.name} no ha devuelto un token de acceso", code="oauth_exchange")
    expires_in = payload.get("expires_in")
    expires_at: float | None = None
    if expires_in is not None:
        try:
            expires_at = time.time() + float(expires_in)
        except (TypeError, ValueError):
            expires_at = None
    scope = payload.get("scope")
    return {
        "access_token": access,
        "refresh_token": payload.get("refresh_token"),
        "expires_at": expires_at,
        "token_type": payload.get("token_type") or "Bearer",
        "scope": scope if isinstance(scope, str) else " ".join(scope or []),
        "extra": {k: v for k, v in extra.items() if v is not None},
        "obtained_at": time.time(),
    }


async def exchange_code(
    spec: ConnectorSpec, *, code: str, redirect_uri: str, code_verifier: str | None = None
) -> dict[str, Any]:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    oauth = _require_oauth(spec)
    if oauth.pkce and code_verifier:
        data["code_verifier"] = code_verifier
    payload = await _token_request(spec, data)
    return normalize_token_response(spec, payload)


def needs_refresh(credentials: dict[str, Any], *, margin_s: int = REFRESH_MARGIN_S) -> bool:
    expires_at = credentials.get("expires_at")
    if not expires_at:
        return False
    try:
        return float(expires_at) - margin_s <= time.time()
    except (TypeError, ValueError):
        return True


async def refresh(spec: ConnectorSpec, credentials: dict[str, Any]) -> dict[str, Any]:
    """Refresh an access token. Providers that do not rotate refresh tokens keep the previous one."""
    oauth = _require_oauth(spec)
    refresh_token = credentials.get("refresh_token")
    if not refresh_token or not oauth.supports_refresh:
        raise ConnectorAuthError(
            f"La sesión de {spec.name} ha caducado y no se puede renovar. Vuelve a conectar la cuenta.",
            code="oauth_expired",
        )
    data = {"grant_type": "refresh_token", "refresh_token": str(refresh_token)}
    if oauth.provider == "microsoft" and oauth.scopes:
        data["scope"] = oauth.scope_separator.join(oauth.scopes)
    payload = await _token_request(spec, data)
    fresh = normalize_token_response(spec, payload)
    if not fresh.get("refresh_token"):
        fresh["refresh_token"] = refresh_token
    merged_extra = {**(credentials.get("extra") or {}), **fresh["extra"]}
    fresh["extra"] = merged_extra
    if not fresh.get("scope"):
        fresh["scope"] = credentials.get("scope", "")
    return fresh
