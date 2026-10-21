"""Authentication backends.

* Local backend (default): email + password stored with Argon2id, refresh-token sessions in
  ``auth_sessions``, Messer-signed access JWTs with Supabase-compatible claims.
* Supabase backend (when SUPABASE_URL/ANON_KEY are set): delegates credentials to Supabase Auth
  (GoTrue) and stores its tokens in the same cookies; user rows reuse the Supabase uid.

Both return a :class:`SessionTokens`. MFA (TOTP) is enforced by Messer in both modes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pyotp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import AuthCredential, AuthSession, OneTimeToken, User
from messer_common.security import (
    decrypt,
    encrypt,
    hash_password,
    hash_token,
    issue_access_token,
    random_token,
    verify_password,
)
from messer_common.settings import get_settings

from ..errors import ApiError, Conflict, Unauthorized

MAX_FAILED_ATTEMPTS = 8
LOCK_MINUTES = 15
MIN_PASSWORD_LENGTH = 10


@dataclass(slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    expires_in: int
    user_id: uuid.UUID


@dataclass(slots=True)
class MfaChallenge:
    mfa_token: str
    user_id: uuid.UUID


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ApiError(f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres", code="weak_password")
    if password.lower() == password or not any(c.isdigit() for c in password):
        raise ApiError("La contraseña debe combinar mayúsculas, minúsculas y números", code="weak_password")


async def find_user_by_email(session: AsyncSession, email: str) -> User | None:
    return (
        await session.execute(select(User).where(func.lower(User.email) == email.strip().lower()))
    ).scalar_one_or_none()


async def ensure_user(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    email: str,
    name: str | None,
    avatar: str | None = None,
    locale: str = "es",
) -> tuple[User, bool]:
    user = await session.get(User, user_id)
    if user is not None:
        return user, False
    existing = await find_user_by_email(session, email)
    if existing is not None:
        return existing, False
    user = User(id=user_id, email=email.strip().lower(), name=name, avatar=avatar, locale=locale)
    session.add(user)
    await session.flush()
    return user, True


# ----------------------------------------------------------------------------- local sessions


async def open_session(
    session: AsyncSession,
    user: User,
    *,
    user_agent: str | None,
    ip: str | None,
    mfa_verified: bool,
    impersonated_by: uuid.UUID | None = None,
    ttl_s: int | None = None,
) -> SessionTokens:
    settings = get_settings()
    refresh = random_token(32)
    auth_session = AuthSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh),
        user_agent=(user_agent or "")[:500],
        ip=ip,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.messer_refresh_token_ttl_s),
        mfa_verified=mfa_verified,
        impersonated_by=impersonated_by,
    )
    session.add(auth_session)
    await session.flush()
    user.last_login_at = datetime.now(UTC)
    ttl = ttl_s or settings.messer_access_token_ttl_s
    access = issue_access_token(
        user_id=user.id,
        email=user.email,
        session_id=auth_session.id,
        impersonated_by=impersonated_by,
        mfa_verified=mfa_verified,
        ttl_s=ttl,
    )
    return SessionTokens(access_token=access, refresh_token=refresh, expires_in=ttl, user_id=user.id)


async def refresh_session(session: AsyncSession, refresh_token: str) -> SessionTokens:
    row = (
        await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(refresh_token)))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None or row.revoked_at is not None or row.expires_at < now:
        raise Unauthorized("Sesión caducada", code="session_expired")
    user = await session.get(User, row.user_id)
    if user is None or user.status == "blocked" or user.deleted_at is not None:
        raise Unauthorized("Sesión no válida", code="session_invalid")
    # Rotate: revoke the old refresh token and issue a new one.
    row.revoked_at = now
    return await open_session(
        session,
        user,
        user_agent=row.user_agent,
        ip=row.ip,
        mfa_verified=row.mfa_verified,
        impersonated_by=row.impersonated_by,
    )


async def revoke_session(session: AsyncSession, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    row = (
        await session.execute(select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(refresh_token)))
    ).scalar_one_or_none()
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


# ----------------------------------------------------------------------------- local signup / login


async def local_signup(session: AsyncSession, *, email: str, password: str, name: str | None, locale: str) -> User:
    validate_password(password)
    if await find_user_by_email(session, email) is not None:
        raise Conflict("Ya existe una cuenta con este email", code="email_taken")
    user = User(id=uuid.uuid4(), email=email.strip().lower(), name=(name or "").strip() or None, locale=locale)
    session.add(user)
    await session.flush()
    session.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
    return user


async def local_login(session: AsyncSession, *, email: str, password: str) -> User:
    user = await find_user_by_email(session, email)
    generic = Unauthorized("Email o contraseña incorrectos", code="invalid_credentials")
    if user is None or user.deleted_at is not None:
        hash_password(password)  # equalize timing
        raise generic
    cred = await session.get(AuthCredential, user.id)
    if cred is None or not cred.password_hash:
        raise generic
    now = datetime.now(UTC)
    if cred.locked_until and cred.locked_until > now:
        raise ApiError("Demasiados intentos. Inténtalo más tarde.", code="account_locked", status_code=429)
    if not verify_password(cred.password_hash, password):
        cred.failed_attempts += 1
        if cred.failed_attempts >= MAX_FAILED_ATTEMPTS:
            cred.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            cred.failed_attempts = 0
        raise generic
    if user.status == "blocked":
        raise ApiError("Tu cuenta está bloqueada. Contacta con soporte.", code="user_blocked", status_code=403)
    cred.failed_attempts = 0
    cred.locked_until = None
    return user


# ----------------------------------------------------------------------------- one-time tokens


async def create_one_time_token(
    session: AsyncSession,
    *,
    purpose: str,
    user_id: uuid.UUID | None,
    ttl: timedelta,
    payload: dict[str, Any] | None = None,
) -> str:
    token = random_token(32)
    session.add(
        OneTimeToken(
            purpose=purpose,
            token_hash=hash_token(token),
            user_id=user_id,
            payload=payload or {},
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.flush()
    return token


async def consume_one_time_token(session: AsyncSession, *, purpose: str, token: str) -> OneTimeToken:
    row = (
        await session.execute(
            select(OneTimeToken)
            .where(OneTimeToken.token_hash == hash_token(token), OneTimeToken.purpose == purpose)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise ApiError("Enlace no válido", code="invalid_token", status_code=400)
    if row.used_at is not None:
        raise ApiError("Este enlace ya se ha usado", code="token_used", status_code=410)
    if row.expires_at < datetime.now(UTC):
        raise ApiError("Este enlace ha caducado", code="token_expired", status_code=410)
    row.used_at = datetime.now(UTC)
    return row


# ----------------------------------------------------------------------------- MFA (TOTP)


async def mfa_enabled(session: AsyncSession, user_id: uuid.UUID) -> bool:
    cred = await session.get(AuthCredential, user_id)
    return bool(cred and cred.mfa_enabled)


async def mfa_begin_setup(session: AsyncSession, user: User) -> tuple[str, str]:
    cred = await session.get(AuthCredential, user.id)
    if cred is None:
        cred = AuthCredential(user_id=user.id)
        session.add(cred)
    secret = pyotp.random_base32()
    cred.mfa_secret_encrypted = encrypt(secret)
    cred.mfa_enabled = False
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="Messer")
    return secret, uri


def _verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code.strip().replace(" ", ""), valid_window=1)


async def mfa_confirm_setup(session: AsyncSession, user: User, code: str) -> list[str]:
    cred = await session.get(AuthCredential, user.id)
    if cred is None or not cred.mfa_secret_encrypted:
        raise ApiError("Inicia la configuración de MFA primero", code="mfa_not_started")
    if not _verify_totp(decrypt(cred.mfa_secret_encrypted), code):
        raise ApiError("Código incorrecto", code="invalid_mfa_code")
    recovery = [random_token(6) for _ in range(8)]
    cred.mfa_recovery_codes = [hash_token(c) for c in recovery]
    cred.mfa_enabled = True
    return recovery


async def mfa_verify(session: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    cred = await session.get(AuthCredential, user_id)
    if cred is None or not cred.mfa_enabled or not cred.mfa_secret_encrypted:
        return False
    if _verify_totp(decrypt(cred.mfa_secret_encrypted), code):
        return True
    hashed = hash_token(code.strip())
    codes = list(cred.mfa_recovery_codes or [])
    if hashed in codes:
        codes.remove(hashed)
        cred.mfa_recovery_codes = codes
        return True
    return False


async def mfa_disable(session: AsyncSession, user_id: uuid.UUID) -> None:
    cred = await session.get(AuthCredential, user_id)
    if cred is not None:
        cred.mfa_enabled = False
        cred.mfa_secret_encrypted = None
        cred.mfa_recovery_codes = []


# ----------------------------------------------------------------------------- Supabase backend


class SupabaseAuth:
    """Thin client for Supabase Auth (GoTrue)."""

    def __init__(self) -> None:
        s = get_settings()
        self.base = s.supabase_url.rstrip("/") + "/auth/v1"
        self.headers = {"apikey": s.supabase_anon_key, "Content-Type": "application/json"}

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(self.base + path, json=body, headers=self.headers)
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            message = data.get("msg") or data.get("error_description") or data.get("message") or "Supabase Auth error"
            raise Unauthorized(str(message), code="supabase_auth")
        return data

    async def signup(self, email: str, password: str, name: str | None) -> dict[str, Any]:
        return await self._post("/signup", {"email": email, "password": password, "data": {"name": name}})

    async def password_login(self, email: str, password: str) -> dict[str, Any]:
        return await self._post("/token?grant_type=password", {"email": email, "password": password})

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._post("/token?grant_type=refresh_token", {"refresh_token": refresh_token})

    async def recover(self, email: str, redirect_to: str) -> None:
        await self._post("/recover", {"email": email, "redirect_to": redirect_to})

    def authorize_url(self, provider: str, redirect_to: str) -> str:
        from urllib.parse import urlencode

        return f"{self.base}/authorize?" + urlencode({"provider": provider, "redirect_to": redirect_to})
