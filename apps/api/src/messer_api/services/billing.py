"""Billing: the Stripe event state machine, plan changes, credits and the simulated test mode.

Both providers end up here. Stripe delivers events to ``POST /api/v1/webhooks/stripe``; the simulated
provider produces the same events in-process (checkout confirmation, plan changes, renewals). Every
event goes through :func:`process_event`, which is idempotent on the event id (``stripe_events``) and
runs in the caller's transaction, so an event is either fully applied or not at all.

Subscription states: ``trialing`` → ``active`` → ``past_due`` (payment failed: warning + 7-day grace,
``past_due_since``) → ``canceled`` (read-only). Every paid period grants the plan's monthly credits once
(idempotency key per period and plan; upgrades grant the difference). Invoices are mirrored locally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.billing_notify import claim_notice, notify_org
from messer_common.billing_state import PAID_STATUSES, derive_state
from messer_common.budgets import period_bounds, runs_this_month
from messer_common.credits import (
    add_entry,
    auto_topup_allowed_now,
    auto_topup_config,
    balance,
    used_between,
)
from messer_common.credits import maybe_auto_topup as maybe_auto_topup  # re-export for the control plane
from messer_common.db import Principal, system_session
from messer_common.db.models import (
    CreditLedger,
    Invoice,
    KbFile,
    Membership,
    Org,
    Plan,
    StripeEvent,
    Subscription,
    User,
)
from messer_common.db.models.business import SimulatedCheckout
from messer_common.logging import get_logger
from messer_common.plans import CREDIT_PACKS, UNLIMITED, limit_value
from messer_common.settings import get_settings

from ..errors import ApiError, Conflict, NotFound
from .billing_providers import (
    INTERVALS,
    BillingProvider,
    ProviderError,
    ProviderResult,
    SimulatedBilling,
    add_months,
    find_pack,
    get_billing_provider,
    pack_label,
    period_end_for,
)
from .limits import projects_used, seats_used

log = get_logger("messer.billing")

# Stripe statuses we fold into our five states.
STATUS_MAP = {"unpaid": "past_due", "incomplete_expired": "canceled", "paused": "canceled"}
LIVE_STATUSES = ("active", "past_due", "trialing")
GRANT_BILLING_REASONS = ("subscription_create", "subscription_cycle", "subscription_update", "subscription")


class BillingError(ApiError):
    status_code = 409
    code = "billing_error"


def provider() -> BillingProvider:
    return get_billing_provider()


def billing_mode() -> str:
    return provider().mode


def current_test_mode() -> bool:
    return provider().test_mode


def web_url(path: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}{path}"


def _ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromtimestamp(int(value), UTC)


def _meta(obj: dict[str, Any] | None) -> dict[str, str]:
    raw = (obj or {}).get("metadata") or {}
    return {str(k): str(v) for k, v in raw.items() if v is not None}


def _id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return str(value.get("id")) if value.get("id") else None
    return str(value)


def _money(cents: Any) -> Decimal:
    return (Decimal(int(cents or 0)) / 100).quantize(Decimal("0.01"))


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


# ============================================================================= lookups


async def get_subscription(session: AsyncSession, org_id: uuid.UUID, *, lock: bool = False) -> Subscription | None:
    q = select(Subscription).where(Subscription.org_id == org_id)
    if lock:
        q = q.with_for_update()
    return (await session.execute(q)).scalar_one_or_none()


async def _org_for(session: AsyncSession, *, customer: str | None, metadata: dict[str, str]) -> uuid.UUID | None:
    org_id = _uuid(metadata.get("org_id"))
    if org_id is not None and await session.get(Org, org_id) is not None:
        return org_id
    if customer:
        found = (
            await session.execute(select(Subscription.org_id).where(Subscription.stripe_customer_id == customer))
        ).scalar_one_or_none()
        if found is not None:
            return found
    return None


async def plan_for_price(session: AsyncSession, price_id: str | None) -> Plan | None:
    if not price_id:
        return None
    if price_id.startswith("price_sim_"):
        plan_id = price_id[len("price_sim_") :].rsplit("_", 1)[0]
        return await session.get(Plan, plan_id)
    return (
        await session.execute(
            select(Plan).where(
                or_(
                    Plan.stripe_price_ids.op("->>")("month") == price_id,
                    Plan.stripe_price_ids.op("->>")("year") == price_id,
                )
            )
        )
    ).scalar_one_or_none()


def _subscription_item(obj: dict[str, Any]) -> dict[str, Any]:
    items = (obj.get("items") or {}).get("data") or []
    return items[0] if items else {}


def _subscription_period(obj: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    item = _subscription_item(obj)
    start = obj.get("current_period_start") or item.get("current_period_start")
    end = obj.get("current_period_end") or item.get("current_period_end")
    return _ts(start), _ts(end)


def _price_of(entry: dict[str, Any]) -> dict[str, Any]:
    price = entry.get("price") or entry.get("plan")
    if isinstance(price, dict):
        return price
    details = ((entry.get("pricing") or {}).get("price_details")) or {}
    if details.get("price"):
        return {"id": _id(details.get("price"))}
    return {}


def _invoice_subscription_id(inv: dict[str, Any]) -> str | None:
    direct = _id(inv.get("subscription"))
    if direct:
        return direct
    details = ((inv.get("parent") or {}).get("subscription_details")) or {}
    return _id(details.get("subscription"))


def _invoice_metadata(inv: dict[str, Any]) -> dict[str, str]:
    merged = _meta(inv)
    for details in (
        inv.get("subscription_details") or {},
        ((inv.get("parent") or {}).get("subscription_details")) or {},
    ):
        for k, v in (details.get("metadata") or {}).items():
            merged.setdefault(str(k), str(v))
    return merged


def _subscription_line(inv: dict[str, Any]) -> dict[str, Any] | None:
    """The line that defines the paid period: positive amount, latest period end."""
    lines = [line for line in ((inv.get("lines") or {}).get("data") or []) if line.get("period")]
    if not lines:
        return None
    positive = [line for line in lines if int(line.get("amount") or 0) > 0] or lines
    return max(positive, key=lambda line: int((line.get("period") or {}).get("end") or 0))


# ============================================================================= credits


async def grant_plan_credits(
    session: AsyncSession, *, org_id: uuid.UUID, plan: Plan, period_start: datetime, note: str | None = None
) -> Decimal:
    """Grant the plan's monthly credits for the period starting at ``period_start``.

    Idempotent per (period, plan). Within one period, upgrading grants only the difference with what the
    period already received; downgrades grant nothing more.
    """
    credits = limit_value(plan.limits, "credits_month")
    if credits == UNLIMITED or credits <= 0:
        return Decimal("0")
    day = period_start.astimezone(UTC).date().isoformat()
    prefix = f"grant:{org_id}:{day}:"
    already = Decimal(
        str(
            (
                await session.execute(
                    select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                        CreditLedger.org_id == org_id, CreditLedger.idempotency_key.like(f"{prefix}%")
                    )
                )
            ).scalar_one()
        )
    )
    delta = Decimal(credits) - already
    if delta <= 0:
        return Decimal("0")
    inserted = await add_entry(
        session,
        org_id=org_id,
        kind="grant",
        amount=delta,
        note=note or f"Créditos incluidos en {plan.name} (periodo desde {day})",
        idempotency_key=f"{prefix}{plan.id}",
    )
    return delta if inserted else Decimal("0")


async def grant_pack(
    session: AsyncSession, *, org_id: uuid.UUID, credits: int, ref: str, note: str, created_by: uuid.UUID | None = None
) -> bool:
    return await add_entry(
        session,
        org_id=org_id,
        kind="purchase",
        amount=Decimal(credits),
        note=note,
        idempotency_key=f"purchase:{ref}",
        created_by=created_by,
    )


def _pack_credits(metadata: dict[str, str]) -> tuple[dict[str, Any] | None, int]:
    pack = find_pack(metadata.get("pack_id"))
    if pack is not None:
        return pack, int(pack["credits"])
    try:
        return None, int(metadata.get("credits") or 0)
    except ValueError:
        return None, 0


# ============================================================================= event state machine


async def process_event(session: AsyncSession, event: dict[str, Any]) -> bool:
    """Apply one Stripe (or simulated) event. Returns False when it was already processed."""
    event_id = str(event["id"])
    event_type = str(event["type"])
    inserted = (
        await session.execute(
            insert(StripeEvent)
            .values(id=event_id, type=event_type, payload=event)
            .on_conflict_do_nothing(index_elements=[StripeEvent.id])
            .returning(StripeEvent.id)
        )
    ).first()
    if inserted is None:
        return False
    obj: dict[str, Any] = (event.get("data") or {}).get("object") or {}
    livemode = bool(event.get("livemode"))
    handler = _HANDLERS.get(event_type)
    if handler is not None:
        await handler(session, obj, livemode)
    else:
        log.info("billing.event_ignored", event_type=event_type)
    event_row = await session.get(StripeEvent, event_id)
    if event_row is not None:
        event_row.processed_at = datetime.now(UTC)
    return True


async def apply_subscription(
    session: AsyncSession, obj: dict[str, Any], *, livemode: bool, deleted: bool = False
) -> Subscription | None:
    """Mirror a provider subscription object into ``subscriptions`` (the single state transition)."""
    metadata = _meta(obj)
    customer = _id(obj.get("customer"))
    org_id = await _org_for(session, customer=customer, metadata=metadata)
    if org_id is None:
        log.warning("billing.subscription_unknown_org", subscription=obj.get("id"), customer=customer)
        return None
    org = await session.get(Org, org_id)
    assert org is not None
    sub = await get_subscription(session, org_id, lock=True)
    incoming_id = str(obj["id"])
    raw_status = "canceled" if deleted else str(obj.get("status") or "active")
    status = STATUS_MAP.get(raw_status, raw_status)

    is_current = sub is not None and sub.stripe_subscription_id == incoming_id
    if not is_current and status not in LIVE_STATUSES:
        # A checkout that never completed (incomplete) or an old subscription ending must not replace the
        # organization's trial or current subscription. Keep the customer for the next attempt.
        if sub is not None and customer and not sub.stripe_customer_id:
            sub.stripe_customer_id = customer
        return sub

    item = _subscription_item(obj)
    price = _price_of(item)
    plan = await plan_for_price(session, _id(price.get("id")))
    if plan is None and metadata.get("plan_id"):
        plan = await session.get(Plan, metadata["plan_id"])
    if plan is None and sub is not None:
        plan = await session.get(Plan, sub.plan_id)
    if plan is None:
        log.error("billing.subscription_unknown_plan", subscription=incoming_id)
        return sub
    interval = str((price.get("recurring") or {}).get("interval") or metadata.get("interval") or "month")
    if interval not in INTERVALS:
        interval = "month"
    period_start, period_end = _subscription_period(obj)
    now = datetime.now(UTC)

    if sub is None:
        sub = Subscription(org_id=org_id, plan_id=plan.id, status=status)
        session.add(sub)
    before = {
        "status": sub.status,
        "plan_id": sub.plan_id,
        "interval": sub.interval,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }
    previous_status = sub.status if is_current else None

    sub.plan_id = plan.id
    sub.interval = interval
    sub.status = status
    sub.stripe_subscription_id = incoming_id
    if customer:
        sub.stripe_customer_id = customer
    if period_start is not None:
        sub.current_period_start = period_start
    if period_end is not None:
        sub.current_period_end = period_end
    if status == "trialing" and obj.get("trial_end"):
        sub.trial_ends_at = _ts(obj.get("trial_end"))
    if status == "past_due":
        sub.past_due_since = sub.past_due_since or now
    else:
        sub.past_due_since = None
    sub.cancel_at_period_end = bool(obj.get("cancel_at_period_end")) or (
        obj.get("cancel_at") is not None and status != "canceled"
    )
    if status == "canceled":
        sub.canceled_at = _ts(obj.get("ended_at")) or _ts(obj.get("canceled_at")) or now
    elif sub.cancel_at_period_end:
        sub.canceled_at = _ts(obj.get("canceled_at")) or now
    else:
        sub.canceled_at = None
    sub.test_mode = not livemode
    org.plan_id = plan.id
    await session.flush()

    after = {
        "status": sub.status,
        "plan_id": sub.plan_id,
        "interval": sub.interval,
        "cancel_at_period_end": sub.cancel_at_period_end,
    }
    if before != after:
        await audit.record(
            session,
            action="billing.subscription_changed",
            org_id=org_id,
            entity_type="subscription",
            entity_id=incoming_id,
            diff={"before": before, "after": after},
        )
    if status == "canceled" and previous_status != "canceled":
        if await claim_notice(session, org_id=org_id, kind="subscription_canceled", ref=incoming_id):
            await notify_org(
                session,
                org_id=org_id,
                kind="billing.subscription_canceled",
                template="subscription_canceled",
                context={"org": org.name, "plan": plan.name},
                url=web_url("/app/settings/billing"),
                min_role="owner",
            )
    return sub


async def _on_subscription(session: AsyncSession, obj: dict[str, Any], livemode: bool) -> None:
    await apply_subscription(session, obj, livemode=livemode)


async def _on_subscription_deleted(session: AsyncSession, obj: dict[str, Any], livemode: bool) -> None:
    await apply_subscription(session, obj, livemode=livemode, deleted=True)


async def _on_checkout_completed(session: AsyncSession, obj: dict[str, Any], livemode: bool) -> None:
    metadata = _meta(obj)
    customer = _id(obj.get("customer"))
    org_id = await _org_for(session, customer=customer, metadata=metadata) or _uuid(obj.get("client_reference_id"))
    if org_id is None or await session.get(Org, org_id) is None:
        log.warning("billing.checkout_unknown_org", checkout=obj.get("id"))
        return
    sub = await get_subscription(session, org_id, lock=True)
    if sub is not None and customer and not sub.stripe_customer_id:
        sub.stripe_customer_id = customer
    if metadata.get("kind") != "credit_pack":
        return  # subscriptions are applied from customer.subscription.* and invoice.paid
    if obj.get("payment_status") not in ("paid", "no_payment_required"):
        return  # delayed payment methods complete with checkout.session.async_payment_succeeded
    pack, credits = _pack_credits(metadata)
    if credits <= 0:
        log.error("billing.checkout_pack_without_credits", checkout=obj.get("id"))
        return
    label = pack_label(pack) if pack else f"{credits} créditos"
    if await grant_pack(session, org_id=org_id, credits=credits, ref=str(obj["id"]), note=f"Compra: {label}"):
        await audit.record(
            session,
            action="billing.credits_purchased",
            org_id=org_id,
            entity_type="checkout",
            entity_id=obj.get("id"),
            diff={"credits": credits, "pack_id": metadata.get("pack_id")},
        )


async def mirror_invoice(session: AsyncSession, inv: dict[str, Any], org_id: uuid.UUID) -> Invoice:
    stripe_id = str(inv["id"])
    line = _subscription_line(inv)
    period = (line or {}).get("period") or {}
    tax = inv.get("tax")
    if tax is None:
        tax = sum(int(t.get("amount") or 0) for t in inv.get("total_taxes") or [])
    values: dict[str, Any] = {
        "number": inv.get("number"),
        "status": str(inv.get("status") or "draft"),
        "amount_due_eur": _money(inv.get("amount_due")),
        "amount_paid_eur": _money(inv.get("amount_paid")),
        "tax_eur": _money(tax),
        "hosted_invoice_url": inv.get("hosted_invoice_url"),
        "pdf_url": inv.get("invoice_pdf"),
        "period_start": _ts(period.get("start")) or _ts(inv.get("period_start")),
        "period_end": _ts(period.get("end")) or _ts(inv.get("period_end")),
    }
    row = (await session.execute(select(Invoice).where(Invoice.stripe_invoice_id == stripe_id))).scalar_one_or_none()
    if row is None:
        row = Invoice(org_id=org_id, stripe_invoice_id=stripe_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.flush()
    return row


async def _invoice_org(session: AsyncSession, inv: dict[str, Any]) -> uuid.UUID | None:
    return await _org_for(session, customer=_id(inv.get("customer")), metadata=_invoice_metadata(inv))


async def _on_invoice_paid(session: AsyncSession, inv: dict[str, Any], livemode: bool) -> None:
    org_id = await _invoice_org(session, inv)
    if org_id is None:
        log.warning("billing.invoice_unknown_org", invoice=inv.get("id"))
        return
    await mirror_invoice(session, inv, org_id)
    metadata = _invoice_metadata(inv)
    if metadata.get("kind") == "credit_pack":
        if metadata.get("source") == "auto_topup":
            pack, credits = _pack_credits(metadata)
            label = pack_label(pack) if pack else f"{credits} créditos"
            if credits > 0:
                await grant_pack(
                    session, org_id=org_id, credits=credits, ref=str(inv["id"]), note=f"Recarga automática: {label}"
                )
            sub = await get_subscription(session, org_id, lock=True)
            if sub is not None:
                cfg = dict(sub.auto_topup or {})
                cfg.update(last_status="succeeded", last_error=None)
                sub.auto_topup = cfg
        return

    sub_id = _invoice_subscription_id(inv)
    if not sub_id:
        return
    sub = await get_subscription(session, org_id, lock=True)
    if sub is None or (sub.stripe_subscription_id not in (None, sub_id)):
        return
    line = _subscription_line(inv)
    price = _price_of(line or {})
    plan = await plan_for_price(session, _id(price.get("id")))
    line_meta = _meta(line) if line else {}
    if plan is None and (line_meta.get("plan_id") or metadata.get("plan_id")):
        plan = await session.get(Plan, line_meta.get("plan_id") or metadata["plan_id"])
    if plan is None:
        plan = await session.get(Plan, sub.plan_id)
    if plan is None:
        return
    if sub.stripe_subscription_id is None:
        # Paid before the subscription event arrived: link it now, the event reconciles the rest.
        sub.stripe_subscription_id = sub_id
        sub.plan_id = plan.id
        interval = str((price.get("recurring") or {}).get("interval") or metadata.get("interval") or sub.interval)
        sub.interval = interval if interval in INTERVALS else "month"
        sub.status = "active"
        sub.test_mode = not livemode
        customer = _id(inv.get("customer"))
        if customer:
            sub.stripe_customer_id = customer
        org = await session.get(Org, org_id)
        if org is not None:
            org.plan_id = plan.id
    period = (line or {}).get("period") or {}
    line_start, line_end = _ts(period.get("start")), _ts(period.get("end"))
    if line_start and line_end and (sub.current_period_end is None or line_end > sub.current_period_end):
        sub.current_period_start, sub.current_period_end = line_start, line_end
    if sub.status == "past_due":
        sub.status = "active"
        sub.past_due_since = None
    await session.flush()
    reason = str(inv.get("billing_reason") or "subscription")
    if reason in GRANT_BILLING_REASONS and sub.current_period_start is not None:
        granted = await grant_plan_credits(session, org_id=org_id, plan=plan, period_start=sub.current_period_start)
        if granted > 0:
            log.info("billing.credits_granted", org_id=str(org_id), credits=str(granted), invoice=inv.get("id"))


async def _on_invoice_failed(session: AsyncSession, inv: dict[str, Any], livemode: bool) -> None:
    org_id = await _invoice_org(session, inv)
    if org_id is None:
        log.warning("billing.invoice_unknown_org", invoice=inv.get("id"))
        return
    await mirror_invoice(session, inv, org_id)
    org = await session.get(Org, org_id)
    assert org is not None
    metadata = _invoice_metadata(inv)
    sub = await get_subscription(session, org_id, lock=True)
    sub_id = _invoice_subscription_id(inv)
    if metadata.get("kind") == "credit_pack" and metadata.get("source") == "auto_topup":
        if sub is not None:
            cfg = dict(sub.auto_topup or {})
            cfg.update(last_status="failed", last_error="payment_failed")
            sub.auto_topup = cfg
        pack, _ = _pack_credits(metadata)
        if await claim_notice(session, org_id=org_id, kind="auto_topup_failed", ref=str(inv["id"])):
            await notify_org(
                session,
                org_id=org_id,
                kind="billing.auto_topup_failed",
                template="auto_topup_failed",
                context={
                    "org": org.name,
                    "pack": pack_label(pack) if pack else "",
                    "reason": "el pago ha sido rechazado",
                },
                url=web_url("/app/settings/credits"),
                min_role="owner",
            )
        return
    if sub is None or not sub_id or sub.stripe_subscription_id != sub_id:
        return
    now = datetime.now(UTC)
    if sub.status != "past_due":
        await audit.record(
            session,
            action="billing.payment_failed",
            org_id=org_id,
            entity_type="invoice",
            entity_id=inv.get("id"),
            diff={"before": sub.status, "after": "past_due"},
        )
    if sub.status in ("active", "past_due", "trialing"):
        sub.status = "past_due"
        sub.past_due_since = sub.past_due_since or now
    state = derive_state(org, sub, now)
    if await claim_notice(session, org_id=org_id, kind="payment_failed", ref=str(inv["id"])):
        grace = state.grace_ends_at or now
        await notify_org(
            session,
            org_id=org_id,
            kind="billing.payment_failed",
            template="payment_failed",
            context={"org": org.name, "grace_end": grace.strftime("%d/%m/%Y")},
            url=web_url("/app/settings/billing"),
            min_role="owner",
        )


async def _on_invoice_other(session: AsyncSession, inv: dict[str, Any], livemode: bool) -> None:
    org_id = await _invoice_org(session, inv)
    if org_id is not None:
        await mirror_invoice(session, inv, org_id)


_HANDLERS = {
    "checkout.session.completed": _on_checkout_completed,
    "checkout.session.async_payment_succeeded": _on_checkout_completed,
    "customer.subscription.created": _on_subscription,
    "customer.subscription.updated": _on_subscription,
    "customer.subscription.deleted": _on_subscription_deleted,
    "invoice.paid": _on_invoice_paid,
    "invoice.payment_succeeded": _on_invoice_paid,
    "invoice.payment_failed": _on_invoice_failed,
    "invoice.finalized": _on_invoice_other,
    "invoice.updated": _on_invoice_other,
    "invoice.voided": _on_invoice_other,
    "invoice.marked_uncollectible": _on_invoice_other,
}
HANDLED_EVENTS = tuple(_HANDLERS)


async def apply_result(session: AsyncSession, result: ProviderResult) -> None:
    """Apply what a provider call returned (provider objects directly, synthetic events as events)."""
    if result.subscription is not None:
        await apply_subscription(session, result.subscription, livemode=bool(result.subscription.get("livemode")))
    if result.invoice is not None:
        if result.invoice.get("status") == "paid":
            await _on_invoice_paid(session, result.invoice, bool(result.invoice.get("livemode")))
        else:
            await _on_invoice_other(session, result.invoice, bool(result.invoice.get("livemode")))
    for event in result.events:
        await process_event(session, event)


# ============================================================================= read models


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def storage_bytes(session: AsyncSession, org_id: uuid.UUID) -> int:
    total = (
        await session.execute(select(func.coalesce(func.sum(KbFile.size), 0)).where(KbFile.org_id == org_id))
    ).scalar_one()
    return int(total)


async def usage_summary(session: AsyncSession, org_id: uuid.UUID, plan: Plan | None) -> dict[str, Any]:
    limits = plan.limits if plan is not None else {}
    start, end = period_bounds("month")
    used_credits = await used_between(session, org_id, start, end)
    storage = await storage_bytes(session, org_id)
    return {
        "period_start": start,
        "period_end": end,
        "seats": {"used": await seats_used(session, org_id), "limit": limit_value(limits, "seats")},
        "projects": {"used": await projects_used(session, org_id), "limit": limit_value(limits, "projects")},
        "runs_month": {"used": await runs_this_month(session, org_id), "limit": limit_value(limits, "runs_month")},
        "credits": {
            "used": used_credits,
            "limit": limit_value(limits, "credits_month"),
            "balance": await balance(session, org_id),
        },
        "storage_gb": {
            "used": round(storage / 1024**3, 3),
            "used_bytes": storage,
            "limit": limit_value(limits, "storage_gb"),
        },
    }


def subscription_view(org: Org | None, sub: Subscription | None) -> dict[str, Any] | None:
    if sub is None:
        return None
    state = derive_state(org, sub)
    return {
        "status": sub.status,
        "state": state.status,
        "plan_id": sub.plan_id,
        "interval": sub.interval,
        "trial_ends_at": sub.trial_ends_at,
        "current_period_start": sub.current_period_start,
        "current_period_end": sub.current_period_end,
        "cancel_at_period_end": sub.cancel_at_period_end,
        "canceled_at": sub.canceled_at,
        "past_due_since": sub.past_due_since,
        "grace_ends_at": state.grace_ends_at,
        "read_only": state.read_only,
        "paid": bool(sub.stripe_subscription_id) and sub.status in PAID_STATUSES,
        "has_customer": bool(sub.stripe_customer_id),
        "test_mode": sub.test_mode,
    }


async def overview(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    org = await session.get(Org, org_id)
    if org is None:
        raise NotFound("Organización no encontrada")
    sub = await get_subscription(session, org_id)
    plan_id = sub.plan_id if sub else org.plan_id
    plan = await session.get(Plan, plan_id) if plan_id else None
    prov = provider()
    settings = get_settings()
    return {
        "mode": prov.mode,
        "test_mode": prov.test_mode,
        "publishable_key": settings.stripe_publishable_key or None,
        "plan": plan,
        "subscription": subscription_view(org, sub),
        "usage": await usage_summary(session, org_id, plan),
    }


async def credits_overview(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    sub = await get_subscription(session, org_id)
    org = await session.get(Org, org_id)
    plan_id = sub.plan_id if sub else (org.plan_id if org else None)
    plan = await session.get(Plan, plan_id) if plan_id else None
    start, end = period_bounds("month")
    added = (
        await session.execute(
            select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
                CreditLedger.org_id == org_id,
                CreditLedger.amount > 0,
                CreditLedger.created_at >= start,
                CreditLedger.created_at < end,
            )
        )
    ).scalar_one()
    cfg = auto_topup_config(sub)
    return {
        "balance": await balance(session, org_id),
        "credits_month": limit_value(plan.limits, "credits_month") if plan else 0,
        "used_this_month": await used_between(session, org_id, start, end),
        "added_this_month": Decimal(str(added)),
        "period_start": start,
        "period_end": end,
        "credit_usd": Decimal(str(get_settings().messer_credit_usd)),
        "mode": provider().mode,
        "test_mode": provider().test_mode,
        "can_auto_topup": bool(sub and sub.stripe_customer_id),
        "auto_topup": {
            "enabled": cfg["enabled"],
            "threshold": cfg["threshold"],
            "pack_id": cfg["pack_id"],
            "last_status": cfg["last_status"],
            "last_error": cfg["last_error"],
            "last_requested_at": cfg["last_requested_at"],
        },
        "packs": CREDIT_PACKS,
    }


# ============================================================================= flows (API)


async def _owner_email(session: AsyncSession, org_id: uuid.UUID, principal: Principal) -> str | None:
    if principal.email and principal.impersonated_by is None:
        return principal.email
    return (
        await session.execute(
            select(User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == org_id, Membership.role == "owner")
            .order_by(Membership.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()


def _provider_error(exc: ProviderError) -> ApiError:
    return BillingError(exc.message, code=exc.code, status_code=409 if exc.code != "stripe_error" else 502)


async def _assert_fits(session: AsyncSession, org_id: uuid.UUID, plan: Plan) -> None:
    checks = (
        ("seats", await seats_used(session, org_id), "usuarios"),
        ("projects", await projects_used(session, org_id), "proyectos"),
    )
    for key, used, noun in checks:
        limit = limit_value(plan.limits, key)
        if limit != UNLIMITED and used > limit:
            raise Conflict(
                f"El plan {plan.name} incluye {limit} {noun} y ahora tienes {used}. Reduce el uso antes de cambiar.",
                code="downgrade_blocked",
                details={"limit": key, "value": limit, "used": used},
            )


async def change_plan(principal: Principal, *, plan_id: str, interval: str) -> dict[str, Any]:
    """Subscribe or change plan. Returns ``{"action": "checkout", "url"}`` or ``{"action": "updated"}``."""
    assert principal.org_id is not None
    if interval not in INTERVALS:
        raise ApiError("Intervalo no válido", code="invalid_interval")
    prov = provider()
    async with system_session() as s:
        org = await s.get(Org, principal.org_id)
        plan = await s.get(Plan, plan_id)
        if org is None:
            raise NotFound("Organización no encontrada")
        if plan is None or not plan.public:
            raise NotFound("Plan no encontrado", code="unknown_plan")
        if not plan.self_serve:
            raise Conflict(
                f"El plan {plan.name} se contrata con el equipo comercial.",
                code="plan_not_self_serve",
                details={"plan_id": plan.id},
            )
        sub = await get_subscription(s, org.id, lock=True)
        await _assert_fits(s, org.id, plan)
        live = sub is not None and bool(sub.stripe_subscription_id) and sub.status in PAID_STATUSES
        try:
            if live and sub is not None:
                if sub.plan_id == plan.id and sub.interval == interval:
                    if not sub.cancel_at_period_end:
                        raise Conflict("Ya tienes este plan.", code="same_plan")
                    await apply_result(s, await prov.set_cancel_at_period_end(sub=sub, cancel=False))
                else:
                    current_plan = await s.get(Plan, sub.plan_id)
                    assert current_plan is not None
                    result = await prov.change_subscription(
                        sub=sub, current_plan=current_plan, plan=plan, interval=interval
                    )
                    await apply_result(s, result)
                await audit.record(
                    s,
                    action="billing.plan_changed",
                    principal=principal,
                    entity_type="subscription",
                    entity_id=sub.stripe_subscription_id,
                    diff={"plan_id": plan.id, "interval": interval},
                )
                return {"action": "updated"}
            customer = await prov.ensure_customer(
                org=org,
                email=await _owner_email(s, org.id, principal),
                existing=sub.stripe_customer_id if sub else None,
            )
            if sub is not None:
                sub.stripe_customer_id = customer
            link = await prov.subscription_checkout(
                s, org=org, plan=plan, interval=interval, customer_id=customer, actor_id=principal.user_id
            )
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        await audit.record(
            s,
            action="billing.checkout_started",
            principal=principal,
            entity_type="checkout",
            entity_id=link.id,
            diff={"plan_id": plan.id, "interval": interval, "mode": prov.mode},
        )
        return {"action": "checkout", "url": link.url, "checkout_id": link.id}


async def set_cancel(principal: Principal, *, cancel: bool) -> None:
    assert principal.org_id is not None
    prov = provider()
    async with system_session() as s:
        sub = await get_subscription(s, principal.org_id, lock=True)
        if sub is None or not sub.stripe_subscription_id or sub.status not in PAID_STATUSES:
            raise Conflict("No hay ninguna suscripción de pago activa.", code="no_paid_subscription")
        if sub.cancel_at_period_end == cancel:
            raise Conflict(
                "La suscripción ya está programada para cancelarse." if cancel else "La suscripción ya está activa.",
                code="already_canceling" if cancel else "not_canceling",
            )
        try:
            await apply_result(s, await prov.set_cancel_at_period_end(sub=sub, cancel=cancel))
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        await audit.record(
            s,
            action="billing.subscription_cancel_scheduled" if cancel else "billing.subscription_resumed",
            principal=principal,
            entity_type="subscription",
            entity_id=sub.stripe_subscription_id,
            diff={"cancel_at_period_end": cancel, "current_period_end": _iso(sub.current_period_end)},
        )


async def portal_url(principal: Principal) -> str:
    assert principal.org_id is not None
    async with system_session() as s:
        sub = await get_subscription(s, principal.org_id)
    if sub is None or not sub.stripe_customer_id:
        raise Conflict("Todavía no tienes datos de facturación en Stripe.", code="no_customer")
    try:
        return await provider().portal_url(
            customer_id=sub.stripe_customer_id, return_url=web_url("/app/settings/billing")
        )
    except ProviderError as exc:
        raise _provider_error(exc) from exc


async def buy_pack(principal: Principal, *, pack_id: str) -> dict[str, Any]:
    assert principal.org_id is not None
    pack = find_pack(pack_id)
    if pack is None:
        raise NotFound("Paquete no encontrado", code="unknown_pack")
    prov = provider()
    async with system_session() as s:
        org = await s.get(Org, principal.org_id)
        assert org is not None
        sub = await get_subscription(s, org.id, lock=True)
        try:
            customer = await prov.ensure_customer(
                org=org,
                email=await _owner_email(s, org.id, principal),
                existing=sub.stripe_customer_id if sub else None,
            )
            if sub is not None:
                sub.stripe_customer_id = customer
            link = await prov.pack_checkout(s, org=org, pack=pack, customer_id=customer, actor_id=principal.user_id)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        await audit.record(
            s,
            action="billing.pack_checkout_started",
            principal=principal,
            entity_type="checkout",
            entity_id=link.id,
            diff={"pack_id": pack_id, "mode": prov.mode},
        )
    return {"action": "checkout", "url": link.url, "checkout_id": link.id}


async def set_auto_topup(principal: Principal, *, enabled: bool, threshold: int, pack_id: str | None) -> None:
    assert principal.org_id is not None
    if enabled and find_pack(pack_id) is None:
        raise ApiError("Elige un paquete de créditos para la recarga automática", code="unknown_pack")
    async with system_session() as s:
        sub = await get_subscription(s, principal.org_id, lock=True)
        if sub is None:
            raise Conflict("La organización no tiene suscripción.", code="no_subscription")
        if enabled and not sub.stripe_customer_id:
            raise Conflict(
                "Necesitas un método de pago guardado: contrata un plan o compra un paquete primero.",
                code="payment_method_required",
            )
        cfg = dict(sub.auto_topup or {})
        before = {k: cfg.get(k) for k in ("enabled", "threshold", "pack_id")}
        cfg.update(enabled=enabled, threshold=threshold, pack_id=pack_id if enabled else cfg.get("pack_id"))
        sub.auto_topup = cfg
        await audit.record(
            s,
            action="billing.auto_topup_updated",
            principal=principal,
            entity_type="subscription",
            entity_id=sub.id,
            diff={"before": before, "after": {"enabled": enabled, "threshold": threshold, "pack_id": pack_id}},
        )


async def execute_auto_topup(org_id: uuid.UUID) -> dict[str, Any]:
    """Buy the configured pack if the balance is below the threshold (worker job / scheduler sweep)."""
    prov = provider()
    async with system_session() as s:
        sub = await get_subscription(s, org_id, lock=True)
        org = await s.get(Org, org_id)
        cfg = auto_topup_config(sub)
        if sub is None or org is None or not cfg["enabled"] or not sub.stripe_customer_id:
            return {"status": "skipped", "reason": "disabled"}
        if org.status == "blocked" or sub.status not in ("active", "past_due", "trialing"):
            return {"status": "skipped", "reason": "inactive"}
        pack = find_pack(cfg["pack_id"])
        if pack is None:
            return {"status": "skipped", "reason": "unknown_pack"}
        if not auto_topup_allowed_now(cfg):
            return {"status": "skipped", "reason": "cooldown"}
        current = await balance(s, org_id)
        if current >= Decimal(cfg["threshold"]):
            return {"status": "skipped", "reason": "above_threshold"}
        now = datetime.now(UTC)
        raw = dict(sub.auto_topup or {})
        history = [str(h) for h in raw.get("history") or []][-9:]
        raw.update(last_requested_at=now.isoformat(), history=[*history, now.isoformat()], last_status="pending")
        sub.auto_topup = raw
        await s.flush()
        try:
            result = await prov.charge_pack(org=org, sub=sub, pack=pack)
        except ProviderError as exc:
            raw.update(last_status="failed", last_error=exc.message)
            sub.auto_topup = dict(raw)
            if await claim_notice(s, org_id=org_id, kind="auto_topup_failed", ref=now.strftime("%Y-%m-%dT%H")):
                await notify_org(
                    s,
                    org_id=org_id,
                    kind="billing.auto_topup_failed",
                    template="auto_topup_failed",
                    context={"org": org.name, "pack": pack_label(pack), "reason": exc.message},
                    url=web_url("/app/settings/credits"),
                    min_role="owner",
                )
            await audit.record(
                s,
                action="billing.auto_topup_failed",
                org_id=org_id,
                entity_type="subscription",
                entity_id=sub.id,
                diff={"pack_id": pack["id"], "error": exc.message},
            )
            return {"status": "failed", "error": exc.message}
        await apply_result(s, result)
        await audit.record(
            s,
            action="billing.auto_topup",
            org_id=org_id,
            entity_type="subscription",
            entity_id=sub.id,
            diff={"pack_id": pack["id"], "credits": pack["credits"], "balance_before": str(current)},
        )
        return {"status": "succeeded", "pack_id": pack["id"]}


# ----------------------------------------------------------------------------- simulated checkout


async def get_simulated_checkout(principal: Principal, checkout_id: uuid.UUID) -> dict[str, Any]:
    async with system_session() as s:
        checkout = await s.get(SimulatedCheckout, checkout_id)
        if checkout is None or checkout.org_id != principal.org_id:
            raise NotFound("Pago no encontrado", code="unknown_checkout")
        org = await s.get(Org, checkout.org_id)
        plan = await s.get(Plan, checkout.plan_id) if checkout.plan_id else None
        sub = await get_subscription(s, checkout.org_id)
    status = checkout.status
    if status == "open" and checkout.expires_at < datetime.now(UTC):
        status = "expired"
    pack = find_pack(checkout.pack_id)
    return {
        "id": checkout.id,
        "kind": checkout.kind,
        "status": status,
        "amount_eur": checkout.amount_eur,
        "plan": plan,
        "interval": checkout.interval,
        "pack": pack,
        "org_name": org.name if org else "",
        "expires_at": checkout.expires_at,
        "created_at": checkout.created_at,
        "current_plan_id": sub.plan_id if sub else None,
        "mode": provider().mode,
    }


async def confirm_simulated_checkout(principal: Principal, checkout_id: uuid.UUID) -> dict[str, Any]:
    prov = provider()
    if not isinstance(prov, SimulatedBilling):
        raise Conflict("Los pagos de prueba solo existen sin clave de Stripe.", code="not_simulated")
    async with system_session() as s:
        checkout = (
            await s.execute(select(SimulatedCheckout).where(SimulatedCheckout.id == checkout_id).with_for_update())
        ).scalar_one_or_none()
        if checkout is None or checkout.org_id != principal.org_id:
            raise NotFound("Pago no encontrado", code="unknown_checkout")
        if checkout.status != "open":
            raise Conflict("Este pago ya no está abierto.", code="checkout_closed", details={"status": checkout.status})
        if checkout.expires_at < datetime.now(UTC):
            checkout.status = "expired"
            raise Conflict("Este pago ha caducado. Vuelve a empezar.", code="checkout_expired")
        sub = await get_subscription(s, checkout.org_id, lock=True)
        if checkout.kind == "subscription" and sub is not None and sub.stripe_subscription_id:
            if sub.status in PAID_STATUSES:
                raise Conflict("Ya tienes una suscripción activa.", code="already_subscribed")
        if checkout.plan_id:
            plan = await s.get(Plan, checkout.plan_id)
            if plan is not None:
                await _assert_fits(s, checkout.org_id, plan)
        try:
            events = prov.checkout_events(checkout, sub=sub)
        except ProviderError as exc:
            raise _provider_error(exc) from exc
        for event in events:
            await process_event(s, event)
        checkout.status = "completed"
        checkout.completed_at = datetime.now(UTC)
        checkout.result = {**(checkout.result or {}), "events": [e["id"] for e in events]}
        await audit.record(
            s,
            action="billing.checkout_completed",
            principal=principal,
            entity_type="checkout",
            entity_id=checkout.id,
            diff={"kind": checkout.kind, "plan_id": checkout.plan_id, "pack_id": checkout.pack_id, "mode": "simulated"},
        )
        kind = checkout.kind
    target = "/app/settings/credits" if kind == "credit_pack" else "/app/settings/billing"
    return {"status": "completed", "kind": kind, "redirect": f"{target}?checkout=success"}


async def cancel_simulated_checkout(principal: Principal, checkout_id: uuid.UUID) -> dict[str, Any]:
    async with system_session() as s:
        checkout = await s.get(SimulatedCheckout, checkout_id)
        if checkout is None or checkout.org_id != principal.org_id:
            raise NotFound("Pago no encontrado", code="unknown_checkout")
        if checkout.status == "open":
            checkout.status = "canceled"
        kind = checkout.kind
    target = "/app/settings/credits" if kind == "credit_pack" else "/app/settings/billing"
    return {"status": "canceled", "kind": kind, "redirect": f"{target}?checkout=canceled"}


async def simulate_payment(principal: Principal, *, succeed: bool) -> None:
    """Test mode only: simulate the outcome of the next charge of the current period (failure → past_due)."""
    prov = provider()
    if not isinstance(prov, SimulatedBilling):
        raise Conflict("Solo disponible en modo de prueba.", code="not_simulated")
    assert principal.org_id is not None
    async with system_session() as s:
        sub = await get_subscription(s, principal.org_id, lock=True)
        if sub is None or not sub.stripe_subscription_id or sub.status not in PAID_STATUSES:
            raise Conflict("No hay ninguna suscripción de pago activa.", code="no_paid_subscription")
        plan = await s.get(Plan, sub.plan_id)
        assert plan is not None
        event = prov.renewal_invoice_event(sub, plan, paid=succeed)
        await process_event(s, event)
        await audit.record(
            s,
            action="billing.simulated_payment",
            principal=principal,
            entity_type="subscription",
            entity_id=sub.stripe_subscription_id,
            diff={"outcome": "succeeded" if succeed else "failed"},
        )


# ----------------------------------------------------------------------------- periodic (scheduler)


async def run_simulated_renewals(now: datetime | None = None) -> int:
    """Simulated mode: renew (or end) subscriptions whose period is over, as Stripe would. Returns renewals."""
    prov = provider()
    if not isinstance(prov, SimulatedBilling):
        return 0
    now = now or datetime.now(UTC)
    count = 0
    async with system_session() as s:
        subs = (
            (
                await s.execute(
                    select(Subscription)
                    .where(
                        Subscription.stripe_subscription_id.like("sub_sim_%"),
                        Subscription.status == "active",
                        Subscription.current_period_end <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for sub in subs:
            for _ in range(36):  # catch up at most three years of missed periods
                if sub.current_period_end is None or sub.current_period_end > now or sub.status != "active":
                    break
                plan = await s.get(Plan, sub.plan_id)
                if plan is None:
                    break
                ending = sub.cancel_at_period_end
                for event in prov.renewal_events(sub, now):
                    await process_event(s, event)
                if ending:
                    break
                await process_event(s, prov.renewal_invoice_event(sub, plan, paid=True))
                count += 1
    return count


async def run_periodic_grants(now: datetime | None = None) -> int:
    """Monthly credits that no invoice triggers. Returns the number of grants made.

    * Annual subscriptions pay once a year but receive the plan's credits every month of the period.
    * Manual subscriptions (assigned in /admin, invoiced outside Stripe) roll their period forward when it
      ends and receive credits every month.
    """
    now = now or datetime.now(UTC)
    granted = 0
    async with system_session() as s:
        subs = (
            (
                await s.execute(
                    select(Subscription)
                    .where(
                        Subscription.status == "active",
                        Subscription.current_period_start.is_not(None),
                        or_(Subscription.interval == "year", Subscription.stripe_subscription_id.is_(None)),
                    )
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for sub in subs:
            plan = await s.get(Plan, sub.plan_id)
            if plan is None or sub.current_period_start is None:
                continue
            if sub.stripe_subscription_id is None:
                for _ in range(36):  # manual renewal, catching up missed periods
                    end = sub.current_period_end or period_end_for(sub.current_period_start, sub.interval)
                    if end > now:
                        break
                    sub.current_period_start, sub.current_period_end = end, period_end_for(end, sub.interval)
            months = 12 if sub.interval == "year" else 1
            for n in range(months):
                month_start = add_months(sub.current_period_start, n)
                if month_start > now or (sub.current_period_end and month_start >= sub.current_period_end):
                    break
                if await grant_plan_credits(s, org_id=sub.org_id, plan=plan, period_start=month_start) > 0:
                    granted += 1
    return granted


async def run_auto_topup_sweep() -> int:
    """Safety net for ``maybe_auto_topup``: top up every organization below its threshold."""
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Subscription.org_id).where(
                    Subscription.auto_topup.op("->>")("enabled") == "true",
                    Subscription.stripe_customer_id.is_not(None),
                )
            )
        ).all()
    done = 0
    for (org_id,) in rows:
        result = await execute_auto_topup(org_id)
        if result.get("status") == "succeeded":
            done += 1
    return done
