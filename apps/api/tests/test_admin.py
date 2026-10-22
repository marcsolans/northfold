"""Backoffice: superadmin-only access, organization list/detail with cost and margin, credit adjustments,
manual plan changes, blocking, impersonation (imp claim, banner data, audit) and business metrics."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from billing_support import api_client, login
from sqlalchemy import delete, select, update

from messer_common.credits import charge_usage
from messer_common.db import system_session
from messer_common.db.models import (
    AuditLog,
    AuthSession,
    FeatureFlag,
    ModelPrice,
    Plan,
    Subscription,
    Template,
    User,
)
from messer_common.security import decode_access_token


async def _admin(make_user) -> User:  # type: ignore[no-untyped-def]
    return await make_user(f"root-{uuid.uuid4().hex[:6]}@messer.example", superadmin=True)


async def test_admin_requires_superadmin(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    await login(client, owner.email, org.id)
    for path in ("/api/v1/admin/orgs", "/api/v1/admin/metrics", "/api/v1/admin/plans", "/api/v1/admin/users"):
        res = await client.get(path)
        assert res.status_code == 403 and res.json()["error"]["code"] == "superadmin_only", path
    assert (await client.post("/api/v1/admin/impersonation/stop")).status_code == 409


async def test_org_list_detail_usage_and_margin(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    org, owner = await make_org(name="Margen SA")
    async with system_session() as s:
        # 1 USD of model cost charged as 130 credits (0.01 USD each, 30 % margin).
        await charge_usage(s, org_id=org.id, run_id=uuid.uuid4(), project_id=None, cost_usd=Decimal("1"), credits=130)
    await login(client, admin.email)
    page = (await client.get("/api/v1/admin/orgs", params={"q": "margen"})).json()
    assert page["total"] == 1
    row = page["items"][0]
    assert row["owner_email"] == owner.email and row["members"] == 1 and row["subscription_status"] == "trialing"
    assert Decimal(row["model_cost_usd_month"]) == Decimal("1")
    assert Decimal(row["credits_revenue_usd_month"]) == Decimal("1.3")
    assert Decimal(row["margin_usd_month"]) == Decimal("0.3")
    assert Decimal(row["credits_balance"]) == Decimal("9870")
    assert Decimal(row["mrr_eur"]) == 0
    by_status = (await client.get("/api/v1/admin/orgs", params={"payment_status": "active"})).json()
    assert by_status["total"] == 0

    detail = (await client.get(f"/api/v1/admin/orgs/{org.id}")).json()
    assert detail["org"]["id"] == str(org.id) and detail["plan"]["id"] == "pro"
    assert detail["members"][0]["email"] == owner.email and detail["members"][0]["role"] == "owner"
    assert detail["usage"]["seats"]["used"] == 1 and len(detail["ledger"]) == 2
    assert detail["subscription"]["status"] == "trialing"
    assert any(a["action"] == "org.created" for a in detail["audit"])
    assert (await client.get(f"/api/v1/admin/orgs/{uuid.uuid4()}")).status_code == 404


async def test_credit_adjustments_are_audited(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    org, _ = await make_org()
    await login(client, admin.email)
    zero = await client.post(f"/api/v1/admin/orgs/{org.id}/credits", json={"amount": "0", "note": "nada"})
    assert zero.status_code == 400
    no_note = await client.post(f"/api/v1/admin/orgs/{org.id}/credits", json={"amount": "500"})
    assert no_note.status_code == 422
    res = await client.post(
        f"/api/v1/admin/orgs/{org.id}/credits", json={"amount": "500", "note": "Compensación por incidencia"}
    )
    assert res.status_code == 200 and Decimal(res.json()["credits_balance"]) == Decimal("10500")
    res = await client.post(f"/api/v1/admin/orgs/{org.id}/credits", json={"amount": "-1500", "note": "Corrección"})
    assert Decimal(res.json()["credits_balance"]) == Decimal("9000")
    async with system_session() as s:
        entries = (await s.execute(select(AuditLog).where(AuditLog.action == "admin.credits_adjusted"))).scalars().all()
    assert len(entries) == 2 and all(e.actor_id == admin.id and e.org_id == org.id for e in entries)
    assert {e.diff["note"] for e in entries} == {"Compensación por incidencia", "Corrección"}


async def test_manual_plan_change_and_blocking(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    await login(client, admin.email)
    res = await client.post(
        f"/api/v1/admin/orgs/{org.id}/plan",
        json={"plan_id": "business", "interval": "year", "status": "active", "note": "Contrato anual firmado"},
    )
    assert res.status_code == 200, res.text
    row = res.json()
    assert row["plan_id"] == "business" and row["subscription_status"] == "active"
    assert Decimal(row["mrr_eur"]) == Decimal("665.83")
    assert Decimal(row["credits_balance"]) == Decimal("60000")  # trial 10 000 + business month 50 000
    trial = await client.post(
        f"/api/v1/admin/orgs/{org.id}/plan", json={"plan_id": "pro", "status": "trialing", "trial_days": 30}
    )
    assert trial.json()["subscription_status"] == "trialing"
    async with system_session() as s:
        sub = (await s.execute(select(Subscription).where(Subscription.org_id == org.id))).scalar_one()
        assert sub.trial_ends_at is not None and sub.trial_ends_at > datetime.now(UTC) + timedelta(days=29)

    blocked = await client.post(f"/api/v1/admin/orgs/{org.id}/block", json={"reason": "Impago reiterado"})
    assert blocked.json()["status"] == "blocked" and blocked.json()["blocked_reason"] == "Impago reiterado"
    async with api_client() as oc:
        await login(oc, owner.email, org.id)
        refused = await oc.patch("/api/v1/orgs/current", json={"name": "Nuevo"})
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "org_blocked"
        assert (await oc.get("/api/v1/me")).json()["billing"]["blocked"] is True
        await client.post(f"/api/v1/admin/orgs/{org.id}/unblock")
        assert (await oc.patch("/api/v1/orgs/current", json={"name": "Nuevo"})).status_code == 200


async def test_block_user_revokes_sessions(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    other_admin = await _admin(make_user)
    org, owner = await make_org()
    async with api_client() as oc:
        await login(oc, owner.email, org.id)
        await login(client, admin.email)
        res = await client.post(f"/api/v1/admin/users/{owner.id}/block", json={"reason": "Fraude"})
        assert res.status_code == 200 and res.json()["status"] == "blocked"
        assert (await oc.get("/api/v1/me")).status_code == 403
        login_again = await oc.post("/api/v1/auth/login", json={"email": owner.email, "password": "Sup3rSecret!pass"})
        assert login_again.status_code == 403
        async with system_session() as s:
            open_sessions = (
                (
                    await s.execute(
                        select(AuthSession).where(AuthSession.user_id == owner.id, AuthSession.revoked_at.is_(None))
                    )
                )
                .scalars()
                .all()
            )
        assert open_sessions == []
        assert (await client.post(f"/api/v1/admin/users/{owner.id}/unblock")).json()["status"] == "active"
    assert (
        await client.post(f"/api/v1/admin/users/{other_admin.id}/block", json={"reason": "x" * 5})
    ).status_code == 403
    assert (await client.post(f"/api/v1/admin/users/{admin.id}/block", json={"reason": "propia"})).status_code == 409
    users = (await client.get("/api/v1/admin/users", params={"q": owner.email})).json()
    assert users["total"] == 1 and users["items"][0]["orgs"][0]["role"] == "owner"


async def test_impersonation_claim_banner_and_audit(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    org, owner = await make_org(name="Cliente Soporte")
    await login(client, admin.email)
    start = await client.post(
        "/api/v1/admin/impersonation/start", json={"user_id": str(owner.id), "reason": "Ticket #4821"}
    )
    assert start.status_code == 200, start.text
    assert start.json()["org_id"] == str(org.id) and start.json()["redirect"] == "/app"
    claims = decode_access_token(client.cookies["messer_at"])
    assert claims["sub"] == str(owner.id) and claims["imp"] == str(admin.id)

    me = (await client.get("/api/v1/me")).json()
    assert me["email"] == owner.email and me["impersonated_by"] == str(admin.id)
    assert me["is_superadmin"] is False and me["active_org"]["id"] == str(org.id)
    # The support session cannot use the backoffice, and its actions are attributed to the admin.
    assert (await client.get("/api/v1/admin/orgs")).status_code == 403
    assert (await client.patch("/api/v1/orgs/current", json={"name": "Cliente Soporte 2"})).status_code == 200
    async with system_session() as s:
        change = (await s.execute(select(AuditLog).where(AuditLog.action == "org.updated"))).scalar_one()
        assert change.actor_id == owner.id and change.impersonated_by == admin.id
        session = (await s.execute(select(AuthSession).where(AuthSession.impersonated_by == admin.id))).scalar_one()
        assert session.expires_at < datetime.now(UTC) + timedelta(hours=3)
        owner_row = await s.get(User, owner.id)
        assert owner_row is not None and owner_row.last_login_at is None

    stop = await client.post("/api/v1/admin/impersonation/stop")
    assert stop.status_code == 200 and stop.json()["redirect"] == "/admin"
    me = (await client.get("/api/v1/me")).json()
    assert me["email"] == admin.email and me["impersonated_by"] is None and me["is_superadmin"] is True
    async with system_session() as s:
        actions = (
            (
                await s.execute(
                    select(AuditLog.action).where(
                        AuditLog.action.like("admin.impersonation%"), AuditLog.org_id == org.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert sorted(actions) == ["admin.impersonation_started", "admin.impersonation_stopped"]
        assert (await s.get(AuthSession, session.id)).revoked_at is not None  # type: ignore[union-attr]
    feed = (await client.get("/api/v1/admin/audit", params={"org_id": str(org.id)})).json()
    assert {a["action"] for a in feed} == {"admin.impersonation_started", "admin.impersonation_stopped"}
    assert all(a["actor_email"] == admin.email for a in feed)

    other_admin = await _admin(make_user)
    refused = await client.post(
        "/api/v1/admin/impersonation/start", json={"user_id": str(other_admin.id), "reason": "no permitido"}
    )
    assert refused.status_code == 403


async def test_business_metrics_from_fixtures(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    now = datetime.now(UTC)
    fixtures = [
        ("pro", "month", "active", None),
        ("business", "year", "active", None),
        ("starter", "month", "past_due", None),
        ("pro", "month", "canceled", now - timedelta(days=5)),
        ("pro", "month", "trialing", None),
    ]
    orgs = []
    for plan_id, interval, status, canceled_at in fixtures:
        org, _ = await make_org(name=f"M {plan_id} {status}")
        orgs.append(org)
        async with system_session() as s:
            await s.execute(
                update(Subscription)
                .where(Subscription.org_id == org.id)
                .values(
                    plan_id=plan_id,
                    interval=interval,
                    status=status,
                    canceled_at=canceled_at,
                    stripe_subscription_id=None if status == "trialing" else f"sub_sim_{org.id.hex[:12]}",
                    test_mode=True,
                )
            )
    async with system_session() as s:
        await charge_usage(
            s, org_id=orgs[0].id, run_id=uuid.uuid4(), project_id=None, cost_usd=Decimal("2"), credits=260
        )
    await login(client, admin.email)
    m = (await client.get("/api/v1/admin/metrics")).json()
    # 199 + 7990 / 12 + 49
    assert Decimal(m["mrr_eur"]) == Decimal("913.83")
    assert Decimal(m["arr_eur"]) == Decimal("10965.96")
    assert m["paid_subscriptions"] == 3 and m["past_due"] == 1 and m["test_mode"] is True
    assert [p["plan_id"] for p in m["mrr_by_plan"]] == ["business", "pro", "starter"]
    assert m["churn"] == {"window_days": 30, "canceled": 1, "base": 4, "rate": 0.25}
    conversion = m["trial_conversion"]
    assert conversion["trials_started"] == 5 and conversion["converted"] == 4
    assert sum(w["orgs"] for w in m["signups"]) == 5 and len(m["signups"]) == 12
    current = m["current_month"]
    assert Decimal(current["ai_cost_usd"]) == Decimal("2.00") and Decimal(current["credits_revenue_usd"]) == Decimal(
        "2.60"
    )
    assert Decimal(current["margin_usd"]) == Decimal("0.60")
    funnel = {f["step"]: f["orgs"] for f in m["activation_funnel"]}
    assert funnel["signed_up"] == 5 and funnel["paid"] == 4 and funnel["project"] == 0


async def test_plan_catalog_management(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    await login(client, admin.email)
    plans = (await client.get("/api/v1/admin/plans")).json()
    assert {p["id"] for p in plans} >= {"starter", "pro", "business", "enterprise"}
    try:
        res = await client.patch(
            "/api/v1/admin/plans/pro",
            json={"price_month_eur": "219.00", "limits": {**plans[1]["limits"], "seats": 12}},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["price_month_eur"] == "219.00" and body["limits"]["seats"] == 12
        assert body["stripe_sync"] == {"mode": "simulated", "ok": True, "changed": False, "error": None}
        public = {p["id"]: p for p in (await client.get("/api/v1/plans")).json()}
        assert public["pro"]["price_month_eur"] == "219.00"
        bad = await client.patch("/api/v1/admin/plans/pro", json={"limits": {**plans[1]["limits"], "features": ["x"]}})
        assert bad.status_code == 422

        created = await client.post(
            "/api/v1/admin/plans",
            json={
                "id": "test-custom",
                "name": "Custom",
                "price_month_eur": "1500.00",
                "price_year_eur": "15000.00",
                "public": False,
                "self_serve": False,
                "limits": {
                    "seats": 50,
                    "projects": -1,
                    "runs_month": -1,
                    "credits_month": 100000,
                    "storage_gb": 500,
                    "features": ["sso", "api"],
                },
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["limits"]["features"] == ["api", "sso"]
        assert "test-custom" not in {p["id"] for p in (await client.get("/api/v1/plans")).json()}
        assert (
            await client.post("/api/v1/admin/plans", json=created.json() | {"id": "test-custom"})
        ).status_code == 409
        synced = await client.post("/api/v1/admin/plans/sync")
        assert synced.status_code == 200 and all(p["stripe_sync"]["ok"] for p in synced.json())
    finally:
        from messer_api.services.seed import seed_plans

        async with system_session() as s:
            await s.execute(delete(Plan).where(Plan.id == "test-custom"))
            await seed_plans(s, overwrite=True)


async def test_model_prices_templates_and_flags(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    admin = await _admin(make_user)
    org, _ = await make_org()
    await login(client, admin.email)
    model = "anthropic/test-model-x"
    try:
        res = await client.put(
            f"/api/v1/admin/model-prices/{model}",
            json={
                "provider": "anthropic",
                "display_name": "Test X",
                "input_per_mtok_usd": "1.5",
                "output_per_mtok_usd": "7.5",
            },
        )
        assert res.status_code == 200 and res.json()["model"] == model
        assert Decimal(res.json()["output_per_mtok_usd"]) == Decimal("7.5")
        listed = (await client.get("/api/v1/admin/model-prices")).json()
        assert model in {p["model"] for p in listed}
        assert (await client.put("/api/v1/admin/model-prices/no-slash", json=res.json())).status_code == 400
        assert (await client.delete(f"/api/v1/admin/model-prices/{model}")).status_code == 204
    finally:
        async with system_session() as s:
            await s.execute(delete(ModelPrice).where(ModelPrice.model == model))

    ids = [f"test-tpl-{i}" for i in range(3)]
    try:
        async with system_session() as s:
            for i, tid in enumerate(ids):
                s.add(
                    Template(
                        id=tid, sector="test", name=f"T{i}", description="d", repo_snapshot="x", sort_order=900 + i
                    )
                )
        hidden = await client.patch(f"/api/v1/admin/templates/{ids[0]}", json={"public": False})
        assert hidden.status_code == 200 and hidden.json()["public"] is False
        ordered = (await client.put("/api/v1/admin/templates/order", json={"ids": [ids[2], ids[0]]})).json()
        positions = [t["id"] for t in ordered]
        assert positions.index(ids[2]) < positions.index(ids[0])
        assert (await client.put("/api/v1/admin/templates/order", json={"ids": ["missing"]})).status_code == 404
    finally:
        async with system_session() as s:
            await s.execute(delete(Template).where(Template.id.in_(ids)))

    key = "test.flag"
    try:
        flag = await client.put(
            f"/api/v1/admin/feature-flags/{key}",
            json={
                "description": "Prueba",
                "enabled": True,
                "targeting": {"plans": ["business"], "orgs": [str(org.id)]},
            },
        )
        assert flag.status_code == 200 and flag.json()["targeting"]["orgs"] == [str(org.id)]
        from messer_api.services.limits import feature_flag_enabled

        async with system_session() as s:
            assert await feature_flag_enabled(s, key, org.id) is True
            assert await feature_flag_enabled(s, key, uuid.uuid4()) is False
        bad = await client.put(
            f"/api/v1/admin/feature-flags/{key}", json={"enabled": True, "targeting": {"plans": ["nope"]}}
        )
        assert bad.status_code == 400
        assert (await client.put("/api/v1/admin/feature-flags/Bad Key", json={"enabled": True})).status_code == 400
        assert (await client.delete(f"/api/v1/admin/feature-flags/{key}")).status_code == 204
    finally:
        async with system_session() as s:
            await s.execute(delete(FeatureFlag).where(FeatureFlag.key == key))
    async with system_session() as s:
        logged = set((await s.execute(select(AuditLog.action).where(AuditLog.action.like("admin.%")))).scalars().all())
        assert {"admin.model_price_updated", "admin.template_updated", "admin.feature_flag_updated"} <= logged
