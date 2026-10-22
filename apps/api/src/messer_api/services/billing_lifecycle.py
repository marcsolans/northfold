"""Trial lifecycle: welcome and help emails on days 1, 3, 7 and 12, and the end of the trial.

Runs from the scheduler (``messer_scheduler.tasks.billing``). Idempotent: each message is claimed in
``billing_notices`` before it is sent, so restarts and parallel schedulers never send it twice. If the
scheduler was down, only the most recent due email is sent (earlier ones are marked as skipped).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from messer_common.billing_notify import claim_notice, notify_org, org_recipients
from messer_common.db import system_session
from messer_common.db.models import Org, Plan, Subscription
from messer_common.email import EmailError, send_template
from messer_common.logging import get_logger
from messer_common.plans import TRIAL_DAYS, TRIAL_PLAN

from .billing import web_url

log = get_logger("messer.billing.lifecycle")

# Trial day → minimum time since the trial started.
TRIAL_EMAILS: dict[int, timedelta] = {
    1: timedelta(0),
    3: timedelta(days=2),
    7: timedelta(days=6),
    12: timedelta(days=11),
}
TRIAL_EMAIL_PATHS = {1: "/app", 3: "/app/knowledge", 7: "/app/projects", 12: "/app/settings/billing"}


def _eur(value: object) -> str:
    amount = f"{float(str(value)):,.0f}".replace(",", ".")
    return f"{amount} €"


async def _local_trials(now: datetime) -> list[tuple[Subscription, Org]]:
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Subscription, Org)
                .join(Org, Org.id == Subscription.org_id)
                .where(
                    Subscription.status == "trialing",
                    Subscription.stripe_subscription_id.is_(None),
                    Subscription.trial_ends_at.is_not(None),
                    Org.status == "active",
                )
            )
        ).all()
    return [(sub, org) for sub, org in rows]


async def run_trial_emails(now: datetime | None = None) -> int:
    """Send the due trial email to each organization's owners. Returns the number of emails sent."""
    now = now or datetime.now(UTC)
    sent = 0
    for sub, org in await _local_trials(now):
        assert sub.trial_ends_at is not None
        if sub.trial_ends_at <= now:
            continue
        started = sub.trial_ends_at - timedelta(days=TRIAL_DAYS)
        elapsed = now - started
        due = [day for day, offset in TRIAL_EMAILS.items() if elapsed >= offset]
        if not due:
            continue
        top = max(due)
        async with system_session() as s:
            if not await claim_notice(s, org_id=org.id, kind=f"trial_day_{top}", payload={"sent_at": now.isoformat()}):
                continue
            for day in due:
                if day != top:
                    await claim_notice(s, org_id=org.id, kind=f"trial_day_{day}", payload={"skipped": True})
            pro = await s.get(Plan, TRIAL_PLAN)
            for person in await org_recipients(s, org.id, "owner"):
                context: dict[str, object] = {
                    "name": person.name or person.email,
                    "url": web_url(TRIAL_EMAIL_PATHS[top]),
                    "trial_end": sub.trial_ends_at.strftime("%d/%m/%Y"),
                    "pro_price": _eur(pro.price_month_eur) if pro else "",
                }
                try:
                    await send_template(person.email, f"trial_day_{top}", context, person.locale)
                    sent += 1
                except EmailError as exc:
                    log.error("trial_email.failed", org_id=str(org.id), day=top, error=str(exc))
    return sent


async def run_trial_expiry(now: datetime | None = None) -> int:
    """Tell owners when a trial ends without a paid plan (the organization becomes read-only)."""
    now = now or datetime.now(UTC)
    notified = 0
    for sub, org in await _local_trials(now):
        assert sub.trial_ends_at is not None
        if sub.trial_ends_at > now:
            continue
        async with system_session() as s:
            if not await claim_notice(
                s, org_id=org.id, kind="trial_expired", payload={"trial_ends_at": sub.trial_ends_at.isoformat()}
            ):
                continue
            await notify_org(
                s,
                org_id=org.id,
                kind="billing.trial_expired",
                template="trial_expired",
                context={"org": org.name},
                url=web_url("/app/settings/billing"),
                min_role="owner",
            )
            notified += 1
    return notified
