"""Social login (Google, Microsoft) without Supabase: OAuth 2.0 authorization code + PKCE + OIDC userinfo."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.security import random_token
from messer_common.settings import get_settings

from ..errors import ApiError
from .auth import consume_one_time_token, create_one_time_token


@dataclass(frozen=True, slots=True)
class Provider:
    key: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id: str
    client_secret: str


def provider_config(key: str) -> Provider | None:
    s = get_settings()
    if key == "google" and s.google_client_id:
        return Provider(
            key="google",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
            scope="openid email profile",
            client_id=s.google_client_id,
            client_secret=s.google_client_secret,
        )
    if key == "microsoft" and s.microsoft_client_id:
        tenant = s.microsoft_tenant_id or "common"
        return Provider(
            key="microsoft",
            authorize_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            token_url=f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            userinfo_url="https://graph.microsoft.com/oidc/userinfo",
            scope="openid email profile",
            client_id=s.microsoft_client_id,
            client_secret=s.microsoft_client_secret,
        )
    return None


def callback_url(provider: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/auth/oauth/{provider}/callback"


def _pkce() -> tuple[str, str]:
    verifier = random_token(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def start(session: AsyncSession, provider: Provider, next_path: str) -> str:
    verifier, challenge = _pkce()
    state = await create_one_time_token(
        session,
        purpose="oauth_state",
        user_id=None,
        ttl=timedelta(minutes=10),
        payload={"provider": provider.key, "verifier": verifier, "next": next_path},
    )
    params = {
        "client_id": provider.client_id,
        "response_type": "code",
        "redirect_uri": callback_url(provider.key),
        "scope": provider.scope,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


@dataclass(slots=True)
class OAuthIdentity:
    email: str
    name: str | None
    avatar: str | None
    subject: str
    next_path: str


async def finish(session: AsyncSession, provider: Provider, code: str, state: str) -> OAuthIdentity:
    row = await consume_one_time_token(session, purpose="oauth_state", token=state)
    if row.payload.get("provider") != provider.key:
        raise ApiError("Estado OAuth no válido", code="oauth_state")
    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            provider.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": callback_url(provider.key),
                "client_id": provider.client_id,
                "client_secret": provider.client_secret,
                "code_verifier": row.payload["verifier"],
            },
        )
        if token_res.status_code >= 400:
            raise ApiError("No se pudo completar el inicio de sesión", code="oauth_exchange")
        access_token = token_res.json().get("access_token")
        info_res = await client.get(provider.userinfo_url, headers={"Authorization": f"Bearer {access_token}"})
        if info_res.status_code >= 400:
            raise ApiError("No se pudo leer el perfil", code="oauth_userinfo")
        info = info_res.json()
    email = info.get("email") or info.get("preferred_username")
    if not email:
        raise ApiError("El proveedor no ha devuelto un email", code="oauth_no_email")
    if provider.key == "google" and info.get("email_verified") is False:
        raise ApiError("El email de Google no está verificado", code="oauth_unverified")
    return OAuthIdentity(
        email=str(email).lower(),
        name=info.get("name"),
        avatar=info.get("picture"),
        subject=str(info.get("sub")),
        next_path=str(row.payload.get("next") or "/app"),
    )
