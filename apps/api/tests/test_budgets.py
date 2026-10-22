"""Budgets: CRUD per organization and project, spend from runs.cost_usd, alerts once per period, hard stop,
and the runtime gate (check_budget: billing state, credits, monthly run limit, budgets)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
from billing_support import add_run, api_client, login
from sqlalchemy import func, select, update

from messer_common.budgets import check_budget, evaluate_alerts, period_bounds
from messer_common.credits import add_entry
from messer_common.db import system_session
from messer_common.db.models import Membership, Notification, Org, Project, Subscription
from messer_common.email import ConsoleEmailAdapter


async def _setup(client: httpx.AsyncClient, make_user, make_org):  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner, name="Budget Co")
    async with system_session() as s:
        project = Project(org_id=org.id, name="Soporte", slug=f"soporte-{uuid.uuid4().hex[:4]}", repo_path="/tmp/x")
        s.add(project)
        await s.flush()
        project_id = project.id
    await login(client, owner.email, org.id)
    return org, owner, project_id


async def test_budget_crud_and_permissions(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _, project_id = await _setup(client, make_user, make_org)
    created = await client.post("/api/v1/budgets", json={"limit_usd": "100.00", "alert_threshold_pct": 75})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["project_id"] is None and body["period"] == "month" and body["hard_stop"] is True
    assert Decimal(body["spent_usd"]) == 0 and body["state"] == "ok"
    dup = await client.post("/api/v1/budgets", json={"limit_usd": "5.00"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "budget_exists"

    proj = await client.post(
        "/api/v1/budgets", json={"project_id": str(project_id), "limit_usd": "20.00", "period": "week"}
    )
    assert proj.status_code == 201 and proj.json()["project_name"] == "Soporte"
    other = await client.post("/api/v1/budgets", json={"project_id": str(uuid.uuid4()), "limit_usd": "1.00"})
    assert other.status_code == 404
    invalid = await client.post("/api/v1/budgets", json={"limit_usd": "0"})
    assert invalid.status_code == 422

    listed = (await client.get("/api/v1/budgets")).json()
    assert [b["project_name"] for b in listed] == [None, "Soporte"]

    patched = await client.patch(f"/api/v1/budgets/{body['id']}", json={"limit_usd": "150.00", "hard_stop": False})
    assert patched.status_code == 200 and Decimal(patched.json()["limit_usd"]) == Decimal("150.00")
    assert patched.json()["hard_stop"] is False

    viewer = await make_user()
    async with system_session() as s:
        s.add(Membership(org_id=org.id, user_id=viewer.id, role="viewer"))
    async with api_client() as vc:
        await login(vc, viewer.email, org.id)
        assert len((await vc.get("/api/v1/budgets")).json()) == 2
        assert (await vc.post("/api/v1/budgets", json={"limit_usd": "1.00"})).status_code == 403
        assert (await vc.delete(f"/api/v1/budgets/{body['id']}")).status_code == 403

    assert (await client.delete(f"/api/v1/budgets/{body['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/budgets/{body['id']}")).status_code == 404
    async with system_session() as s:
        from messer_common.db.models import AuditLog

        actions = set((await s.execute(select(AuditLog.action).where(AuditLog.org_id == org.id))).scalars().all())
    assert {"budget.created", "budget.updated", "budget.deleted"} <= actions


async def test_alert_once_per_period_and_hard_stop(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, project_id = await _setup(client, make_user, make_org)
    budget = (await client.post("/api/v1/budgets", json={"limit_usd": "10.00", "alert_threshold_pct": 50})).json()
    await add_run(org.id, project_id, "6.00")
    # Runs from a previous month do not count.
    last_month = period_bounds("month")[0] - timedelta(days=3)
    await add_run(org.id, project_id, "500.00", started_at=last_month)

    ConsoleEmailAdapter.sent.clear()
    async with system_session() as s:
        status = await check_budget(s, org.id, project_id)
    assert status.allowed is True and status.remaining_usd == Decimal("4.00")
    assert status.budget_id == uuid.UUID(budget["id"])
    alerts = [e for e in ConsoleEmailAdapter.sent if e.tags == ["budget_alert"]]
    assert len(alerts) == 1 and alerts[0].to == owner.email and "60%" in alerts[0].subject
    async with system_session() as s:
        assert await evaluate_alerts(s, org_id=org.id) == 0  # once per period
        kinds = (await s.execute(select(Notification.kind).where(Notification.org_id == org.id))).scalars().all()
    assert kinds == ["budget.alert"]
    listed = (await client.get("/api/v1/budgets")).json()[0]
    assert listed["state"] == "alert" and listed["pct"] == 60 and listed["last_alerted_at"] is not None

    await add_run(org.id, project_id, "4.50")
    async with system_session() as s:
        stopped = await check_budget(s, org.id, project_id)
        assert stopped.allowed is False and stopped.reason == "budget_exceeded"
        assert stopped.message and stopped.spent_usd == Decimal("10.50")
        assert await evaluate_alerts(s, org_id=org.id) == 0
    exceeded = [e for e in ConsoleEmailAdapter.sent if e.tags == ["budget_exceeded"]]
    assert len(exceeded) == 1 and "detenidas" in exceeded[0].text
    gate = (await client.get("/api/v1/budgets/check", params={"project_id": str(project_id)})).json()
    assert gate["allowed"] is False and gate["reason"] == "budget_exceeded"

    # Without hard stop the run is allowed (alerts only).
    await client.patch(f"/api/v1/budgets/{budget['id']}", json={"hard_stop": False})
    async with system_session() as s:
        assert (await check_budget(s, org.id, project_id)).allowed is True


async def test_project_budget_is_scoped(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _, project_id = await _setup(client, make_user, make_org)
    async with system_session() as s:
        other = Project(org_id=org.id, name="Ventas", slug=f"ventas-{uuid.uuid4().hex[:4]}", repo_path="/tmp/y")
        s.add(other)
        await s.flush()
        other_id = other.id
    await client.post("/api/v1/budgets", json={"project_id": str(project_id), "limit_usd": "2.00"})
    await add_run(org.id, project_id, "3.00")
    async with system_session() as s:
        assert (await check_budget(s, org.id, project_id)).reason == "budget_exceeded"
        assert (await check_budget(s, org.id, other_id)).allowed is True
        assert (await check_budget(s, org.id, None)).allowed is True


async def test_gate_billing_credits_and_run_limits(make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    async with system_session() as s:
        status = await check_budget(s, org.id, None)
        assert status.allowed is True and status.remaining_usd is None
        await add_entry(s, org_id=org.id, kind="adjustment", amount=-10000, note="test")
    async with system_session() as s:
        exhausted = await check_budget(s, org.id, None)
        assert exhausted.allowed is False and exhausted.reason == "credits_exhausted"
        await add_entry(s, org_id=org.id, kind="adjustment", amount=10, note="test")
        await s.execute(
            update(Subscription)
            .where(Subscription.org_id == org.id)
            .values(trial_ends_at=datetime.now(UTC) - timedelta(days=1))
        )
    async with system_session() as s:
        assert (await check_budget(s, org.id, None)).reason == "read_only"
        await s.execute(update(Org).where(Org.id == org.id).values(status="blocked"))
    async with system_session() as s:
        assert (await check_budget(s, org.id, None)).reason == "org_blocked"
        await s.execute(update(Org).where(Org.id == org.id).values(status="active"))
        await s.execute(
            update(Subscription)
            .where(Subscription.org_id == org.id)
            .values(trial_ends_at=datetime.now(UTC) + timedelta(days=3), plan_id="starter")
        )
        project = Project(org_id=org.id, name="P", slug="p-runs", repo_path="/tmp/p")
        s.add(project)
        await s.flush()
        project_id = project.id
    from messer_common.db.models import Run

    async with system_session() as s:
        s.add_all([Run(id=uuid.uuid4(), org_id=org.id, project_id=project_id, status="success") for _ in range(2000)])
    async with system_session() as s:
        limited = await check_budget(s, org.id, project_id)
        assert limited.allowed is False and limited.reason == "runs_limit"
        assert (await s.execute(select(func.count()).select_from(Run))).scalar_one() == 2000
