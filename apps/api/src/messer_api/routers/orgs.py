"""/api/v1/me, /orgs, /members, /invitations, /roles."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import AuthCredential, Invitation, Membership, Org, Plan, User
from messer_common.email import send_template
from messer_common.plans import limit_value
from messer_common.settings import get_settings

from ..deps import ORG_COOKIE, get_db, get_principal, get_user_db, org_billing_state, require_role
from ..errors import ApiError, Conflict, Forbidden, NotFound, PlanLimitExceeded
from ..services.orgs import create_invitation, create_org, member_count, pending_invitation_count

router = APIRouter(tags=["orgs"])

Role = Literal["owner", "admin", "builder", "viewer"]
ROLE_DESCRIPTIONS = {
    "owner": "Todo, incluida la facturación.",
    "admin": "Usuarios, presupuestos, políticas y SSO.",
    "builder": "Crea y edita proyectos, agentes, flujos y conocimiento.",
    "viewer": "Solo lectura y uso de interfaces.",
}


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str | None = None
    data_residency: str
    region: str
    plan_id: str | None = None


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    avatar: str | None
    locale: str
    is_superadmin: bool
    impersonated_by: uuid.UUID | None
    mfa_enabled: bool
    email_verified: bool
    active_org: OrgOut | None
    orgs: list[OrgOut]
    billing: dict[str, Any] | None


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80)


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    trace_retention_days: int | None = Field(default=None, ge=1, le=3650)
    conversation_retention_days: int | None = Field(default=None, ge=1, le=3650)
    data_residency: Literal["standard", "eu_strict"] | None = None
    region: str | None = None


class MeUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    locale: Literal["es", "en"] | None = None
    avatar: str | None = None


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    role: str
    source: str
    joined_at: datetime


class RoleIn(BaseModel):
    role: Role


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = "viewer"


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


def _org_out(org: Org, role: str | None) -> OrgOut:
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        role=role,
        data_residency=org.data_residency,
        region=org.region,
        plan_id=org.plan_id,
    )


@router.get("/me", response_model=MeOut)
async def me(principal: Principal = Depends(get_principal)) -> MeOut:
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
        if user is None:
            raise NotFound("Usuario no encontrado")
        cred = await s.get(AuthCredential, user.id)
        rows = (
            await s.execute(
                select(Org, Membership.role)
                .join(Membership, Membership.org_id == Org.id)
                .where(Membership.user_id == user.id)
                .order_by(Membership.created_at)
            )
        ).all()
        orgs = [_org_out(org, role) for org, role in rows]
        active = next((o for o in orgs if o.id == principal.org_id), None)
        if active is None and principal.org_id and principal.is_superadmin:
            org = await s.get(Org, principal.org_id)
            active = _org_out(org, "owner") if org else None
    billing = None
    if active is not None:
        state = await org_billing_state(active.id)
        billing = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in state.items()}
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar=user.avatar,
        locale=user.locale,
        is_superadmin=user.is_superadmin,
        impersonated_by=principal.impersonated_by,
        mfa_enabled=bool(cred and cred.mfa_enabled),
        email_verified=bool(cred and cred.email_verified_at),
        active_org=active,
        orgs=orgs,
        billing=billing,
    )


@router.patch("/me", response_model=dict)
async def update_me(
    body: MeUpdateIn, principal: Principal = Depends(get_principal), db: AsyncSession = Depends(get_user_db)
) -> dict[str, bool]:
    user = await db.get(User, principal.user_id)
    if user is None:
        raise NotFound("Usuario no encontrado")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    return {"ok": True}


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(principal: Principal = Depends(get_principal)) -> list[OrgOut]:
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Org, Membership.role)
                .join(Membership, Membership.org_id == Org.id)
                .where(Membership.user_id == principal.user_id)
                .order_by(Org.name)
            )
        ).all()
    return [_org_out(org, role) for org, role in rows]


@router.post("/orgs", response_model=OrgOut, status_code=201)
async def create_organization(
    body: OrgCreateIn, response: Response, principal: Principal = Depends(get_principal)
) -> OrgOut:
    if principal.api_key_id is not None:
        raise Forbidden("Las API keys no pueden crear organizaciones")
    async with system_session() as s:
        user = await s.get(User, principal.user_id)
        assert user is not None
        org = await create_org(s, owner=user, name=body.name, slug=body.slug)
        out = _org_out(org, "owner")
    response.set_cookie(
        ORG_COOKIE,
        str(out.id),
        httponly=False,
        samesite="lax",
        path="/",
        secure=get_settings().messer_web_url.startswith("https://"),
    )
    return out


@router.post("/orgs/{org_id}/switch", response_model=OrgOut)
async def switch_org(org_id: uuid.UUID, response: Response, principal: Principal = Depends(get_principal)) -> OrgOut:
    async with system_session() as s:
        org = await s.get(Org, org_id)
        role = (
            await s.execute(
                select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == principal.user_id)
            )
        ).scalar_one_or_none()
    if org is None or (role is None and not principal.is_superadmin):
        raise NotFound("Organización no encontrada")
    response.set_cookie(
        ORG_COOKIE,
        str(org_id),
        httponly=False,
        samesite="lax",
        path="/",
        secure=get_settings().messer_web_url.startswith("https://"),
    )
    return _org_out(org, role or "owner")


@router.get("/orgs/current", response_model=OrgOut)
async def current_org(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> OrgOut:
    org = await db.get(Org, principal.org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    return _org_out(org, principal.role)


@router.patch("/orgs/current", response_model=OrgOut)
async def update_org(
    body: OrgUpdateIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> OrgOut:
    org = await db.get(Org, principal.org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("data_residency") == "eu_strict":
        plan = await db.get(Plan, org.plan_id) if org.plan_id else None
        if plan is None or "eu_strict" not in (plan.limits.get("features") or []):
            raise PlanLimitExceeded(
                "La residencia UE estricta requiere el plan Enterprise",
                details={"feature": "eu_strict", "upgrade_to": "enterprise"},
            )
    if "region" in changes and changes["region"] and not str(changes["region"]).startswith("eu-"):
        raise ApiError("Solo se admiten regiones de la UE", code="non_eu_region")
    before = {k: getattr(org, k) for k in changes}
    for field, value in changes.items():
        setattr(org, field, value)
    await audit.record(
        db,
        action="org.updated",
        principal=principal,
        entity_type="org",
        entity_id=org.id,
        diff={"before": before, "after": changes},
    )
    return _org_out(org, principal.role)


# ----------------------------------------------------------------------------- members


@router.get("/roles")
async def roles() -> list[dict[str, str]]:
    return [{"role": r, "description": d} for r, d in ROLE_DESCRIPTIONS.items()]


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> list[MemberOut]:
    rows = (
        await db.execute(
            select(Membership, User)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == principal.org_id)
            .order_by(Membership.created_at)
        )
    ).all()
    return [
        MemberOut(user_id=u.id, email=u.email, name=u.name, role=m.role, source=m.source, joined_at=m.created_at)
        for m, u in rows
    ]


async def _owner_count(db: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == "owner")
            )
        ).scalar_one()
    )


@router.patch("/members/{user_id}", response_model=MemberOut)
async def update_member(
    user_id: uuid.UUID,
    body: RoleIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    membership = (
        await db.execute(select(Membership).where(Membership.org_id == principal.org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        raise NotFound("Miembro no encontrado")
    if (
        (body.role == "owner" or membership.role == "owner")
        and principal.role != "owner"
        and not principal.is_superadmin
    ):
        raise Forbidden("Solo un owner puede cambiar el rol owner")
    if membership.role == "owner" and body.role != "owner" and await _owner_count(db, principal.org_id) <= 1:  # type: ignore[arg-type]
        raise Conflict("La organización debe tener al menos un owner", code="last_owner")
    before = membership.role
    membership.role = body.role
    await audit.record(
        db,
        action="member.role_changed",
        principal=principal,
        entity_type="user",
        entity_id=user_id,
        diff={"before": before, "after": body.role},
    )
    user = await db.get(User, user_id)
    assert user is not None
    return MemberOut(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
        source=membership.source,
        joined_at=membership.created_at,
    )


@router.delete("/members/{user_id}", status_code=204)
async def remove_member(
    user_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    membership = (
        await db.execute(select(Membership).where(Membership.org_id == principal.org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        raise NotFound("Miembro no encontrado")
    if membership.role == "owner":
        if principal.role != "owner" and not principal.is_superadmin:
            raise Forbidden("Solo un owner puede retirar a otro owner")
        if await _owner_count(db, principal.org_id) <= 1:  # type: ignore[arg-type]
            raise Conflict("La organización debe tener al menos un owner", code="last_owner")
    await db.delete(membership)
    await audit.record(
        db,
        action="member.removed",
        principal=principal,
        entity_type="user",
        entity_id=user_id,
        diff={"role": membership.role},
    )
    return Response(status_code=204)


# ----------------------------------------------------------------------------- invitations


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> list[InvitationOut]:
    rows = (
        await db.execute(
            select(Invitation).where(Invitation.org_id == principal.org_id).order_by(Invitation.created_at.desc())
        )
    ).scalars()
    return [InvitationOut.model_validate(r, from_attributes=True) for r in rows]


@router.post("/invitations", response_model=InvitationOut, status_code=201)
async def invite(
    body: InviteIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> InvitationOut:
    if body.role == "owner" and principal.role != "owner" and not principal.is_superadmin:
        raise Forbidden("Solo un owner puede invitar a otro owner")
    org = await db.get(Org, principal.org_id)
    assert org is not None
    plan = await db.get(Plan, org.plan_id) if org.plan_id else None
    if plan is not None:
        seats = limit_value(plan.limits, "seats")
        used = await member_count(db, org.id) + await pending_invitation_count(db, org.id)
        if seats != -1 and used >= seats:
            raise PlanLimitExceeded(
                f"Tu plan {plan.name} incluye {seats} usuarios. Mejora el plan para invitar a más.",
                details={"limit": "seats", "value": seats, "used": used},
            )
    invitation, token = await create_invitation(db, principal=principal, email=body.email, role=body.role)
    inviter = await db.get(User, principal.user_id) if principal.user_id else None
    url = f"{get_settings().messer_web_url}/invite/{token}"
    await send_template(
        body.email,
        "invitation",
        {
            "inviter": (inviter.name or inviter.email) if inviter else "Messer",
            "org": org.name,
            "role": body.role,
            "url": url,
        },
        inviter.locale if inviter else "es",
    )
    return InvitationOut.model_validate(invitation, from_attributes=True)


@router.delete("/invitations/{invitation_id}", status_code=204)
async def revoke_invitation(
    invitation_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    invitation = await db.get(Invitation, invitation_id)
    if invitation is None or invitation.org_id != principal.org_id:
        raise NotFound("Invitación no encontrada")
    invitation.revoked_at = datetime.now(UTC)
    await audit.record(
        db, action="invitation.revoked", principal=principal, entity_type="invitation", entity_id=invitation_id
    )
    return Response(status_code=204)


@router.get("/invitations/lookup/{token}")
async def lookup_invitation(token: str) -> dict[str, Any]:
    """Public: show which organization an invitation link belongs to (for the accept screen)."""
    from messer_common.security import hash_token

    async with system_session() as s:
        inv = (
            await s.execute(select(Invitation).where(Invitation.token_hash == hash_token(token)))
        ).scalar_one_or_none()
        if inv is None or inv.revoked_at is not None:
            raise NotFound("Invitación no válida", code="invalid_invitation")
        org = await s.get(Org, inv.org_id)
    return {
        "org_name": org.name if org else "",
        "email": inv.email,
        "role": inv.role,
        "expired": inv.expires_at < datetime.now(UTC),
        "accepted": inv.accepted_at is not None,
    }
