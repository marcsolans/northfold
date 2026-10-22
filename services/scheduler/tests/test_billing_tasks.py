"""Billing scheduler tasks: trial emails (days 1, 3, 7, 12, idempotent), trial expiry and task registration."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from messer_api.services.billing_lifecycle import run_trial_emails, run_trial_expiry
from messer_common.db import system_session
from messer_common.db.models import Notification, Subscription
from messer_common.db.models.business import BillingNotice
from messer_common.email import ConsoleEmailAdapter
from messer_scheduler.core import discover_tasks


def _trial_mails(to: str) -> list[str]:
    return [e.tags[0] for e in ConsoleEmailAdapter.sent if e.to == to and e.tags and e.tags[0].startswith("trial_")]


async def _trial_start(org_id) -> datetime:  # type: ignore[no-untyped-def]
    async with system_session() as s:
        sub = (await s.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one()
    assert sub.trial_ends_at is not None
    return sub.trial_ends_at - timedelta(days=14)


def test_billing_tasks_are_registered() -> None:
    names = {t.name for t in discover_tasks()}
    assert {
        "billing.trial_emails",
        "billing.trial_expiry",
        "billing.simulated_renewals",
        "billing.periodic_grants",
        "billing.auto_topup",
        "billing.budget_alerts",
    } <= names


async def test_trial_emails_days_1_3_7_12_are_sent_once(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    start = await _trial_start(org.id)
    ConsoleEmailAdapter.sent.clear()

    assert await run_trial_emails(now=start + timedelta(minutes=5)) == 1
    assert await run_trial_emails(now=start + timedelta(hours=3)) == 0
    assert _trial_mails(owner.email) == ["trial_day_1"]

    assert await run_trial_emails(now=start + timedelta(days=2, hours=1)) == 1
    # The scheduler was down for a week: only the latest due email goes out, day 7 is skipped.
    assert await run_trial_emails(now=start + timedelta(days=11, hours=2)) == 1
    assert await run_trial_emails(now=start + timedelta(days=12)) == 0
    assert _trial_mails(owner.email) == ["trial_day_1", "trial_day_3", "trial_day_12"]
    day12 = next(e for e in ConsoleEmailAdapter.sent if e.tags == ["trial_day_12"])
    assert "199 €" in day12.text and "/app/settings/billing" in day12.text

    async with system_session() as s:
        kinds = sorted((await s.execute(select(BillingNotice.kind).where(BillingNotice.org_id == org.id))).scalars())
    assert kinds == ["trial_day_1", "trial_day_12", "trial_day_3", "trial_day_7"]


async def test_trial_expiry_notifies_once(make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    start = await _trial_start(org.id)
    ConsoleEmailAdapter.sent.clear()
    assert await run_trial_expiry(now=start + timedelta(days=10)) == 0
    assert await run_trial_expiry(now=start + timedelta(days=15)) == 1
    assert await run_trial_expiry(now=start + timedelta(days=16)) == 0
    assert [e.tags for e in ConsoleEmailAdapter.sent if e.to == owner.email] == [["trial_expired"]]
    # No more trial emails once the trial has ended.
    assert await run_trial_emails(now=start + timedelta(days=15)) == 0
    async with system_session() as s:
        notes = (await s.execute(select(Notification).where(Notification.org_id == org.id))).scalars().all()
    assert [n.kind for n in notes] == ["billing.trial_expired"]
    assert notes[0].payload["url"] == "/app/settings/billing"
