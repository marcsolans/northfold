"""Derived billing state of an organization (data-plane safe; same rules as ``messer_api.deps``).

States: ``none`` (no subscription), ``trialing``, ``trial_expired`` (trial over without a paid plan),
``active``, ``past_due`` (payment failed; writable during a 7-day grace period), ``canceled`` and
``incomplete``. Read-only applies to canceled subscriptions, expired trials and past-due beyond the grace.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import Org, Subscription

GRACE_DAYS = 7
PAID_STATUSES = ("active", "past_due")


@dataclass(slots=True, frozen=True)
class BillingState:
    status: str
    plan_id: str | None
    read_only: bool
    blocked: bool
    trial_ends_at: datetime | None
    grace_ends_at: datetime | None


def derive_state(org: Org | None, sub: Subscription | None, now: datetime | None = None) -> BillingState:
    now = now or datetime.now(UTC)
    blocked = bool(org is not None and org.status == "blocked")
    if sub is None:
        return BillingState(
            status="none",
            plan_id=org.plan_id if org else None,
            read_only=False,
            blocked=blocked,
            trial_ends_at=None,
            grace_ends_at=None,
        )
    status = sub.status
    read_only = False
    grace_ends_at: datetime | None = None
    if sub.status == "canceled":
        read_only = True
    elif sub.status == "past_due":
        grace_ends_at = (sub.past_due_since or now) + timedelta(days=GRACE_DAYS)
        read_only = now > grace_ends_at
    elif sub.status == "trialing" and sub.trial_ends_at is not None and sub.trial_ends_at < now:
        read_only = True
        status = "trial_expired"
    return BillingState(
        status=status,
        plan_id=sub.plan_id,
        read_only=read_only,
        blocked=blocked,
        trial_ends_at=sub.trial_ends_at,
        grace_ends_at=grace_ends_at,
    )


async def load_state(session: AsyncSession, org_id: uuid.UUID) -> BillingState:
    org = await session.get(Org, org_id)
    sub = (await session.execute(select(Subscription).where(Subscription.org_id == org_id))).scalar_one_or_none()
    return derive_state(org, sub)
