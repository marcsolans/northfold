"""Billing periodic tasks.

* ``billing.trial_emails``      — welcome/help emails on trial days 1, 3, 7 and 12 (idempotent per org/day).
* ``billing.trial_expiry``      — notify owners once when a trial ends without a paid plan (read-only).
* ``billing.simulated_renewals``— test mode without Stripe: renew/end subscriptions at period end exactly as
  Stripe would (``customer.subscription.*`` + ``invoice.paid`` → monthly credit grant).
* ``billing.periodic_grants``   — monthly credits for annual and manually assigned subscriptions.
* ``billing.auto_topup``        — safety net for ``maybe_auto_topup`` (balance below the threshold).
* ``billing.budget_alerts``     — budget threshold / limit notices (once per period).

Every task is idempotent; the scheduler's leader lock keeps one instance acting at a time.
"""

from __future__ import annotations

from messer_api.services import billing, billing_lifecycle
from messer_common.budgets import evaluate_alerts
from messer_common.db import system_session
from messer_common.logging import get_logger
from messer_scheduler.core import PeriodicTask

log = get_logger("messer.scheduler.billing")


async def trial_emails() -> None:
    sent = await billing_lifecycle.run_trial_emails()
    if sent:
        log.info("billing.trial_emails", sent=sent)


async def trial_expiry() -> None:
    notified = await billing_lifecycle.run_trial_expiry()
    if notified:
        log.info("billing.trial_expiry", notified=notified)


async def simulated_renewals() -> None:
    renewed = await billing.run_simulated_renewals()
    if renewed:
        log.info("billing.simulated_renewals", renewed=renewed)


async def periodic_grants() -> None:
    granted = await billing.run_periodic_grants()
    if granted:
        log.info("billing.periodic_grants", granted=granted)


async def auto_topup() -> None:
    done = await billing.run_auto_topup_sweep()
    if done:
        log.info("billing.auto_topup_sweep", purchases=done)


async def budget_alerts() -> None:
    async with system_session() as s:
        fired = await evaluate_alerts(s)
    if fired:
        log.info("billing.budget_alerts", fired=fired)


TASKS = [
    PeriodicTask("billing.trial_emails", 15 * 60, trial_emails),
    PeriodicTask("billing.trial_expiry", 15 * 60, trial_expiry),
    PeriodicTask("billing.simulated_renewals", 10 * 60, simulated_renewals),
    PeriodicTask("billing.periodic_grants", 60 * 60, periodic_grants),
    PeriodicTask("billing.auto_topup", 10 * 60, auto_topup),
    PeriodicTask("billing.budget_alerts", 5 * 60, budget_alerts),
]
