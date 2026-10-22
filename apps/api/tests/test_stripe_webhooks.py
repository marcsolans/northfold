"""Stripe webhooks: signature verification, idempotency and the subscription state machine
(trial → active → past_due → grace over → canceled read-only), with Stripe-shaped payloads."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from billing_support import event, login, post_event, sign
from sqlalchemy import select, update

from messer_common.credits import balance
from messer_common.db import system_session
from messer_common.db.models import AuditLog, Invoice, Plan, StripeEvent, Subscription
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import reset_settings_cache

SECRET = "whsec_test_messer_123"


@pytest.fixture
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    reset_settings_cache()
    yield SECRET
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    reset_settings_cache()


@pytest.fixture
async def stripe_prices() -> AsyncIterator[dict[str, str]]:
    """Plans as if synced to Stripe (plans are reference data kept across tests: restore afterwards)."""
    ids = {"pro": {"month": "price_test_pro_m", "year": "price_test_pro_y"}, "business": {"month": "price_test_biz_m"}}
    async with system_session() as s:
        before = {p: (await s.get(Plan, p)).stripe_price_ids for p in ids}  # type: ignore[union-attr]
        for plan_id, prices in ids.items():
            await s.execute(update(Plan).where(Plan.id == plan_id).values(stripe_price_ids=prices))
    yield {"pro": "price_test_pro_m", "business": "price_test_biz_m"}
    async with system_session() as s:
        for plan_id, prices in before.items():
            await s.execute(update(Plan).where(Plan.id == plan_id).values(stripe_price_ids=prices))


def _subscription(org_id: uuid.UUID, price: str, status: str, start: int, end: int, **extra: object) -> dict:  # type: ignore[type-arg]
    return {
        "id": "sub_test_1",
        "object": "subscription",
        "customer": "cus_test_1",
        "status": status,
        "livemode": False,
        "metadata": {"org_id": str(org_id)},
        "cancel_at_period_end": False,
        "items": {
            "data": [
                {
                    "id": "si_test_1",
                    "price": {"id": price, "recurring": {"interval": "month"}},
                    "current_period_start": start,
                    "current_period_end": end,
                }
            ]
        },
        **extra,
    }


def _invoice(invoice_id: str, price: str, reason: str, start: int, end: int, *, paid: bool = True) -> dict:  # type: ignore[type-arg]
    return {
        "id": invoice_id,
        "object": "invoice",
        "customer": "cus_test_1",
        "billing_reason": reason,
        "status": "paid" if paid else "open",
        "number": f"MSR-{invoice_id[-4:]}",
        "currency": "eur",
        "amount_due": 24079,
        "amount_paid": 24079 if paid else 0,
        "total_taxes": [{"amount": 4179}],
        "hosted_invoice_url": f"https://invoice.stripe.com/i/{invoice_id}",
        "invoice_pdf": f"https://pay.stripe.com/invoice/{invoice_id}/pdf",
        "parent": {"subscription_details": {"subscription": "sub_test_1", "metadata": {}}},
        "lines": {
            "data": [
                {
                    "amount": 19900,
                    "period": {"start": start, "end": end},
                    "pricing": {"price_details": {"price": price}},
                }
            ]
        },
    }


async def _state(org_id: uuid.UUID) -> Subscription:
    async with system_session() as s:
        return (await s.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one()


async def _balance(org_id: uuid.UUID) -> Decimal:
    async with system_session() as s:
        return await balance(s, org_id)


async def test_signature_verification(client: httpx.AsyncClient, webhook_secret: str) -> None:
    body = json.dumps(event("customer.created", {"id": "cus_x"})).encode()
    missing = await client.post("/api/v1/webhooks/stripe", content=body)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "invalid_signature"
    wrong = await client.post("/api/v1/webhooks/stripe", content=body, headers={"Stripe-Signature": sign(body, "nope")})
    assert wrong.status_code == 400
    stale = await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sign(body, webhook_secret, int(time.time()) - 3600)},
    )
    assert stale.status_code == 400
    ok = await client.post(
        "/api/v1/webhooks/stripe", content=body, headers={"Stripe-Signature": sign(body, webhook_secret)}
    )
    assert ok.status_code == 200 and ok.json() == {"received": True, "duplicate": False}


async def test_webhook_requires_configured_secret(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/v1/webhooks/stripe", content=b"{}", headers={"Stripe-Signature": "t=1,v1=x"})
    assert res.status_code == 503 and res.json()["error"]["code"] == "webhook_not_configured"


async def test_state_machine_trial_active_past_due_grace_canceled(
    client: httpx.AsyncClient,
    make_user,  # type: ignore[no-untyped-def]
    make_org,  # type: ignore[no-untyped-def]
    webhook_secret: str,
    stripe_prices: dict[str, str],
) -> None:
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    await login(client, owner.email, org.id)
    assert (await _state(org.id)).status == "trialing"
    now = datetime.now(UTC)
    t0, t1 = int(now.timestamp()), int((now + timedelta(days=30)).timestamp())

    # A checkout that did not complete must not replace the trial.
    incomplete = _subscription(org.id, stripe_prices["pro"], "incomplete", t0, t1)
    assert (
        await post_event(client, event("customer.subscription.created", incomplete), webhook_secret)
    ).status_code == 200
    sub = await _state(org.id)
    assert sub.status == "trialing" and sub.stripe_subscription_id is None and sub.stripe_customer_id == "cus_test_1"

    # trialing → active
    active = _subscription(org.id, stripe_prices["pro"], "active", t0, t1)
    res = await post_event(client, event("customer.subscription.updated", active), webhook_secret)
    assert res.status_code == 200, res.text
    sub = await _state(org.id)
    assert (sub.status, sub.plan_id, sub.stripe_subscription_id) == ("active", "pro", "sub_test_1")
    assert sub.test_mode is True and sub.current_period_end is not None

    # First paid period: invoice mirrored, monthly credits granted once (replays are no-ops).
    paid = event("invoice.paid", _invoice("in_test_0001", stripe_prices["pro"], "subscription_create", t0, t1))
    first = await post_event(client, paid, webhook_secret)
    assert first.json() == {"received": True, "duplicate": False}
    dup = await post_event(client, paid, webhook_secret)
    assert dup.json() == {"received": True, "duplicate": True}
    assert await _balance(org.id) == Decimal("20000")
    async with system_session() as s:
        inv = (await s.execute(select(Invoice).where(Invoice.stripe_invoice_id == "in_test_0001"))).scalar_one()
        assert inv.amount_paid_eur == Decimal("240.79") and inv.tax_eur == Decimal("41.79")
        assert inv.pdf_url and inv.hosted_invoice_url
        assert (await s.get(StripeEvent, paid["id"])).processed_at is not None  # type: ignore[union-attr]
    # A different event id for the same invoice does not grant the period twice either.
    replay = event(
        "invoice.payment_succeeded", _invoice("in_test_0001", stripe_prices["pro"], "subscription_create", t0, t1)
    )
    await post_event(client, replay, webhook_secret)
    assert await _balance(org.id) == Decimal("20000")

    # active → past_due: warning email, 7-day grace, still writable.
    ConsoleEmailAdapter.sent.clear()
    t2 = int((now + timedelta(days=60)).timestamp())
    failed = event(
        "invoice.payment_failed",
        _invoice("in_test_0002", stripe_prices["pro"], "subscription_cycle", t1, t2, paid=False),
    )
    await post_event(client, failed, webhook_secret)
    sub = await _state(org.id)
    assert sub.status == "past_due" and sub.past_due_since is not None
    assert any(e.to == owner.email and e.tags == ["payment_failed"] for e in ConsoleEmailAdapter.sent)
    me = (await client.get("/api/v1/me")).json()
    assert me["billing"]["status"] == "past_due" and me["billing"]["read_only"] is False
    assert me["billing"]["grace_ends_at"] is not None
    assert (await client.post("/api/v1/budgets", json={"limit_usd": "50.00"})).status_code == 201
    # Stripe retries: the same failure does not email twice; the subscription update keeps the grace start.
    ConsoleEmailAdapter.sent.clear()
    await post_event(client, event("invoice.payment_failed", failed["data"]["object"]), webhook_secret)
    since = (await _state(org.id)).past_due_since
    await post_event(
        client,
        event("customer.subscription.updated", _subscription(org.id, stripe_prices["pro"], "past_due", t1, t2)),
        webhook_secret,
    )
    assert (await _state(org.id)).past_due_since == since
    assert not [e for e in ConsoleEmailAdapter.sent if e.tags == ["payment_failed"]]

    # Grace period over → read-only (billing stays usable).
    async with system_session() as s:
        await s.execute(
            update(Subscription)
            .where(Subscription.org_id == org.id)
            .values(past_due_since=datetime.now(UTC) - timedelta(days=8))
        )
    me = (await client.get("/api/v1/me")).json()
    assert me["billing"]["read_only"] is True
    blocked = await client.patch("/api/v1/orgs/current", json={"name": "Otro"})
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "read_only"
    assert (await client.get("/api/v1/billing")).status_code == 200

    # Payment recovered → active, next period's credits.
    await post_event(
        client,
        event("invoice.paid", _invoice("in_test_0002", stripe_prices["pro"], "subscription_cycle", t1, t2)),
        webhook_secret,
    )
    sub = await _state(org.id)
    assert sub.status == "active" and sub.past_due_since is None
    assert sub.current_period_end is not None and int(sub.current_period_end.timestamp()) == t2
    assert await _balance(org.id) == Decimal("30000")
    assert (await client.get("/api/v1/me")).json()["billing"]["read_only"] is False

    # Upgrade through the portal: the price decides the plan.
    upgraded = _subscription(org.id, stripe_prices["business"], "active", t1, t2)
    await post_event(client, event("customer.subscription.updated", upgraded), webhook_secret)
    assert (await _state(org.id)).plan_id == "business"

    # Deleted → canceled, read-only, owner notified.
    ConsoleEmailAdapter.sent.clear()
    gone = _subscription(org.id, stripe_prices["business"], "canceled", t1, t2, ended_at=int(time.time()))
    await post_event(client, event("customer.subscription.deleted", gone), webhook_secret)
    sub = await _state(org.id)
    assert sub.status == "canceled" and sub.canceled_at is not None
    me = (await client.get("/api/v1/me")).json()
    assert me["billing"]["status"] == "canceled" and me["billing"]["read_only"] is True
    assert any(e.tags == ["subscription_canceled"] for e in ConsoleEmailAdapter.sent)
    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action).where(AuditLog.org_id == org.id))).scalars().all())
    assert {"billing.subscription_changed", "billing.payment_failed"} <= actions


async def test_checkout_pack_event_grants_once(
    client: httpx.AsyncClient,
    make_org,  # type: ignore[no-untyped-def]
    webhook_secret: str,
) -> None:
    org, _ = await make_org()
    session = {
        "id": "cs_test_pack_1",
        "object": "checkout.session",
        "mode": "payment",
        "customer": "cus_pack",
        "payment_status": "paid",
        "metadata": {"org_id": str(org.id), "kind": "credit_pack", "pack_id": "pack_25k", "credits": "25000"},
    }
    await post_event(client, event("checkout.session.completed", session), webhook_secret)
    await post_event(client, event("checkout.session.async_payment_succeeded", session), webhook_secret)
    assert await _balance(org.id) == Decimal("35000")
    unpaid = {**session, "id": "cs_test_pack_2", "payment_status": "unpaid"}
    await post_event(client, event("checkout.session.completed", unpaid), webhook_secret)
    assert await _balance(org.id) == Decimal("35000")
    sub = await _state(org.id)
    assert sub.stripe_customer_id == "cus_pack"


async def test_unknown_events_are_recorded(client: httpx.AsyncClient, webhook_secret: str) -> None:
    evt = event("charge.refunded", {"id": "ch_1"})
    assert (await post_event(client, evt, webhook_secret)).json()["duplicate"] is False
    async with system_session() as s:
        row = await s.get(StripeEvent, evt["id"])
    assert row is not None and row.type == "charge.refunded"
