"""Cron triggers and approval expiry."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from messer_common import audit, triggers
from messer_common.approvals import decide, resume_request
from messer_common.db import system_session
from messer_common.db.models import Approval, Trigger
from messer_common.logging import get_logger
from messer_common.queue import Jobs, enqueue

from ..core import PeriodicTask

log = get_logger("messer.scheduler.triggers")


async def fire_due_cron() -> None:
    """Fire every enabled cron trigger whose time has come (one job per scheduled instant)."""
    now = datetime.now(UTC)
    async with system_session() as s:
        due = (
            (
                await s.execute(
                    select(Trigger)
                    .where(Trigger.kind == "cron", Trigger.enabled.is_(True), Trigger.next_fire_at <= now)
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for trigger in due:
            cfg = trigger.config or {}
            scheduled = trigger.next_fire_at or now
            await triggers.fire(
                trigger,
                {"type": "cron", "scheduled_at": scheduled.isoformat(), "expression": cfg.get("expression")},
                event_id=f"cron:{scheduled.isoformat()}",
            )
            try:
                trigger.next_fire_at = triggers.next_cron(
                    str(cfg.get("expression")), str(cfg.get("timezone") or "Europe/Madrid"), now
                )
            except triggers.TriggerConfigError as exc:
                trigger.enabled = False
                trigger.state = {**(trigger.state or {}), "disabled_reason": str(exc)}
    if due:
        log.info("scheduler.cron_fired", count=len(due))


async def expire_approvals() -> None:
    """Apply the default action to approvals past their expiry and resume their runs."""
    now = datetime.now(UTC)
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(Approval)
                    .where(Approval.status == "pending", Approval.expires_at <= now)
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        requests = []
        for approval in rows:
            decision = "approve" if approval.expiry_action == "approve" else "deny"
            await decide(
                s,
                approval,
                decision=decision,
                user_id=None,
                via="expiry",
                comment="Caducada: se aplicó la acción por defecto",
            )
            await audit.record(
                s,
                action=f"approval.expired_{approval.status}",
                org_id=approval.org_id,
                entity_type="approval",
                entity_id=approval.id,
                diff={"tool": approval.tool_name},
            )
            request = await resume_request(s, approval.run_id)
            if request is not None:
                requests.append(request)
    for request in requests:
        await enqueue(Jobs.RESUME_RUN, request, _job_id=f"resume:{request['run_id']}")
    if rows:
        log.info("scheduler.approvals_expired", count=len(rows))


TASKS = [
    PeriodicTask(name="cron_triggers", interval_s=15, fn=fire_due_cron),
    PeriodicTask(name="approval_expiry", interval_s=60, fn=expire_approvals),
]
