"""Request dependencies: authentication, active organization, roles and RLS sessions.

Authentication sources, in order:
1. ``Authorization: Bearer msr_…``  → organization API key (acts as ``builder`` within its scopes)
2. ``Authorization: Bearer <jwt>``  → Messer or Supabase access token
3. ``messer_at`` cookie             → browser session (set by /auth endpoints)

The active organization comes from the ``X-Messer-Org`` header or the ``messer_org`` cookie
and must be one the user belongs to. Superadmins may act in any organization.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, rls_session, system_session
from messer_common.db.models import ApiKey, Membership, Org, Subscription, User
from messer_common.security import TokenError, decode_access_token, hash_token

from .errors import Forbidden, PaymentRequired, Unauthorized

ACCESS_COOKIE = "messer_at"
REFRESH_COOKIE = "messer_rt"
ORG_COOKIE = "messer_org"
ROLE_RANK = {"viewer": 1, "builder": 2, "admin": 3, "owner": 4}
GRACE_DAYS = 7


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def _requested_org(request: Request) -> uuid.UUID | None:
    raw = request.headers.get("x-messer-org") or request.cookies.get(ORG_COOKIE)
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def _principal_from_api_key(token: str) -> Principal:
    async with system_session() as s:
        key = (await s.execute(select(ApiKey).where(ApiKey.hashed_key == hash_token(token)))).scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            raise Unauthorized("API key no válida o revocada", code="invalid_api_key")
        await s.execute(update(ApiKey).where(ApiKey.id == key.id).values(last_used_at=datetime.now(UTC)))
        return Principal(
            user_id=key.created_by,
            org_id=key.org_id,
            role="builder",
            api_key_id=key.id,
            scopes=list(key.scopes or []),
            project_id=key.project_id,
            mfa_verified=True,
        )


async def _principal_from_jwt(token: str, request: Request) -> Principal:
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise Unauthorized("Sesión caducada o no válida", code="invalid_token") from exc
    try:
        user_id = uuid.UUID(str(claims["sub"]))
    except (KeyError, ValueError) as exc:
        raise Unauthorized("Token sin sujeto válido", code="invalid_token") from exc
    impersonated_by = uuid.UUID(claims["imp"]) if claims.get("imp") else None

    async with system_session() as s:
        user = await s.get(User, user_id)
        if user is None or user.deleted_at is not None:
            raise Unauthorized("Usuario no encontrado", code="unknown_user")
        if user.status == "blocked":
            raise Forbidden("Tu cuenta está bloqueada. Contacta con soporte.", code="user_blocked")
        principal = Principal(
            user_id=user.id,
            email=user.email,
            is_superadmin=user.is_superadmin and impersonated_by is None,
            impersonated_by=impersonated_by,
            mfa_verified=claims.get("aal") == "aal2",
        )
        org_id = _requested_org(request)
        if org_id is None:
            first = (
                await s.execute(
                    select(Membership.org_id).where(Membership.user_id == user.id).order_by(Membership.created_at)
                )
            ).first()
            org_id = first[0] if first else None
        if org_id is not None:
            role = (
                await s.execute(
                    select(Membership.role).where(Membership.user_id == user.id, Membership.org_id == org_id)
                )
            ).scalar_one_or_none()
            if role is None and not principal.is_superadmin:
                org_id = None
            principal.org_id = org_id
            principal.role = role or ("owner" if principal.is_superadmin and org_id else None)
    return principal


async def get_optional_principal(request: Request) -> Principal | None:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    token = _bearer(request) or request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    if token.startswith("msr_"):
        principal = await _principal_from_api_key(token)
    else:
        principal = await _principal_from_jwt(token, request)
    request.state.principal = principal
    return principal


async def get_principal(request: Request) -> Principal:
    principal = await get_optional_principal(request)
    if principal is None:
        raise Unauthorized("Inicia sesión para continuar", code="not_authenticated")
    return principal


async def get_org_principal(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.org_id is None:
        raise Forbidden("Selecciona o crea una organización", code="no_active_org")
    return principal


async def org_billing_state(org_id: uuid.UUID) -> dict[str, Any]:
    """Return {status, read_only, blocked, plan_id, trial_ends_at, grace_ends_at} for an organization."""
    async with system_session() as s:
        org = await s.get(Org, org_id)
        sub = (await s.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one_or_none()
    blocked = bool(org and org.status == "blocked")
    status = sub.status if sub else "none"
    now = datetime.now(UTC)
    read_only = False
    grace_ends_at = None
    if sub is not None:
        if sub.status == "canceled":
            read_only = True
        elif sub.status == "past_due":
            since = sub.past_due_since or now
            grace_ends_at = since + timedelta(days=GRACE_DAYS)
            read_only = now > grace_ends_at
        elif sub.status == "trialing" and sub.trial_ends_at and sub.trial_ends_at < now:
            read_only = True
            status = "trial_expired"
    return {
        "status": status,
        "plan_id": sub.plan_id if sub else (org.plan_id if org else None),
        "read_only": read_only,
        "blocked": blocked,
        "trial_ends_at": sub.trial_ends_at if sub else None,
        "grace_ends_at": grace_ends_at,
    }


def require_role(min_role: str, *, allow_read_only: bool = False) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """Dependency factory: the principal must hold at least ``min_role`` in the active organization.

    Roles that can write (builder and above) are also refused when the organization is blocked
    or in read-only billing state, unless ``allow_read_only`` (used by billing endpoints).
    """

    async def dependency(principal: Principal = Depends(get_org_principal)) -> Principal:
        rank = ROLE_RANK.get(principal.role or "", 0)
        if not principal.is_superadmin and rank < ROLE_RANK[min_role]:
            raise Forbidden(
                f"Necesitas el rol {min_role} o superior",
                code="insufficient_role",
                details={"required": min_role, "current": principal.role},
            )
        if ROLE_RANK[min_role] >= ROLE_RANK["builder"] and principal.org_id is not None:
            state = await org_billing_state(principal.org_id)
            if state["blocked"] and not principal.is_superadmin:
                raise Forbidden("Esta organización está bloqueada. Contacta con soporte.", code="org_blocked")
            if state["read_only"] and not allow_read_only:
                raise PaymentRequired(
                    "Tu organización está en modo solo lectura. Elige un plan para continuar.",
                    code="read_only",
                    details={"status": state["status"]},
                )
        return principal

    return dependency


def require_superadmin() -> Callable[..., Coroutine[Any, Any, Principal]]:
    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if not principal.is_superadmin:
            raise Forbidden("Solo superadministradores", code="superadmin_only")
        return principal

    return dependency


def require_scope(scope: str) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """API keys with explicit scopes must include ``scope``; users always pass."""

    async def dependency(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.api_key_id is not None and principal.scopes and scope not in principal.scopes:
            raise Forbidden(f"La API key no tiene el permiso {scope}", code="missing_scope")
        return principal

    return dependency


async def get_db(principal: Principal = Depends(get_org_principal)) -> AsyncIterator[AsyncSession]:
    """RLS-scoped transaction for the active organization."""
    async with rls_session(principal) as session:
        yield session


async def get_user_db(principal: Principal = Depends(get_principal)) -> AsyncIterator[AsyncSession]:
    """RLS-scoped transaction for user-level endpoints that may not have an active organization."""
    async with rls_session(principal) as session:
        yield session


def ensure_project_access(principal: Principal, project_id: uuid.UUID) -> None:
    """Project-scoped API keys can only touch their project."""
    if principal.project_id is not None and principal.project_id != project_id:
        raise Forbidden("La API key está limitada a otro proyecto", code="project_scope")
