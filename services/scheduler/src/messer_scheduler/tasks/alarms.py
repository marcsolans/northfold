"""Alarm evaluation (§7.11): every enabled alarm is checked once a minute.

``messer_api.services.analytics.run_alarm_sweep`` computes each alarm's metric over its window, applies the
ok → firing → ok transitions (row-locked, so overlapping sweeps never double-notify), records them in
``alarm_events`` and delivers in-app, email and Slack notices.
"""

from __future__ import annotations

from messer_api.services.analytics import run_alarm_sweep
from messer_common.logging import get_logger
from messer_scheduler.core import PeriodicTask

log = get_logger("messer.scheduler.alarms")


async def evaluate_alarms() -> None:
    outcomes = await run_alarm_sweep()
    transitions = [o for o in outcomes if o.transitioned]
    errors = [o for o in outcomes if o.error]
    if transitions or errors:
        log.info(
            "alarms.evaluated",
            evaluated=len(outcomes),
            transitions=len(transitions),
            firing=sum(1 for o in transitions if o.state == "firing"),
            errors=len(errors),
        )


TASKS = [PeriodicTask("alarms.evaluate", 60, evaluate_alarms)]
