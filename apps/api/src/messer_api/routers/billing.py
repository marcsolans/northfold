"""/api/v1/billing — plan, usage vs limits, subscription, Stripe portal, invoices, credits and test-mode checkout.

Reads are open to every member; mutations require the owner role. Billing endpoints stay available when
the organization is read-only (canceled, trial expired, past due beyond the grace period) so it can pay.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_serializer
from sqlalchemy import func, select

from messer_common.db import Principal, system_session
from messer_common.db.models import CreditLedger, Invoice, Project, User

from ..deps import require_role
from ..services import billing as billing_service
from .plans import CreditPackOut, PlanOut, money, plan_out

router = APIRouter(prefix="/billing", tags=["billing"])

viewer = require_role("viewer", allow_read_only=True)
owner = require_role("owner", allow_read_only=True)


class LimitUsage(BaseModel):
    used: int
    limit: int


class CreditsUsage(BaseModel):
    used: Decimal
    limit: int
    balance: Decimal


class StorageUsage(BaseModel):
    used: float
    used_bytes: int
    limit: int


class UsageOut(BaseModel):
    period_start: datetime
    period_end: datetime
    seats: LimitUsage
    projects: LimitUsage
    runs_month: LimitUsage
    credits: CreditsUsage
    storage_gb: StorageUsage


class SubscriptionOut(BaseModel):
    status: str
    state: str
    plan_id: str
    interval: str
    trial_ends_at: datetime | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    canceled_at: datetime | None
    past_due_since: datetime | None
    grace_ends_at: datetime | None
    read_only: bool
    paid: bool
    has_customer: bool
    test_mode: bool


class BillingOverviewOut(BaseModel):
    mode: Literal["stripe", "simulated"]
    test_mode: bool
    publishable_key: str | None
    plan: PlanOut | None
    subscription: SubscriptionOut | None
    usage: UsageOut
    can_manage: bool


class ChangePlanIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    interval: Literal["month", "year"] = "month"


class CheckoutActionOut(BaseModel):
    action: Literal["checkout", "updated"]
    url: str | None = None
    checkout_id: str | None = None


class UrlOut(BaseModel):
    url: str


class InvoiceOut(BaseModel):
    id: uuid.UUID
    stripe_invoice_id: str
    number: str | None
    status: str
    amount_due_eur: Decimal
    amount_paid_eur: Decimal
    tax_eur: Decimal
    hosted_invoice_url: str | None
    pdf_url: str | None
    period_start: datetime | None
    period_end: datetime | None
    created_at: datetime
    test: bool

    @field_serializer("amount_due_eur", "amount_paid_eur", "tax_eur")
    def _money(self, value: Decimal) -> str:
        return money(value)


class AutoTopupOut(BaseModel):
    enabled: bool
    threshold: int
    pack_id: str | None
    last_status: str | None
    last_error: str | None
    last_requested_at: str | None


class CreditsOut(BaseModel):
    balance: Decimal
    credits_month: int
    used_this_month: Decimal
    added_this_month: Decimal
    period_start: datetime
    period_end: datetime
    credit_usd: Decimal
    mode: Literal["stripe", "simulated"]
    test_mode: bool
    can_auto_topup: bool
    auto_topup: AutoTopupOut
    packs: list[CreditPackOut]


class LedgerEntryOut(BaseModel):
    id: uuid.UUID
    kind: str
    amount: Decimal
    note: str | None
    run_id: uuid.UUID | None
    project_id: uuid.UUID | None
    project_name: str | None
    cost_usd: Decimal | None
    created_at: datetime
    created_by_email: str | None


class LedgerPage(BaseModel):
    items: list[LedgerEntryOut]
    total: int


class PackPurchaseIn(BaseModel):
    pack_id: str = Field(min_length=1, max_length=40)


class AutoTopupIn(BaseModel):
    enabled: bool
    threshold: int = Field(ge=0, le=10_000_000)
    pack_id: str | None = Field(default=None, max_length=40)


class SimulatedCheckoutOut(BaseModel):
    id: uuid.UUID
    kind: Literal["subscription", "credit_pack"]
    status: str
    amount_eur: Decimal
    plan: PlanOut | None
    interval: str | None
    pack: CreditPackOut | None
    org_name: str
    expires_at: datetime
    created_at: datetime
    current_plan_id: str | None
    mode: Literal["stripe", "simulated"]

    @field_serializer("amount_eur")
    def _money(self, value: Decimal) -> str:
        return money(value)


class CheckoutResultOut(BaseModel):
    status: str
    kind: str
    redirect: str


@router.get("", response_model=BillingOverviewOut)
async def get_billing(principal: Principal = Depends(viewer)) -> BillingOverviewOut:
    assert principal.org_id is not None
    async with system_session() as s:
        data = await billing_service.overview(s, principal.org_id)
    plan = data["plan"]
    sub = data["subscription"]
    return BillingOverviewOut(
        mode=data["mode"],
        test_mode=data["test_mode"],
        publishable_key=data["publishable_key"],
        plan=plan_out(plan) if plan is not None else None,
        subscription=SubscriptionOut(**sub) if sub is not None else None,
        usage=UsageOut(**data["usage"]),
        can_manage=principal.role == "owner" or principal.is_superadmin,
    )


@router.post("/subscription", response_model=CheckoutActionOut)
async def change_subscription(body: ChangePlanIn, principal: Principal = Depends(owner)) -> CheckoutActionOut:
    """Subscribe (Stripe Checkout or the test-mode checkout) or change the plan of a paid subscription."""
    result = await billing_service.change_plan(principal, plan_id=body.plan_id, interval=body.interval)
    return CheckoutActionOut(**result)


@router.post("/subscription/cancel", response_model=BillingOverviewOut)
async def cancel_subscription(principal: Principal = Depends(owner)) -> BillingOverviewOut:
    """Cancel at the end of the current period (the organization becomes read-only afterwards)."""
    await billing_service.set_cancel(principal, cancel=True)
    return await get_billing(principal)


@router.post("/subscription/resume", response_model=BillingOverviewOut)
async def resume_subscription(principal: Principal = Depends(owner)) -> BillingOverviewOut:
    await billing_service.set_cancel(principal, cancel=False)
    return await get_billing(principal)


@router.post("/portal", response_model=UrlOut)
async def billing_portal(principal: Principal = Depends(owner)) -> UrlOut:
    """Stripe customer portal: payment method, plan, invoices and tax data."""
    return UrlOut(url=await billing_service.portal_url(principal))


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    limit: int = Query(default=50, ge=1, le=200), principal: Principal = Depends(owner)
) -> list[InvoiceOut]:
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(Invoice)
                    .where(Invoice.org_id == principal.org_id)
                    .order_by(Invoice.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return [
        InvoiceOut(
            id=r.id,
            stripe_invoice_id=r.stripe_invoice_id,
            number=r.number,
            status=r.status,
            amount_due_eur=r.amount_due_eur,
            amount_paid_eur=r.amount_paid_eur,
            tax_eur=r.tax_eur,
            hosted_invoice_url=r.hosted_invoice_url,
            pdf_url=r.pdf_url,
            period_start=r.period_start,
            period_end=r.period_end,
            created_at=r.created_at,
            test=r.stripe_invoice_id.startswith("in_sim_"),
        )
        for r in rows
    ]


@router.get("/credits", response_model=CreditsOut)
async def get_credits(principal: Principal = Depends(viewer)) -> CreditsOut:
    assert principal.org_id is not None
    async with system_session() as s:
        data = await billing_service.credits_overview(s, principal.org_id)
    packs = [
        CreditPackOut(id=str(p["id"]), credits=int(p["credits"]), price_eur=Decimal(p["price_eur"]))
        for p in data["packs"]
    ]
    return CreditsOut(**{**data, "auto_topup": AutoTopupOut(**data["auto_topup"]), "packs": packs})


@router.get("/credits/ledger", response_model=LedgerPage)
async def credit_ledger(
    kind: Literal["grant", "usage", "purchase", "adjustment"] | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(viewer),
) -> LedgerPage:
    filters: list[Any] = [CreditLedger.org_id == principal.org_id]
    if kind:
        filters.append(CreditLedger.kind == kind)
    async with system_session() as s:
        total = (await s.execute(select(func.count()).select_from(CreditLedger).where(*filters))).scalar_one()
        rows = (
            await s.execute(
                select(CreditLedger, Project.name, User.email)
                .outerjoin(Project, Project.id == CreditLedger.project_id)
                .outerjoin(User, User.id == CreditLedger.created_by)
                .where(*filters)
                .order_by(CreditLedger.created_at.desc(), CreditLedger.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    return LedgerPage(
        total=int(total),
        items=[
            LedgerEntryOut(
                id=e.id,
                kind=e.kind,
                amount=e.amount,
                note=e.note,
                run_id=e.run_id,
                project_id=e.project_id,
                project_name=project_name,
                cost_usd=e.cost_usd,
                created_at=e.created_at,
                created_by_email=email,
            )
            for e, project_name, email in rows
        ],
    )


@router.post("/credits/purchase", response_model=CheckoutActionOut)
async def purchase_credits(body: PackPurchaseIn, principal: Principal = Depends(owner)) -> CheckoutActionOut:
    return CheckoutActionOut(**await billing_service.buy_pack(principal, pack_id=body.pack_id))


@router.put("/credits/auto-topup", response_model=CreditsOut)
async def update_auto_topup(body: AutoTopupIn, principal: Principal = Depends(owner)) -> CreditsOut:
    """Buy ``pack_id`` automatically whenever the balance drops below ``threshold`` credits."""
    await billing_service.set_auto_topup(
        principal, enabled=body.enabled, threshold=body.threshold, pack_id=body.pack_id
    )
    return await get_credits(principal)


@router.get("/checkout/{checkout_id}", response_model=SimulatedCheckoutOut)
async def get_checkout(checkout_id: uuid.UUID, principal: Principal = Depends(owner)) -> SimulatedCheckoutOut:
    """Test-mode checkout page data (no charge is made)."""
    data = await billing_service.get_simulated_checkout(principal, checkout_id)
    plan = data["plan"]
    pack = data["pack"]
    return SimulatedCheckoutOut(
        **{
            **data,
            "plan": plan_out(plan) if plan is not None else None,
            "pack": CreditPackOut(
                id=str(pack["id"]), credits=int(pack["credits"]), price_eur=Decimal(pack["price_eur"])
            )
            if pack
            else None,
        }
    )


@router.post("/checkout/{checkout_id}/confirm", response_model=CheckoutResultOut)
async def confirm_checkout(checkout_id: uuid.UUID, principal: Principal = Depends(owner)) -> CheckoutResultOut:
    """Confirm a test-mode checkout: fires the same handlers as the Stripe webhooks."""
    return CheckoutResultOut(**await billing_service.confirm_simulated_checkout(principal, checkout_id))


@router.post("/checkout/{checkout_id}/cancel", response_model=CheckoutResultOut)
async def cancel_checkout(checkout_id: uuid.UUID, principal: Principal = Depends(owner)) -> CheckoutResultOut:
    return CheckoutResultOut(**await billing_service.cancel_simulated_checkout(principal, checkout_id))


@router.post("/simulate/{outcome}", response_model=BillingOverviewOut)
async def simulate_payment(
    outcome: Literal["payment_failed", "payment_succeeded"], principal: Principal = Depends(owner)
) -> BillingOverviewOut:
    """Test mode only: simulate a failed or successful charge to exercise past-due and recovery."""
    await billing_service.simulate_payment(principal, succeed=outcome == "payment_succeeded")
    return await get_billing(principal)
