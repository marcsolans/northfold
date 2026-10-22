"""/api/v1/auth — sign-up, login, MFA, sessions, password reset, email verification, social login."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import AuthCredential, AuthSession, Membership, Org, User
from messer_common.email import send_template
from messer_common.security import TokenError, decode_access_token, hash_password, sign_payload, verify_signed_payload
from messer_common.settings import get_settings

from ..deps import ACCESS_COOKIE, ORG_COOKIE, REFRESH_COOKIE, client_ip, get_principal
from ..errors import ApiError, Unauthorized
from ..ratelimit import rate_limit
from ..services import auth as auth_service
from ..services import oauth_login
from ..services import sso as sso_service
from ..services.orgs import accept_invitation, create_org

router = APIRouter(prefix="/auth", tags=["auth"])


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    org_name: str | None = Field(default=None, max_length=200)
    locale: Literal["es", "en"] = "es"
    invitation_token: str | None = None
    accept_terms: bool = True


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    mfa_code: str | None = None


class MfaVerifyIn(BaseModel):
    mfa_token: str
    code: str


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str
    password: str = Field(min_length=10, max_length=200)


class TokenIn(BaseModel):
    token: str


class CodeIn(BaseModel):
    code: str


class SupabaseSessionIn(BaseModel):
    access_token: str
    refresh_token: str


class AuthOut(BaseModel):
    user_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    mfa_required: bool = False
    mfa_token: str | None = None
    redirect: str | None = None


def _cookie_secure() -> bool:
    return get_settings().messer_web_url.startswith("https://")


def set_session_cookies(response: Response, tokens: auth_service.SessionTokens, org_id: uuid.UUID | None) -> None:
    settings = get_settings()
    secure = _cookie_secure()
    response.set_cookie(
        ACCESS_COOKIE,
        tokens.access_token,
        max_age=tokens.expires_in,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE,
        tokens.refresh_token,
        max_age=settings.messer_refresh_token_ttl_s,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/api/v1/auth",
    )
    if org_id:
        response.set_cookie(
            ORG_COOKIE,
            str(org_id),
            max_age=settings.messer_refresh_token_ttl_s,
            httponly=False,
            secure=secure,
            samesite="lax",
            path="/",
        )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.delete_cookie(ORG_COOKIE, path="/")


async def _first_org(session: Any, user_id: uuid.UUID) -> uuid.UUID | None:
    row = (
        await session.execute(
            select(Membership.org_id).where(Membership.user_id == user_id).order_by(Membership.created_at)
        )
    ).first()
    return row[0] if row else None


async def _after_new_user(
    session: Any, user: User, body_org_name: str | None, invitation_token: str | None, locale: str
) -> uuid.UUID:
    """New account: accept an invitation, or create the organization and start the trial."""
    if invitation_token:
        membership = await accept_invitation(session, token=invitation_token, user=user)
        return membership.org_id
    org_name = body_org_name or (f"{user.name}" if user.name else user.email.split("@")[0])
    org = await create_org(session, owner=user, name=org_name)
    return org.id


async def _send_verification(user: User) -> None:
    async with system_session() as s:
        token = await auth_service.create_one_time_token(
            s, purpose="verify_email", user_id=user.id, ttl=timedelta(days=3)
        )
    url = f"{get_settings().messer_web_url}/verify-email?token={token}"
    await send_template(user.email, "verify_email", {"name": user.name or user.email, "url": url}, user.locale)


@router.get("/config")
async def auth_config() -> dict[str, Any]:
    """Which login methods are available (drives the login/sign-up screens)."""
    s = get_settings()
    return {
        "mode": "supabase" if s.has_supabase else "local",
        "providers": {
            "google": s.has_supabase or bool(s.google_client_id),
            "microsoft": s.has_supabase or bool(s.microsoft_client_id),
        },
        "sso": True,
    }


@router.post("/signup", response_model=AuthOut, dependencies=[Depends(rate_limit("signup", 10, 60))])
async def signup(body: SignupIn, request: Request, response: Response) -> AuthOut:
    if not body.accept_terms:
        raise ApiError("Debes aceptar los términos del servicio", code="terms_required")
    settings = get_settings()
    async with system_session() as s:
        if settings.has_supabase:
            supa = auth_service.SupabaseAuth()
            auth_service.validate_password(body.password)
            data = await supa.signup(body.email, body.password, body.name)
            sb_user = data.get("user") or data
            user, _ = await auth_service.ensure_user(
                s, user_id=uuid.UUID(sb_user["id"]), email=body.email, name=body.name, locale=body.locale
            )
            org_id = await _after_new_user(s, user, body.org_name, body.invitation_token, body.locale)
            if data.get("access_token"):
                tokens = auth_service.SessionTokens(
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    expires_in=int(data.get("expires_in", 3600)),
                    user_id=user.id,
                )
                set_session_cookies(response, tokens, org_id)
            await audit.record(
                s, action="auth.signup", principal=Principal(user_id=user.id, org_id=org_id), ip=client_ip(request)
            )
            return AuthOut(user_id=user.id, org_id=org_id, redirect="/onboarding")

        user = await auth_service.local_signup(
            s, email=body.email, password=body.password, name=body.name, locale=body.locale
        )
        org_id = await _after_new_user(s, user, body.org_name, body.invitation_token, body.locale)
        tokens = await auth_service.open_session(
            s, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request), mfa_verified=False
        )
        await audit.record(
            s, action="auth.signup", principal=Principal(user_id=user.id, org_id=org_id), ip=client_ip(request)
        )
    await _send_verification(user)
    set_session_cookies(response, tokens, org_id)
    return AuthOut(user_id=user.id, org_id=org_id, redirect="/onboarding")


@router.post("/login", response_model=AuthOut, dependencies=[Depends(rate_limit("login", 20, 60))])
async def login(body: LoginIn, request: Request, response: Response) -> AuthOut:
    settings = get_settings()
    async with system_session() as s:
        await sso_service.assert_password_login_allowed(s, body.email)  # "enforce SSO for this domain"
        if settings.has_supabase:
            data = await auth_service.SupabaseAuth().password_login(body.email, body.password)
            sb_user = data["user"]
            user, _ = await auth_service.ensure_user(
                s, user_id=uuid.UUID(sb_user["id"]), email=body.email, name=sb_user.get("user_metadata", {}).get("name")
            )
            tokens = auth_service.SessionTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_in=int(data.get("expires_in", 3600)),
                user_id=user.id,
            )
        else:
            user = await auth_service.local_login(s, email=body.email, password=body.password)
            tokens = None  # issued after the MFA check
        if await auth_service.mfa_enabled(s, user.id):
            if not body.mfa_code:
                challenge = sign_payload({"sub": str(user.id), "purpose": "mfa"}, ttl_s=300)
                return AuthOut(user_id=user.id, mfa_required=True, mfa_token=challenge)
            if not await auth_service.mfa_verify(s, user.id, body.mfa_code):
                raise Unauthorized("Código MFA incorrecto", code="invalid_mfa_code")
            mfa_ok = True
        else:
            mfa_ok = False
        if tokens is None:
            tokens = await auth_service.open_session(
                s, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request), mfa_verified=mfa_ok
            )
        org_id = await _first_org(s, user.id)
        await audit.record(
            s,
            action="auth.login",
            principal=Principal(user_id=user.id, org_id=org_id),
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    set_session_cookies(response, tokens, org_id)
    return AuthOut(user_id=user.id, org_id=org_id, redirect="/app" if org_id else "/onboarding")


@router.post("/mfa/verify", response_model=AuthOut, dependencies=[Depends(rate_limit("mfa", 20, 60))])
async def mfa_verify_login(body: MfaVerifyIn, request: Request, response: Response) -> AuthOut:
    try:
        claims = verify_signed_payload(body.mfa_token)
    except TokenError as exc:
        raise Unauthorized("El desafío MFA ha caducado", code="mfa_expired") from exc
    if claims.get("purpose") != "mfa":
        raise Unauthorized("Desafío MFA no válido", code="mfa_invalid")
    user_id = uuid.UUID(claims["sub"])
    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None or not await auth_service.mfa_verify(s, user_id, body.code):
            raise Unauthorized("Código MFA incorrecto", code="invalid_mfa_code")
        tokens = await auth_service.open_session(
            s, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request), mfa_verified=True
        )
        org_id = await _first_org(s, user.id)
    set_session_cookies(response, tokens, org_id)
    return AuthOut(user_id=user_id, org_id=org_id, redirect="/app" if org_id else "/onboarding")


@router.post("/refresh", response_model=AuthOut)
async def refresh(request: Request, response: Response) -> AuthOut:
    refresh_token = request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise Unauthorized("No hay sesión", code="no_session")
    settings = get_settings()
    async with system_session() as s:
        if settings.has_supabase:
            data = await auth_service.SupabaseAuth().refresh(refresh_token)
            tokens = auth_service.SessionTokens(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_in=int(data.get("expires_in", 3600)),
                user_id=uuid.UUID(data["user"]["id"]),
            )
        else:
            tokens = await auth_service.refresh_session(s, refresh_token)
    set_session_cookies(response, tokens, None)
    return AuthOut(user_id=tokens.user_id)


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, bool]:
    async with system_session() as s:
        await auth_service.revoke_session(s, request.cookies.get(REFRESH_COOKIE))
    clear_session_cookies(response)
    return {"ok": True}


@router.post("/supabase/session", response_model=AuthOut)
async def supabase_session(body: SupabaseSessionIn, response: Response) -> AuthOut:
    """Store tokens obtained by the browser from a Supabase OAuth redirect."""
    try:
        claims = decode_access_token(body.access_token)
    except TokenError as exc:
        raise Unauthorized("Token de Supabase no válido", code="invalid_token") from exc
    async with system_session() as s:
        await sso_service.assert_password_login_allowed(s, str(claims.get("email", "")))
        meta = claims.get("user_metadata") or {}
        user, created = await auth_service.ensure_user(
            s,
            user_id=uuid.UUID(claims["sub"]),
            email=claims.get("email", ""),
            name=meta.get("full_name") or meta.get("name"),
            avatar=meta.get("avatar_url"),
        )
        org_id = await _first_org(s, user.id)
        if org_id is None:
            org_id = (await create_org(s, owner=user, name=user.name or user.email.split("@")[0])).id
    tokens = auth_service.SessionTokens(
        access_token=body.access_token,
        refresh_token=body.refresh_token,
        expires_in=max(60, int(claims.get("exp", 0)) - int(datetime.now(UTC).timestamp())),
        user_id=user.id,
    )
    set_session_cookies(response, tokens, org_id)
    return AuthOut(user_id=user.id, org_id=org_id, redirect="/onboarding" if created else "/app")


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, next: str = "/app") -> RedirectResponse:
    settings = get_settings()
    safe_next = next if next.startswith("/") and not next.startswith("//") else "/app"
    if settings.has_supabase:
        redirect_to = f"{settings.messer_web_url}/auth/callback?next={safe_next}"
        supa_provider = "azure" if provider == "microsoft" else provider
        return RedirectResponse(auth_service.SupabaseAuth().authorize_url(supa_provider, redirect_to), status_code=302)
    config = oauth_login.provider_config(provider)
    if config is None:
        raise ApiError(
            f"El inicio de sesión con {provider} no está configurado", code="provider_unavailable", status_code=404
        )
    async with system_session() as s:
        url = await oauth_login.start(s, config, safe_next)
    return RedirectResponse(url, status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(provider: str, request: Request, code: str = "", state: str = "") -> RedirectResponse:
    settings = get_settings()
    config = oauth_login.provider_config(provider)
    if config is None or not code or not state:
        return RedirectResponse(f"{settings.messer_web_url}/login?error=oauth", status_code=302)
    async with system_session() as s:
        identity = await oauth_login.finish(s, config, code, state)
        try:
            await sso_service.assert_password_login_allowed(s, identity.email)
        except ApiError as exc:
            return RedirectResponse(f"{settings.messer_web_url}/sso/error?code={exc.code}", status_code=302)
        user = await auth_service.find_user_by_email(s, identity.email)
        created = False
        if user is None:
            user, created = await auth_service.ensure_user(
                s, user_id=uuid.uuid4(), email=identity.email, name=identity.name, avatar=identity.avatar
            )
            s.add(AuthCredential(user_id=user.id, email_verified_at=datetime.now(UTC)))
        org_id = await _first_org(s, user.id)
        if org_id is None:
            org_id = (await create_org(s, owner=user, name=user.name or user.email.split("@")[0])).id
        mfa = await auth_service.mfa_enabled(s, user.id)
        if mfa:
            challenge = sign_payload({"sub": str(user.id), "purpose": "mfa"}, ttl_s=300)
            return RedirectResponse(f"{settings.messer_web_url}/mfa?token={challenge}", status_code=302)
        tokens = await auth_service.open_session(
            s, user, user_agent=request.headers.get("user-agent"), ip=client_ip(request), mfa_verified=False
        )
    target = "/onboarding" if created else identity.next_path
    response = RedirectResponse(f"{settings.messer_web_url}{target}", status_code=302)
    set_session_cookies(response, tokens, org_id)
    return response


@router.post("/password/forgot", dependencies=[Depends(rate_limit("forgot", 5, 60))])
async def forgot_password(body: EmailIn) -> dict[str, bool]:
    settings = get_settings()
    if settings.has_supabase:
        await auth_service.SupabaseAuth().recover(body.email, f"{settings.messer_web_url}/reset-password")
        return {"ok": True}
    async with system_session() as s:
        user = await auth_service.find_user_by_email(s, body.email)
        if user is None:
            return {"ok": True}  # never reveal whether an email exists
        token = await auth_service.create_one_time_token(
            s, purpose="password_reset", user_id=user.id, ttl=timedelta(hours=1)
        )
    await send_template(
        user.email, "password_reset", {"url": f"{settings.messer_web_url}/reset-password?token={token}"}, user.locale
    )
    return {"ok": True}


@router.post("/password/reset", dependencies=[Depends(rate_limit("reset", 10, 60))])
async def reset_password(body: ResetIn) -> dict[str, bool]:
    auth_service.validate_password(body.password)
    async with system_session() as s:
        row = await auth_service.consume_one_time_token(s, purpose="password_reset", token=body.token)
        assert row.user_id is not None
        cred = await s.get(AuthCredential, row.user_id)
        if cred is None:
            cred = AuthCredential(user_id=row.user_id)
            s.add(cred)
        cred.password_hash = hash_password(body.password)
        cred.failed_attempts = 0
        cred.locked_until = None
        # Revoke every open session after a password change.
        sessions = (await s.execute(select(AuthSession).where(AuthSession.user_id == row.user_id))).scalars()
        for sess in sessions:
            sess.revoked_at = sess.revoked_at or datetime.now(UTC)
        await audit.record(s, action="auth.password_reset", principal=Principal(user_id=row.user_id))
    return {"ok": True}


@router.post("/verify-email")
async def verify_email(body: TokenIn) -> dict[str, bool]:
    async with system_session() as s:
        row = await auth_service.consume_one_time_token(s, purpose="verify_email", token=body.token)
        assert row.user_id is not None
        cred = await s.get(AuthCredential, row.user_id)
        if cred is None:
            cred = AuthCredential(user_id=row.user_id)
            s.add(cred)
        cred.email_verified_at = datetime.now(UTC)
    return {"ok": True}


@router.post("/verify-email/resend", dependencies=[Depends(rate_limit("verify_resend", 3, 60))])
async def resend_verification(principal: Principal = Depends(get_principal)) -> dict[str, bool]:
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
    if user is not None:
        await _send_verification(user)
    return {"ok": True}


# ----------------------------------------------------------------------------- MFA management


@router.post("/mfa/setup")
async def mfa_setup(principal: Principal = Depends(get_principal)) -> dict[str, str]:
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
        assert user is not None
        secret, uri = await auth_service.mfa_begin_setup(s, user)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/mfa/confirm")
async def mfa_confirm(body: CodeIn, principal: Principal = Depends(get_principal)) -> dict[str, list[str]]:
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
        assert user is not None
        codes = await auth_service.mfa_confirm_setup(s, user, body.code)
        await audit.record(s, action="auth.mfa_enabled", principal=principal)
    return {"recovery_codes": codes}


@router.post("/mfa/disable")
async def mfa_disable(body: CodeIn, principal: Principal = Depends(get_principal)) -> dict[str, bool]:
    async with system_session() as s:
        if not await auth_service.mfa_verify(s, principal.user_id, body.code):  # type: ignore[arg-type]
            raise Unauthorized("Código MFA incorrecto", code="invalid_mfa_code")
        await auth_service.mfa_disable(s, principal.user_id)  # type: ignore[arg-type]
        await audit.record(s, action="auth.mfa_disabled", principal=principal)
    return {"ok": True}


@router.post("/invitations/accept")
async def accept_invite(
    body: TokenIn, response: Response, principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
        assert user is not None
        membership = await accept_invitation(s, token=body.token, user=user)
        org = await s.get(Org, membership.org_id)
    response.set_cookie(
        ORG_COOKIE, str(membership.org_id), httponly=False, samesite="lax", path="/", secure=_cookie_secure()
    )
    return {"org_id": str(membership.org_id), "org_name": org.name if org else "", "role": membership.role}
