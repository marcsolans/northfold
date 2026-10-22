"""Billing: public catalog, trial overview, simulated checkout end to end, plan changes, cancel/resume,
credit packs, auto top-up, plan limits and the Phase 2 acceptance (trial → Pro in test mode → MRR in /admin)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from billing_support import api_client, login
from sqlalchemy import func, select, update

from messer_common.credits import balance, charge_usage, maybe_auto_topup
from messer_common.db import system_session
from messer_common.db.models import CreditLedger, Invoice, Project, Subscription
from messer_common.email import ConsoleEmailAdapter


async def _owner(make_user, make_org, client: httpx.AsyncClient):  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner, name="Facturas SL")
    await login(client, owner.email, org.id)
    return org, owner


async def _subscribe(client: httpx.AsyncClient, plan_id: str = "pro", interval: str = "month") -> dict:  # type: ignore[type-arg]
    res = await client.post("/api/v1/billing/subscription", json={"plan_id": plan_id, "interval": interval})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] == "checkout"
    assert "/app/settings/billing/checkout/" in body["url"]
    checkout_id = body["checkout_id"]
    detail = await client.get(f"/api/v1/billing/checkout/{checkout_id}")
    assert detail.status_code == 200, detail.text
    confirm = await client.post(f"/api/v1/billing/checkout/{checkout_id}/confirm")
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["redirect"].startswith("/app/settings/billing?checkout=success")
    return detail.json()


async def _balance(org_id: uuid.UUID) -> Decimal:
    async with system_session() as s:
        return await balance(s, org_id)


async def _add_projects(org_id: uuid.UUID, n: int) -> None:
    async with system_session() as s:
        for i in range(n):
            s.add(Project(org_id=org_id, name=f"P{i}", slug=f"p-{i}-{uuid.uuid4().hex[:4]}", repo_path="/tmp/p"))


async def test_public_plans_and_credit_packs(client: httpx.AsyncClient) -> None:
    plans = (await client.get("/api/v1/plans")).json()
    assert [p["id"] for p in plans] == ["starter", "pro", "business", "enterprise"]
    pro = plans[1]
    assert pro["price_month_eur"] == "199.00" and pro["price_year_eur"] == "1990.00"
    assert pro["limits"]["seats"] == 10 and "connectors" in pro["limits"]["features"]
    assert plans[2]["limits"]["projects"] == -1
    assert plans[3]["price_is_starting"] is True and plans[3]["self_serve"] is False
    packs = (await client.get("/api/v1/credit-packs")).json()
    assert packs[0] == {"id": "pack_5k", "credits": 5000, "price_eur": "55.00"}


async def test_trial_overview(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    await _owner(make_user, make_org, client)
    data = (await client.get("/api/v1/billing")).json()
    assert data["mode"] == "simulated" and data["test_mode"] is True
    assert data["plan"]["id"] == "pro"
    sub = data["subscription"]
    assert sub["status"] == "trialing" and sub["paid"] is False and sub["read_only"] is False
    usage = data["usage"]
    assert usage["seats"] == {"used": 1, "limit": 10}
    assert usage["projects"] == {"used": 0, "limit": 5}
    assert Decimal(usage["credits"]["balance"]) == Decimal("10000")
    assert data["can_manage"] is True
    credits = (await client.get("/api/v1/billing/credits")).json()
    assert Decimal(credits["balance"]) == 10000 and credits["credits_month"] == 10000
    ledger = (await client.get("/api/v1/billing/credits/ledger")).json()
    assert ledger["total"] == 1 and ledger["items"][0]["kind"] == "grant"


async def test_acceptance_trial_to_pro_in_test_mode_appears_in_admin(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await make_user("root@example.com", superadmin=True)
    async with api_client() as owner_c, api_client() as admin_c:
        signup = await owner_c.post(
            "/api/v1/auth/signup",
            json={"email": "ana@acme.example", "password": "Contrasena123", "name": "Ana", "org_name": "Acme Facturas"},
        )
        assert signup.status_code == 200, signup.text
        org_id = signup.json()["org_id"]
        assert (await owner_c.get("/api/v1/me")).json()["billing"]["status"] == "trialing"

        checkout = await _subscribe(owner_c, "pro", "month")
        assert checkout["kind"] == "subscription" and checkout["amount_eur"] == "199.00"
        assert checkout["mode"] == "simulated"

        overview = (await owner_c.get("/api/v1/billing")).json()
        sub = overview["subscription"]
        assert sub["status"] == "active" and sub["paid"] is True and sub["interval"] == "month"
        assert sub["current_period_end"] is not None
        me = (await owner_c.get("/api/v1/me")).json()
        assert me["billing"]["status"] == "active" and me["billing"]["read_only"] is False
        # Trial credits + the first paid month.
        assert Decimal(overview["usage"]["credits"]["balance"]) == Decimal("20000")
        invoices = (await owner_c.get("/api/v1/billing/invoices")).json()
        assert len(invoices) == 1 and invoices[0]["status"] == "paid" and invoices[0]["amount_paid_eur"] == "199.00"
        assert invoices[0]["test"] is True

        await login(admin_c, admin.email)
        orgs = (await admin_c.get("/api/v1/admin/orgs", params={"q": "Acme"})).json()
        assert orgs["total"] == 1
        row = orgs["items"][0]
        assert row["id"] == org_id and row["plan_id"] == "pro" and row["subscription_status"] == "active"
        assert Decimal(row["mrr_eur"]) == Decimal("199")
        metrics = (await admin_c.get("/api/v1/admin/metrics")).json()
        assert Decimal(metrics["mrr_eur"]) == Decimal("199") and metrics["paid_subscriptions"] == 1


async def test_checkout_confirm_is_single_use_and_owner_only(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await _owner(make_user, make_org, client)
    res = (await client.post("/api/v1/billing/subscription", json={"plan_id": "pro", "interval": "month"})).json()
    cid = res["checkout_id"]
    assert (await client.post(f"/api/v1/billing/checkout/{cid}/confirm")).status_code == 200
    again = await client.post(f"/api/v1/billing/checkout/{cid}/confirm")
    assert again.status_code == 409 and again.json()["error"]["code"] == "checkout_closed"
    # Builders cannot pay or change plans.
    builder = await make_user()
    async with system_session() as s:
        from messer_common.db.models import Membership

        s.add(Membership(org_id=org.id, user_id=builder.id, role="builder"))
    async with api_client() as other:
        await login(other, builder.email, org.id)
        denied = await other.post("/api/v1/billing/subscription", json={"plan_id": "business", "interval": "month"})
        assert denied.status_code == 403
        assert (await other.get("/api/v1/billing")).json()["can_manage"] is False
    # Self-serve only; unknown plans are rejected.
    enterprise = await client.post("/api/v1/billing/subscription", json={"plan_id": "enterprise", "interval": "year"})
    assert enterprise.status_code == 409 and enterprise.json()["error"]["code"] == "plan_not_self_serve"
    assert (await client.post("/api/v1/billing/subscription", json={"plan_id": "nope"})).status_code == 404


async def test_upgrade_grants_credit_difference_and_downgrade_rules(
    client: httpx.AsyncClient, make_user, make_org
) -> None:  # type: ignore[no-untyped-def]
    org, _ = await _owner(make_user, make_org, client)
    await _subscribe(client, "pro", "month")
    assert await _balance(org.id) == Decimal("20000")

    up = await client.post("/api/v1/billing/subscription", json={"plan_id": "business", "interval": "month"})
    assert up.status_code == 200 and up.json()["action"] == "updated"
    data = (await client.get("/api/v1/billing")).json()
    assert data["plan"]["id"] == "business" and data["subscription"]["status"] == "active"
    # Same period: only the difference with what the period already received (50 000 − 10 000).
    assert await _balance(org.id) == Decimal("60000")
    invoices = (await client.get("/api/v1/billing/invoices")).json()
    assert len(invoices) == 2  # the proration invoice is mirrored

    same = await client.post("/api/v1/billing/subscription", json={"plan_id": "business", "interval": "month"})
    assert same.status_code == 409 and same.json()["error"]["code"] == "same_plan"

    await _add_projects(org.id, 2)
    blocked = await client.post("/api/v1/billing/subscription", json={"plan_id": "starter", "interval": "month"})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "downgrade_blocked"
    assert blocked.json()["error"]["details"]["limit"] == "projects"

    down = await client.post("/api/v1/billing/subscription", json={"plan_id": "pro", "interval": "month"})
    assert down.status_code == 200
    assert await _balance(org.id) == Decimal("60000")  # downgrades never grant more


async def test_annual_interval_mrr_and_monthly_grants(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.admin import mrr_of
    from messer_api.services.billing import run_periodic_grants

    org, _ = await _owner(make_user, make_org, client)
    detail = await _subscribe(client, "pro", "year")
    assert detail["amount_eur"] == "1990.00"
    async with system_session() as s:
        sub = (await s.execute(select(Subscription).where(Subscription.org_id == org.id))).scalar_one()
        from messer_common.db.models import Plan

        plan = await s.get(Plan, "pro")
        assert mrr_of(sub, plan) == Decimal("165.83")
        start = sub.current_period_start
    assert start is not None
    assert await _balance(org.id) == Decimal("20000")
    granted = await run_periodic_grants(now=start + timedelta(days=62))
    assert granted == 2
    assert await _balance(org.id) == Decimal("40000")
    assert await run_periodic_grants(now=start + timedelta(days=62)) == 0


async def test_cancel_resume_and_end_of_period(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.billing import run_simulated_renewals

    org, owner = await _owner(make_user, make_org, client)
    trial_cancel = await client.post("/api/v1/billing/subscription/cancel")
    assert trial_cancel.status_code == 409 and trial_cancel.json()["error"]["code"] == "no_paid_subscription"
    await _subscribe(client, "pro", "month")

    canceled = (await client.post("/api/v1/billing/subscription/cancel")).json()
    assert canceled["subscription"]["cancel_at_period_end"] is True
    assert canceled["subscription"]["status"] == "active"
    resumed = (await client.post("/api/v1/billing/subscription/resume")).json()
    assert resumed["subscription"]["cancel_at_period_end"] is False
    await client.post("/api/v1/billing/subscription/cancel")

    async with system_session() as s:
        end = (
            await s.execute(select(Subscription.current_period_end).where(Subscription.org_id == org.id))
        ).scalar_one()
    assert end is not None
    ConsoleEmailAdapter.sent.clear()
    assert await run_simulated_renewals(now=end + timedelta(minutes=1)) == 0
    me = (await client.get("/api/v1/me")).json()
    assert me["billing"]["status"] == "canceled" and me["billing"]["read_only"] is True
    assert any(e.to == owner.email and "cancelada" in e.subject for e in ConsoleEmailAdapter.sent)
    # Read-only: writing endpoints refuse, billing stays available to reactivate.
    blocked = await client.post("/api/v1/budgets", json={"limit_usd": "10.00"})
    assert blocked.status_code == 402 and blocked.json()["error"]["code"] == "read_only"
    again = await client.post("/api/v1/billing/subscription", json={"plan_id": "pro", "interval": "month"})
    assert again.status_code == 200 and again.json()["action"] == "checkout"


async def test_simulated_renewal_grants_each_paid_period(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.billing import run_simulated_renewals

    org, _ = await _owner(make_user, make_org, client)
    await _subscribe(client, "starter", "month")
    assert await _balance(org.id) == Decimal("12000")  # trial 10 000 + starter 2 000
    async with system_session() as s:
        end = (
            await s.execute(select(Subscription.current_period_end).where(Subscription.org_id == org.id))
        ).scalar_one()
    assert end is not None
    assert await run_simulated_renewals(now=end + timedelta(hours=1)) == 1
    assert await run_simulated_renewals(now=end + timedelta(hours=1)) == 0
    assert await _balance(org.id) == Decimal("14000")
    invoices = (await client.get("/api/v1/billing/invoices")).json()
    assert len(invoices) == 2 and all(i["status"] == "paid" for i in invoices)
    data = (await client.get("/api/v1/billing")).json()
    assert datetime.fromisoformat(data["subscription"]["current_period_start"]) >= end - timedelta(seconds=1)


async def test_simulated_payment_failure_and_recovery(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    _, owner = await _owner(make_user, make_org, client)
    await _subscribe(client, "pro", "month")
    ConsoleEmailAdapter.sent.clear()
    failed = (await client.post("/api/v1/billing/simulate/payment_failed")).json()
    assert failed["subscription"]["status"] == "past_due"
    assert failed["subscription"]["grace_ends_at"] is not None and failed["subscription"]["read_only"] is False
    assert any(e.to == owner.email and "No hemos podido cobrar" in e.subject for e in ConsoleEmailAdapter.sent)
    notifications = (await client.get("/api/v1/notifications")).json()
    assert any(n["kind"] == "billing.payment_failed" for n in notifications["items"])
    recovered = (await client.post("/api/v1/billing/simulate/payment_succeeded")).json()
    assert recovered["subscription"]["status"] == "active" and recovered["subscription"]["past_due_since"] is None


async def test_credit_pack_purchase_and_ledger(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await _owner(make_user, make_org, client)
    res = await client.post("/api/v1/billing/credits/purchase", json={"pack_id": "pack_5k"})
    assert res.status_code == 200 and res.json()["action"] == "checkout"
    cid = res.json()["checkout_id"]
    detail = (await client.get(f"/api/v1/billing/checkout/{cid}")).json()
    assert detail["kind"] == "credit_pack" and detail["pack"]["credits"] == 5000 and detail["amount_eur"] == "55.00"
    confirm = (await client.post(f"/api/v1/billing/checkout/{cid}/confirm")).json()
    assert confirm["redirect"].startswith("/app/settings/credits")
    assert await _balance(org.id) == Decimal("15000")
    purchases = (await client.get("/api/v1/billing/credits/ledger", params={"kind": "purchase"})).json()
    assert purchases["total"] == 1 and Decimal(purchases["items"][0]["amount"]) == 5000
    assert (await client.post("/api/v1/billing/credits/purchase", json={"pack_id": "x"})).status_code == 404
    # Cancelled checkouts never grant anything.
    other = (await client.post("/api/v1/billing/credits/purchase", json={"pack_id": "pack_25k"})).json()
    await client.post(f"/api/v1/billing/checkout/{other['checkout_id']}/cancel")
    late = await client.post(f"/api/v1/billing/checkout/{other['checkout_id']}/confirm")
    assert late.status_code == 409
    assert await _balance(org.id) == Decimal("15000")


async def test_charge_usage_is_idempotent(make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    run_id = uuid.uuid4()
    async with system_session() as s:
        for _ in range(3):
            await charge_usage(
                s, org_id=org.id, run_id=run_id, project_id=None, cost_usd=Decimal("0.5"), credits=Decimal("65")
            )
        await charge_usage(s, org_id=org.id, run_id=uuid.uuid4(), project_id=None, cost_usd=0, credits=0)
        with pytest.raises(ValueError):
            await charge_usage(s, org_id=org.id, run_id=uuid.uuid4(), project_id=None, cost_usd=1, credits=-1)
    async with system_session() as s:
        usage = (
            await s.execute(
                select(func.count())
                .select_from(CreditLedger)
                .where(CreditLedger.org_id == org.id, CreditLedger.kind == "usage")
            )
        ).scalar_one()
        assert usage == 1
        assert await balance(s, org.id) == Decimal("9935")


async def test_auto_topup_flow(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.billing import execute_auto_topup

    org, _ = await _owner(make_user, make_org, client)
    early = await client.put(
        "/api/v1/billing/credits/auto-topup", json={"enabled": True, "threshold": 20000, "pack_id": "pack_5k"}
    )
    assert early.status_code == 409 and early.json()["error"]["code"] == "payment_method_required"
    res = (await client.post("/api/v1/billing/credits/purchase", json={"pack_id": "pack_5k"})).json()
    await client.post(f"/api/v1/billing/checkout/{res['checkout_id']}/confirm")
    assert await _balance(org.id) == Decimal("15000")

    saved = await client.put(
        "/api/v1/billing/credits/auto-topup", json={"enabled": True, "threshold": 20000, "pack_id": "pack_5k"}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["auto_topup"] == {
        "enabled": True,
        "threshold": 20000,
        "pack_id": "pack_5k",
        "last_status": None,
        "last_error": None,
        "last_requested_at": None,
    }
    async with system_session() as s:
        assert await maybe_auto_topup(s, org.id) is True  # enqueued for the worker
    result = await execute_auto_topup(org.id)
    assert result["status"] == "succeeded"
    assert await _balance(org.id) == Decimal("20000")
    assert (await execute_auto_topup(org.id))["status"] == "skipped"  # above threshold now
    async with system_session() as s:
        await s.execute(
            update(CreditLedger).where(CreditLedger.org_id == org.id, CreditLedger.kind == "purchase").values(amount=0)
        )
    assert (await execute_auto_topup(org.id))["reason"] == "cooldown"  # never twice within 10 minutes
    credits = (await client.get("/api/v1/billing/credits")).json()
    assert credits["auto_topup"]["last_status"] == "succeeded"
    disabled = await client.put("/api/v1/billing/credits/auto-topup", json={"enabled": False, "threshold": 0})
    assert disabled.json()["auto_topup"]["enabled"] is False


async def test_plan_limits_helpers(make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_api.errors import PlanLimitExceeded
    from messer_api.services.limits import feature_flag_enabled, require_capacity, require_feature

    org, _ = await make_org()
    async with system_session() as s:
        await require_feature(s, org.id, "connectors")
        with pytest.raises(PlanLimitExceeded) as feature:
            await require_feature(s, org.id, "sso")
        assert feature.value.status_code == 402 and feature.value.code == "plan_limit"
        assert feature.value.details["feature"] == "sso" and feature.value.details["upgrade_to"] == "business"
        await require_capacity(s, org.id, "projects", 4)
        with pytest.raises(PlanLimitExceeded) as capacity:
            await require_capacity(s, org.id, "projects", 5)
        assert capacity.value.details == {
            "limit": "projects",
            "value": 5,
            "used": 5,
            "upgrade_to": "business",
            "current_plan": "pro",
        }
        assert await feature_flag_enabled(s, "guard", org.id) is True
        assert await feature_flag_enabled(s, "does-not-exist", org.id) is False


async def test_seat_limit_on_invitations(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await _owner(make_user, make_org, client)
    async with system_session() as s:
        await s.execute(update(Subscription).where(Subscription.org_id == org.id).values(plan_id="starter"))
    for email in ("a@example.com", "b@example.com"):
        assert (await client.post("/api/v1/invitations", json={"email": email})).status_code == 201
    third = await client.post("/api/v1/invitations", json={"email": "c@example.com"})
    assert third.status_code == 402
    error = third.json()["error"]
    assert error["code"] == "plan_limit"
    assert error["details"]["limit"] == "seats" and error["details"]["upgrade_to"] == "pro"


async def test_invoices_and_mutations_are_owner_only(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user()
    org, _ = await make_org()
    async with system_session() as s:
        from messer_common.db.models import Membership

        s.add(Membership(org_id=org.id, user_id=viewer.id, role="viewer"))
    async with api_client() as c:
        await login(c, viewer.email, org.id)
        assert (await c.get("/api/v1/billing")).status_code == 200
        assert (await c.get("/api/v1/billing/invoices")).status_code == 403
        assert (await c.post("/api/v1/billing/portal")).status_code == 403
        assert (await c.post("/api/v1/billing/credits/purchase", json={"pack_id": "pack_5k"})).status_code == 403


async def test_portal_unavailable_in_test_mode(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    await _owner(make_user, make_org, client)
    no_customer = await client.post("/api/v1/billing/portal")
    assert no_customer.status_code == 409 and no_customer.json()["error"]["code"] == "no_customer"
    await _subscribe(client)
    simulated = await client.post("/api/v1/billing/portal")
    assert simulated.status_code == 409 and simulated.json()["error"]["code"] == "portal_unavailable"
    async with system_session() as s:
        count = (await s.execute(select(func.count()).select_from(Invoice))).scalar_one()
    assert count == 1
