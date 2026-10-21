"""Trigger firings: run the target member through the runtime with the event payload."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from messer_common import runtime_client, triggers
from messer_common.db import system_session
from messer_common.db.models import Trigger
from messer_common.execution import NotDeployed
from messer_common.logging import get_logger
from messer_common.runtime_client import RuntimeUnavailable

log = get_logger("messer.worker.triggers")

HISTORY = 20


async def _record(trigger_id: uuid.UUID, entry: dict[str, Any]) -> None:
    async with system_session() as s:
        trigger = await s.get(Trigger, trigger_id, with_for_update=True)
        if trigger is None:
            return
        state = dict(trigger.state or {})
        history = [entry, *list(state.get("history") or [])][:HISTORY]
        failures = 0 if entry["status"] in ("success", "paused") else int(state.get("consecutive_failures") or 0) + 1
        trigger.state = {**state, "history": history, "last": entry, "consecutive_failures": failures}
        trigger.last_fired_at = datetime.now(UTC)


async def fire_trigger(_ctx: dict[str, Any], trigger_id: str, payload: dict[str, Any], event_id: str) -> dict[str, Any]:
    tid = uuid.UUID(trigger_id)
    async with system_session() as s:
        trigger = await s.get(Trigger, tid)
        if trigger is None or not trigger.enabled:
            return {"skipped": "disabled"}
        kind = trigger.kind
        try:
            request = await triggers.run_request(s, trigger, payload, event_id)
        except NotDeployed as exc:
            entry = {
                "at": datetime.now(UTC).isoformat(),
                "event_id": event_id,
                "status": "not_deployed",
                "error": str(exc),
            }
            await _record(tid, entry)
            return entry
        except LookupError as exc:
            entry = {"at": datetime.now(UTC).isoformat(), "event_id": event_id, "status": "error", "error": str(exc)}
            await _record(tid, entry)
            return entry
    try:
        result = await runtime_client.run(request)
    except RuntimeUnavailable as exc:
        log.warning("trigger.runtime_unavailable", trigger_id=trigger_id, error=str(exc))
        raise  # arq retries with backoff
    entry = {
        "at": datetime.now(UTC).isoformat(),
        "event_id": event_id,
        "status": result.get("status"),
        "run_id": result.get("run_id"),
    }
    await _record(tid, entry)
    log.info(
        "trigger.fired", trigger_id=trigger_id, kind=kind, run_id=result.get("run_id"), status=result.get("status")
    )
    return entry


JOBS = [fire_trigger]
