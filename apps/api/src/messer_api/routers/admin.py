"""/api/v1/admin — internal backoffice (superadmins only, §8.5).

Organizations (plan, payment status, usage, real model cost, margin, last access), organization detail
with credits adjustments, manual plan changes and blocking, users (block/unblock), impersonation ("log in
as", audited, visible banner via ``me.impersonated_by``) and business metrics. Every mutation is audited.
Catalog management (plans, model prices, templates, feature flags) lives in ``admin_catalog``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from messer_common import audit
from messer_common.billing_state import PAID_STATUSES
from messer_common.credits import add_entry, balance
from messer_common.db import Principal, system_session
from messer_common.db.models import AuthSession, CreditLedger, Invoice, Membership, Org, Plan, Subscription, User
from messer_common.security import TokenError, decode_access_token

from ..deps import ACCESS_COOKIE, ORG_COOKIE, client_ip, get_principal, require_superadmin
from ..errors import ApiError, Conflict, Forbidden, NotFound, Unauthorized
from ..services import admin as admin_service
from ..services import auth as auth_service
from ..services import billing as billing_service
from ..services.billing_providers import ProviderError, SimulatedBilling, period_end_for
from .auth import set_session_cookies
from .billing import InvoiceOut, LedgerEntryOut, SubscriptionOut, UsageOut
from .plans import PlanOut, plan_out

router = APIRouter(prefix="/admin", tags=["admin"])

superadmin = require_superadmin()
IMPERSONATION_TTL = timedelta(hours=2)


# ============================================================================= models


class OrgRowOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    blocked_reason: str | None
    created_at: datetime
    owner_email: str | None
    plan_id: str | None
    plan_name: str | None
    subscription_status: str
    interval: str | None
    trial_ends_at: datetime | None
    test_mode: bool
    mrr_eur: Decimal
    members: int
    projects: int
    runs_month: int
    credits_used_month: Decimal
    credits_balance: Decimal
    model_cost_usd_month: Decimal
    credits_revenue_usd_month: Decimal
    margin_usd_month: Decimal
    last_active_at: datetime | None


class OrgPage(BaseModel):
    items: list[OrgRowOut]
    total: int


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    role: str
    status: str
    is_superadmin: bool
    last_login_at: datetime | None
    joined_at: datetime


class ProjectRowOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    archived_at: datetime | None
    template_id: str | None
    runs_month: int
    cost_usd_month: Decimal


class AuditOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    org_id: uuid.UUID | None
    action: str
    actor_email: str | None
    impersonated_by_email: str | None
    entity_type: str | None
    entity_id: str | None
    diff: dict[str, Any]
    ip: str | None


class OrgDetailOut(BaseModel):
    org: OrgRowOut
    region: str
    data_residency: str
    plan: PlanOut | None
    subscription: SubscriptionOut | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    usage: UsageOut
    members: list[MemberOut]
    projects: list[ProjectRowOut]
    ledger: list[LedgerEntryOut]
    invoices: list[InvoiceOut]
    audit: list[AuditOut]


class CreditAdjustIn(BaseModel):
    amount: Decimal = Field(ge=Decimal("-10000000"), le=Decimal("10000000"), decimal_places=4)
    note: str = Field(min_length=3, max_length=500)


class PlanChangeIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    interval: Literal["month", "year"] = "month"
    status: Literal["active", "trialing"] = "active"
    trial_days: int = Field(default=14, ge=1, le=90)
    note: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class UserRowOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str | None
    status: str
    is_superadmin: bool
    last_login_at: datetime | None
    created_at: datetime
    orgs: list[dict[str, Any]]


class UserPage(BaseModel):
    items: list[UserRowOut]
    total: int


class ImpersonateIn(BaseModel):
    user_id: uuid.UUID
    org_id: uuid.UUID | None = None
    reason: str = Field(min_length=3, max_length=500)


class ImpersonationOut(BaseModel):
    ok: bool
    redirect: str
    user_id: uuid.UUID
    org_id: uuid.UUID | None


class OkOut(BaseModel):
    ok: bool = True


# ============================================================================= metrics


@router.get("/metrics")
async def metrics(
    weeks: int = Query(default=12, ge=4, le=52),
    months: int = Query(default=6, ge=3, le=24),
    _: Principal = Depends(superadmin),
) -> dict[str, Any]:
    """MRR (annual / 12), sign-ups per week, trial→paid conversion, churn, AI cost vs revenue, activation."""
    async with system_session() as s:
        return await admin_service.business_metrics(s, weeks=weeks, months=months)


# ============================================================================= organizations


@router.get("/orgs", response_model=OrgPage)
async def list_orgs(
    q: str | None = Query(default=None, max_length=200),
    status: Literal["active", "blocked"] | None = None,
    payment_status: Literal["none", "trialing", "active", "past_due", "canceled", "incomplete"] | None = None,
    plan_id: str | None = None,
    sort: Literal["created", "name", "cost", "last_active"] = "created",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(superadmin),
) -> OrgPage:
    async with system_session() as s:
        rows, total = await admin_service.list_orgs(
            s,
            q=q,
            status=status,
            payment_status=payment_status,
            plan_id=plan_id,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    return OrgPage(items=[OrgRowOut(**r) for r in rows], total=total)


async def _org_or_404(session: Any, org_id: uuid.UUID) -> Org:
    org = await session.get(Org, org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    return org


@router.get("/orgs/{org_id}", response_model=OrgDetailOut)
async def org_detail(org_id: uuid.UUID, _: Principal = Depends(superadmin)) -> OrgDetailOut:
    async with system_session() as s:
        org = await _org_or_404(s, org_id)
        row = await admin_service.org_row(s, org_id)
        assert row is not None
        sub = await billing_service.get_subscription(s, org_id)
        plan_id = sub.plan_id if sub else org.plan_id
        plan = await s.get(Plan, plan_id) if plan_id else None
        usage = await billing_service.usage_summary(s, org_id, plan)
        members = await admin_service.org_members(s, org_id)
        projects = await admin_service.org_projects(s, org_id)
        ledger_rows = (
            (
                await s.execute(
                    select(CreditLedger, User.email)
                    .outerjoin(User, User.id == CreditLedger.created_by)
                    .where(CreditLedger.org_id == org_id)
                    .order_by(CreditLedger.created_at.desc())
                    .limit(30)
                )
            )
            .tuples()
            .all()
        )
        invoices = (
            (
                await s.execute(
                    select(Invoice).where(Invoice.org_id == org_id).order_by(Invoice.created_at.desc()).limit(20)
                )
            )
            .scalars()
            .all()
        )
        entries = await admin_service.recent_audit(s, org_id=org_id, limit=40)
    sub_view = billing_service.subscription_view(org, sub)
    return OrgDetailOut(
        org=OrgRowOut(**row),
        region=org.region,
        data_residency=org.data_residency,
        plan=plan_out(plan) if plan else None,
        subscription=SubscriptionOut(**sub_view) if sub_view else None,
        stripe_customer_id=sub.stripe_customer_id if sub else None,
        stripe_subscription_id=sub.stripe_subscription_id if sub else None,
        usage=UsageOut(**usage),
        members=[MemberOut(**m) for m in members],
        projects=[ProjectRowOut(**p) for p in projects],
        ledger=[
            LedgerEntryOut(
                id=e.id,
                kind=e.kind,
                amount=e.amount,
                note=e.note,
                run_id=e.run_id,
                project_id=e.project_id,
                project_name=None,
                cost_usd=e.cost_usd,
                created_at=e.created_at,
                created_by_email=email,
            )
            for e, email in ledger_rows
        ],
        invoices=[
            InvoiceOut(
                id=i.id,
                stripe_invoice_id=i.stripe_invoice_id,
                number=i.number,
                status=i.status,
                amount_due_eur=i.amount_due_eur,
                amount_paid_eur=i.amount_paid_eur,
                tax_eur=i.tax_eur,
                hosted_invoice_url=i.hosted_invoice_url,
                pdf_url=i.pdf_url,
                period_start=i.period_start,
                period_end=i.period_end,
                created_at=i.created_at,
                test=i.stripe_invoice_id.startswith("in_sim_"),
            )
            for i in invoices
        ],
        audit=[AuditOut(**a) for a in entries],
    )


@router.post("/orgs/{org_id}/credits", response_model=OrgRowOut)
async def adjust_credits(org_id: uuid.UUID, body: CreditAdjustIn, admin: Principal = Depends(superadmin)) -> OrgRowOut:
    """Grant (positive) or remove (negative) credits with a mandatory note → ``adjustment`` ledger entry."""
    if body.amount == 0:
        raise ApiError("La cantidad no puede ser cero", code="invalid_amount")
    async with system_session() as s:
        await _org_or_404(s, org_id)
        await add_entry(
            s, org_id=org_id, kind="adjustment", amount=body.amount, note=body.note.strip(), created_by=admin.user_id
        )
        new_balance = await balance(s, org_id)
        await audit.record(
            s,
            action="admin.credits_adjusted",
            principal=admin,
            org_id=org_id,
            entity_type="org",
            entity_id=org_id,
            diff={"amount": str(body.amount), "note": body.note.strip(), "balance_after": str(new_balance)},
        )
        await s.flush()
        row = await admin_service.org_row(s, org_id)
    assert row is not None
    return OrgRowOut(**row)


@router.post("/orgs/{org_id}/plan", response_model=OrgRowOut)
async def change_org_plan(org_id: uuid.UUID, body: PlanChangeIn, admin: Principal = Depends(superadmin)) -> OrgRowOut:
    """Manual plan change. A live paid subscription is changed through its provider (so billing follows);
    otherwise the plan is assigned manually (invoiced outside Stripe) or a trial is (re)started."""
    prov = billing_service.provider()
    now = datetime.now(UTC)
    async with system_session() as s:
        org = await _org_or_404(s, org_id)
        plan = await s.get(Plan, body.plan_id)
        if plan is None:
            raise NotFound("Plan no encontrado", code="unknown_plan")
        sub = await billing_service.get_subscription(s, org_id, lock=True)
        before = {
            "plan_id": sub.plan_id if sub else org.plan_id,
            "status": sub.status if sub else "none",
            "interval": sub.interval if sub else None,
        }
        provider_sub = bool(
            sub is not None
            and sub.stripe_subscription_id
            and sub.status in PAID_STATUSES
            and sub.stripe_subscription_id.startswith("sub_sim_") == isinstance(prov, SimulatedBilling)
        )
        if provider_sub and sub is not None:
            if body.status == "trialing":
                raise Conflict(
                    "La organización tiene una suscripción de pago activa. Cancélala antes de iniciar una prueba.",
                    code="paid_subscription_active",
                )
            current = await s.get(Plan, sub.plan_id)
            assert current is not None
            if current.id != plan.id or sub.interval != body.interval:
                try:
                    result = await prov.change_subscription(
                        sub=sub, current_plan=current, plan=plan, interval=body.interval
                    )
                except ProviderError as exc:
                    raise ApiError(exc.message, code=exc.code, status_code=502) from exc
                await billing_service.apply_result(s, result)
        else:
            if sub is None:
                sub = Subscription(org_id=org_id, plan_id=plan.id, status=body.status)
                s.add(sub)
            sub.plan_id = plan.id
            sub.interval = body.interval
            sub.status = body.status
            sub.past_due_since = None
            sub.cancel_at_period_end = False
            sub.canceled_at = None
            sub.test_mode = billing_service.current_test_mode()
            # A manual plan is not billed by a provider subscription any more.
            sub.stripe_subscription_id = None
            sub.current_period_start = now
            if body.status == "trialing":
                sub.trial_ends_at = now + timedelta(days=body.trial_days)
                sub.current_period_end = sub.trial_ends_at
            else:
                sub.current_period_end = period_end_for(now, body.interval)
            org.plan_id = plan.id
            await s.flush()
            if body.status == "active":
                await billing_service.grant_plan_credits(
                    s, org_id=org_id, plan=plan, period_start=now, note=f"Créditos incluidos en {plan.name} (manual)"
                )
        await audit.record(
            s,
            action="admin.plan_changed",
            principal=admin,
            org_id=org_id,
            entity_type="org",
            entity_id=org_id,
            diff={
                "before": before,
                "after": {"plan_id": plan.id, "status": body.status, "interval": body.interval},
                "note": body.note,
                "via_provider": provider_sub,
            },
        )
        await s.flush()
        row = await admin_service.org_row(s, org_id)
    assert row is not None
    return OrgRowOut(**row)


@router.post("/orgs/{org_id}/block", response_model=OrgRowOut)
async def block_org(org_id: uuid.UUID, body: ReasonIn, admin: Principal = Depends(superadmin)) -> OrgRowOut:
    async with system_session() as s:
        org = await _org_or_404(s, org_id)
        org.status = "blocked"
        org.blocked_reason = body.reason.strip()
        await audit.record(
            s,
            action="admin.org_blocked",
            principal=admin,
            org_id=org_id,
            entity_type="org",
            entity_id=org_id,
            diff={"reason": org.blocked_reason},
        )
        await s.flush()
        row = await admin_service.org_row(s, org_id)
    assert row is not None
    return OrgRowOut(**row)


@router.post("/orgs/{org_id}/unblock", response_model=OrgRowOut)
async def unblock_org(org_id: uuid.UUID, admin: Principal = Depends(superadmin)) -> OrgRowOut:
    async with system_session() as s:
        org = await _org_or_404(s, org_id)
        previous = org.blocked_reason
        org.status = "active"
        org.blocked_reason = None
        await audit.record(
            s,
            action="admin.org_unblocked",
            principal=admin,
            org_id=org_id,
            entity_type="org",
            entity_id=org_id,
            diff={"previous_reason": previous},
        )
        await s.flush()
        row = await admin_service.org_row(s, org_id)
    assert row is not None
    return OrgRowOut(**row)


# ============================================================================= users


async def _user_orgs(session: Any, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    out: dict[uuid.UUID, list[dict[str, Any]]] = {uid: [] for uid in user_ids}
    if not user_ids:
        return out
    rows = (
        await session.execute(
            select(Membership.user_id, Org.id, Org.name, Membership.role)
            .join(Org, Org.id == Membership.org_id)
            .where(Membership.user_id.in_(user_ids))
            .order_by(Membership.created_at)
        )
    ).all()
    for user_id, org_id, name, role in rows:
        out[user_id].append({"id": str(org_id), "name": name, "role": role})
    return out


def _user_out(user: User, orgs: list[dict[str, Any]]) -> UserRowOut:
    return UserRowOut(
        id=user.id,
        email=user.email,
        name=user.name,
        status=user.status,
        is_superadmin=user.is_superadmin,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        orgs=orgs,
    )


@router.get("/users", response_model=UserPage)
async def list_users(
    q: str | None = Query(default=None, max_length=200),
    status: Literal["active", "blocked"] | None = None,
    org_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: Principal = Depends(superadmin),
) -> UserPage:
    filters: list[Any] = [User.deleted_at.is_(None)]
    if q:
        like = f"%{q.strip()}%"
        filters.append(or_(User.email.ilike(like), User.name.ilike(like)))
    if status:
        filters.append(User.status == status)
    if org_id:
        filters.append(User.id.in_(select(Membership.user_id).where(Membership.org_id == org_id)))
    async with system_session() as s:
        total = (await s.execute(select(func.count()).select_from(User).where(*filters))).scalar_one()
        users = (
            (await s.execute(select(User).where(*filters).order_by(User.created_at.desc()).limit(limit).offset(offset)))
            .scalars()
            .all()
        )
        orgs = await _user_orgs(s, [u.id for u in users])
    return UserPage(items=[_user_out(u, orgs[u.id]) for u in users], total=int(total))


async def _target_user(session: Any, user_id: uuid.UUID, admin: Principal) -> User:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFound("Usuario no encontrado")
    if user.id == admin.user_id:
        raise Conflict("No puedes aplicar esta acción a tu propia cuenta.", code="self_action")
    if user.is_superadmin:
        raise Forbidden("No se puede aplicar a otro superadministrador.", code="superadmin_target")
    return user


@router.post("/users/{user_id}/block", response_model=UserRowOut)
async def block_user(user_id: uuid.UUID, body: ReasonIn, admin: Principal = Depends(superadmin)) -> UserRowOut:
    """Block a user: every session is revoked and the API refuses their tokens."""
    async with system_session() as s:
        user = await _target_user(s, user_id, admin)
        user.status = "blocked"
        await s.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await audit.record(
            s,
            action="admin.user_blocked",
            principal=admin,
            org_id=None,
            entity_type="user",
            entity_id=user.id,
            diff={"email": user.email, "reason": body.reason.strip()},
        )
        orgs = await _user_orgs(s, [user.id])
    return _user_out(user, orgs[user.id])


@router.post("/users/{user_id}/unblock", response_model=UserRowOut)
async def unblock_user(user_id: uuid.UUID, admin: Principal = Depends(superadmin)) -> UserRowOut:
    async with system_session() as s:
        user = await _target_user(s, user_id, admin)
        user.status = "active"
        await audit.record(
            s,
            action="admin.user_unblocked",
            principal=admin,
            org_id=None,
            entity_type="user",
            entity_id=user.id,
            diff={"email": user.email},
        )
        orgs = await _user_orgs(s, [user.id])
    return _user_out(user, orgs[user.id])


# ============================================================================= impersonation


def _session_id_from(request: Request) -> uuid.UUID | None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else request.cookies.get(ACCESS_COOKIE)
    if not token:
        return None
    try:
        sid = decode_access_token(token).get("sid")
        return uuid.UUID(str(sid)) if sid else None
    except (TokenError, ValueError):
        return None


@router.post("/impersonation/start", response_model=ImpersonationOut)
async def start_impersonation(
    body: ImpersonateIn, request: Request, response: Response, admin: Principal = Depends(superadmin)
) -> ImpersonationOut:
    """Log in as a user for support. The session carries the ``imp`` claim (banner, audit attribution)."""
    if admin.api_key_id is not None or admin.user_id is None:
        raise Forbidden("La suplantación requiere una sesión de superadministrador", code="session_required")
    async with system_session() as s:
        target = await _target_user(s, body.user_id, admin)
        if target.status == "blocked":
            raise Conflict("El usuario está bloqueado.", code="user_blocked")
        memberships = (
            (await s.execute(select(Membership).where(Membership.user_id == target.id).order_by(Membership.created_at)))
            .scalars()
            .all()
        )
        org_id = body.org_id
        if org_id is not None and all(m.org_id != org_id for m in memberships):
            raise ApiError("El usuario no pertenece a esa organización", code="not_a_member")
        if org_id is None and memberships:
            org_id = memberships[0].org_id
        previous_login = target.last_login_at
        tokens = await auth_service.open_session(
            s,
            target,
            user_agent=request.headers.get("user-agent"),
            ip=client_ip(request),
            mfa_verified=admin.mfa_verified,
            impersonated_by=admin.user_id,
        )
        target.last_login_at = previous_login  # support sessions are not the user's activity
        claims = decode_access_token(tokens.access_token)
        auth_row = await s.get(AuthSession, uuid.UUID(str(claims["sid"])))
        if auth_row is not None:
            auth_row.expires_at = datetime.now(UTC) + IMPERSONATION_TTL
        await audit.record(
            s,
            action="admin.impersonation_started",
            principal=Principal(user_id=admin.user_id, org_id=org_id),
            org_id=org_id,
            entity_type="user",
            entity_id=target.id,
            diff={"email": target.email, "reason": body.reason.strip(), "admin_email": admin.email},
            ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    set_session_cookies(response, tokens, org_id)
    return ImpersonationOut(ok=True, redirect="/app", user_id=target.id, org_id=org_id)


@router.post("/impersonation/stop", response_model=ImpersonationOut)
async def stop_impersonation(
    request: Request, response: Response, principal: Principal = Depends(get_principal)
) -> ImpersonationOut:
    """End the support session and restore the superadmin's own session."""
    if principal.impersonated_by is None:
        raise Conflict("No hay ninguna suplantación activa.", code="not_impersonating")
    sid = _session_id_from(request)
    async with system_session() as s:
        if sid is not None:
            await s.execute(
                update(AuthSession)
                .where(AuthSession.id == sid, AuthSession.revoked_at.is_(None))
                .values(revoked_at=datetime.now(UTC))
            )
        admin_user = await s.get(User, principal.impersonated_by)
        if (
            admin_user is None
            or not admin_user.is_superadmin
            or admin_user.status == "blocked"
            or admin_user.deleted_at is not None
        ):
            response.delete_cookie(ACCESS_COOKIE, path="/")
            raise Unauthorized(
                "La sesión de administrador ya no es válida. Inicia sesión.", code="admin_session_invalid"
            )
        await audit.record(
            s,
            action="admin.impersonation_stopped",
            principal=Principal(user_id=admin_user.id, org_id=principal.org_id),
            org_id=principal.org_id,
            entity_type="user",
            entity_id=principal.user_id,
            diff={"admin_email": admin_user.email},
            ip=client_ip(request),
        )
        tokens = await auth_service.open_session(
            s,
            admin_user,
            user_agent=request.headers.get("user-agent"),
            ip=client_ip(request),
            mfa_verified=principal.mfa_verified,
        )
        own_org = (
            await s.execute(
                select(Membership.org_id).where(Membership.user_id == admin_user.id).order_by(Membership.created_at)
            )
        ).first()
    org_id = own_org[0] if own_org else None
    set_session_cookies(response, tokens, org_id)
    if org_id is None:
        response.delete_cookie(ORG_COOKIE, path="/")
    return ImpersonationOut(ok=True, redirect="/admin", user_id=admin_user.id, org_id=org_id)


# ============================================================================= audit


@router.get("/audit", response_model=list[AuditOut])
async def admin_audit(
    org_id: uuid.UUID | None = None,
    action: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(superadmin),
) -> list[AuditOut]:
    """Audit trail across organizations (defaults to backoffice actions)."""
    async with system_session() as s:
        rows = await admin_service.recent_audit(
            s, org_id=org_id, action_prefix=action if action is not None else "admin.", limit=limit
        )
    return [AuditOut(**r) for r in rows]
