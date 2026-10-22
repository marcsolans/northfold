"""Organization lifecycle: creation (with trial), membership and invitations."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from slugify import slugify
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import CreditLedger, Invitation, Membership, Org, Plan, Subscription, User
from messer_common.plans import TRIAL_DAYS, TRIAL_PLAN
from messer_common.security import hash_token, random_token

from ..errors import ApiError, Conflict, NotFound

INVITATION_TTL = timedelta(days=7)
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
# Organization slugs are the first segment of public URLs (/{org}/{project}/…), so they must never shadow a
# top-level route of the web app or a well-known path.
RESERVED_SLUGS = frozenset(
    {
        "admin",
        "api",
        "app",
        "auth",
        "approvals",
        "blog",
        "contact",
        "docs",
        "embed",
        "forgot-password",
        "health",
        "invite",
        "legal",
        "login",
        "logout",
        "mfa",
        "monaco",
        "onboarding",
        "pricing",
        "reset-password",
        "robots.txt",
        "security",
        "signup",
        "sitemap.xml",
        "sso",
        "static",
        "status",
        "templates",
        "verify-email",
        "widget",
        "www",
        "_next",
        "messer",
        "support",
        "help",
    }
)


async def unique_org_slug(session: AsyncSession, name: str) -> str:
    base = slugify(name, max_length=60) or "org"
    slug = base if base not in RESERVED_SLUGS else f"{base}-org"
    n = 2
    while (await session.execute(select(Org.id).where(Org.slug == slug))).first() is not None:
        slug = f"{base}-{n}"
        n += 1
    return slug


async def create_org(
    session: AsyncSession,
    *,
    owner: User,
    name: str,
    slug: str | None = None,
    start_trial: bool = True,
    data_residency: str = "standard",
) -> Org:
    """Create an organization owned by ``owner`` (system session). Starts the Pro trial by default."""
    name = name.strip()
    if not name:
        raise ApiError("El nombre de la organización es obligatorio", code="invalid_name")
    if slug:
        slug = slug.strip().lower()
        if not _SLUG_RE.match(slug):
            raise ApiError("El identificador solo admite minúsculas, números y guiones", code="invalid_slug")
        if slug in RESERVED_SLUGS:
            raise ApiError("Ese identificador está reservado; elige otro", code="slug_reserved")
        if (await session.execute(select(Org.id).where(Org.slug == slug))).first() is not None:
            raise Conflict("Ese identificador ya está en uso", code="slug_taken")
    else:
        slug = await unique_org_slug(session, name)

    org = Org(name=name, slug=slug, created_by=owner.id, data_residency=data_residency, plan_id=None)
    session.add(org)
    await session.flush()
    session.add(Membership(org_id=org.id, user_id=owner.id, role="owner"))
    if start_trial:
        await start_trial_subscription(session, org)
    await audit.record(
        session,
        action="org.created",
        principal=Principal(user_id=owner.id, org_id=org.id),
        entity_type="org",
        entity_id=org.id,
        diff={"name": name, "slug": slug},
    )
    return org


async def start_trial_subscription(session: AsyncSession, org: Org) -> Subscription:
    plan = await session.get(Plan, TRIAL_PLAN)
    if plan is None:
        raise ApiError("Los planes no están cargados. Ejecuta `make bootstrap`.", code="plans_missing", status_code=500)
    now = datetime.now(UTC)
    sub = Subscription(
        org_id=org.id,
        plan_id=plan.id,
        status="trialing",
        trial_ends_at=now + timedelta(days=TRIAL_DAYS),
        current_period_start=now,
        current_period_end=now + timedelta(days=TRIAL_DAYS),
        test_mode=True,
    )
    session.add(sub)
    org.plan_id = plan.id
    credits = Decimal(str(plan.limits.get("credits_month", 0)))
    if credits > 0:
        session.add(
            CreditLedger(
                org_id=org.id,
                kind="grant",
                amount=credits,
                note=f"Créditos incluidos en la prueba de {plan.name}",
                idempotency_key=f"trial-grant:{org.id}",
            )
        )
    return sub


async def member_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))
        ).scalar_one()
    )


async def pending_invitation_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    now = datetime.now(UTC)
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Invitation)
                .where(
                    Invitation.org_id == org_id,
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                    Invitation.expires_at > now,
                )
            )
        ).scalar_one()
    )


async def create_invitation(
    session: AsyncSession, *, principal: Principal, email: str, role: str
) -> tuple[Invitation, str]:
    """Create an invitation and return it with the clear-text token (sent by email, never stored)."""
    assert principal.org_id is not None
    email = email.strip().lower()
    existing_member = (
        await session.execute(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == principal.org_id, func.lower(User.email) == email)
        )
    ).first()
    if existing_member is not None:
        raise Conflict("Esa persona ya es miembro de la organización", code="already_member")
    token = random_token(24)
    invitation = Invitation(
        org_id=principal.org_id,
        email=email,
        role=role,
        token_hash=hash_token(token),
        invited_by=principal.user_id,
        expires_at=datetime.now(UTC) + INVITATION_TTL,
    )
    session.add(invitation)
    await session.flush()
    await audit.record(
        session,
        action="invitation.created",
        principal=principal,
        entity_type="invitation",
        entity_id=invitation.id,
        diff={"email": email, "role": role},
    )
    return invitation, token


async def accept_invitation(session: AsyncSession, *, token: str, user: User) -> Membership:
    """System session: validate the token and add the membership."""
    invitation = (
        await session.execute(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if invitation is None or invitation.revoked_at is not None:
        raise NotFound("Invitación no válida", code="invalid_invitation")
    if invitation.accepted_at is not None:
        raise Conflict("Esta invitación ya se ha usado", code="invitation_used")
    if invitation.expires_at < now:
        raise ApiError("La invitación ha caducado", code="invitation_expired", status_code=410)
    if invitation.email.lower() != user.email.lower():
        raise ApiError(
            "Esta invitación es para otra dirección de email", code="invitation_email_mismatch", status_code=403
        )
    existing = (
        await session.execute(
            select(Membership).where(Membership.org_id == invitation.org_id, Membership.user_id == user.id)
        )
    ).scalar_one_or_none()
    invitation.accepted_at = now
    if existing is not None:
        return existing
    membership = Membership(org_id=invitation.org_id, user_id=user.id, role=invitation.role)
    session.add(membership)
    await audit.record(
        session,
        action="invitation.accepted",
        principal=Principal(user_id=user.id, org_id=invitation.org_id),
        entity_type="invitation",
        entity_id=invitation.id,
        diff={"role": invitation.role},
    )
    return membership
