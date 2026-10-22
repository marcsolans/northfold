"""Scheduled connector syncs, connector event polling (workflow triggers), agent liveness, event retention."""

from __future__ import annotations

from messer_api.services.connector_events import poll_connector_events
from messer_api.services.connector_syncs import (
    enqueue_due_syncs,
    mark_stale_agents_offline,
    purge_old_connector_events,
)
from messer_scheduler.core import PeriodicTask


async def enqueue_due() -> None:
    await enqueue_due_syncs()


async def agents_liveness() -> None:
    await mark_stale_agents_offline()


async def poll_events() -> None:
    await poll_connector_events()


async def events_retention() -> None:
    await purge_old_connector_events()


TASKS = [
    PeriodicTask("syncs.enqueue_due", 30, enqueue_due),
    PeriodicTask("connector_agents.liveness", 60, agents_liveness),
    PeriodicTask("connector_events.poll", 60, poll_events),
    PeriodicTask("connector_events.retention", 3600, events_retention),
]
