"""Service health history (``service_health``) and the public status summary.

The scheduler (``messer_scheduler.tasks.health``) records one check per service every minute with
:func:`record_check`. Each row keeps its current status plus ``history``: one bucket per UTC day for the
last 90 days with check counts per status and the status transitions of that day::

    {"date": "2026-10-21", "checks": 1440, "operational": 1438, "degraded": 0, "down": 2,
     "events": [{"at": "2026-10-21T08:14:03+00:00", "status": "down"}, ...]}

:func:`public_summary` turns those rows into the payload of ``GET /api/v1/status/public``. It never exposes
the internal ``detail`` text (hostnames, exception messages): only statuses, latencies and times.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import ServiceHealth

CheckStatus = Literal["operational", "degraded", "down"]
PublicStatus = Literal["operational", "degraded", "down", "unknown"]
DayStatus = Literal["operational", "degraded", "down", "no_data"]

# Display order on the status page.
SERVICES: tuple[str, ...] = ("web", "api", "runtime", "worker", "scheduler", "voice", "mcp")
CHECK_STATUSES: tuple[CheckStatus, ...] = ("operational", "degraded", "down")
HISTORY_DAYS = 90
# A service whose last check is older than this is shown as "unknown" (the checker itself may be down).
STALE_AFTER = timedelta(minutes=5)
# Share of failed checks in a day from which the day bar is red instead of amber (~30 minutes).
DOWN_DAY_RATIO = 0.02
MAX_EVENTS_PER_DAY = 50
MAX_INCIDENTS = 20

_SEVERITY: dict[str, int] = {"operational": 0, "unknown": 1, "degraded": 2, "down": 3}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _prune(history: list[Any], today: date) -> list[dict[str, Any]]:
    """Keep well-formed buckets of the last HISTORY_DAYS days, oldest first."""
    oldest = today - timedelta(days=HISTORY_DAYS - 1)
    kept: dict[str, dict[str, Any]] = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        raw_day = cast(dict[str, Any], item).get("date")
        try:
            day = date.fromisoformat(str(raw_day))
        except ValueError:
            continue
        if oldest <= day <= today:
            kept[day.isoformat()] = dict(cast(dict[str, Any], item))
    return [kept[k] for k in sorted(kept)]


async def record_check(
    session: AsyncSession,
    *,
    service: str,
    status: CheckStatus,
    latency_ms: int | None,
    detail: str | None,
    now: datetime | None = None,
) -> str | None:
    """Store one check result for ``service``. Returns the previous status (``None`` on the first check)."""
    if status not in CHECK_STATUSES:
        raise ValueError(f"invalid health status {status!r}")
    now = _utc(now or datetime.now(UTC))
    today = now.date()
    row = await session.get(ServiceHealth, service, with_for_update=True)
    previous = row.status if row is not None else None
    history = _prune(list(row.history or []) if row is not None else [], today)
    bucket = next((b for b in history if b.get("date") == today.isoformat()), None)
    if bucket is None:
        bucket = {"date": today.isoformat(), "checks": 0, "operational": 0, "degraded": 0, "down": 0, "events": []}
        history.append(bucket)
    bucket["checks"] = _as_int(bucket.get("checks")) + 1
    bucket[status] = _as_int(bucket.get(status)) + 1
    if previous != status:
        events = [e for e in bucket.get("events") or [] if isinstance(e, dict)]
        events.append({"at": now.isoformat(), "status": status})
        bucket["events"] = events[-MAX_EVENTS_PER_DAY:]
    trimmed_detail = detail[:1000] if detail else None
    if row is None:
        session.add(
            ServiceHealth(
                service=service,
                status=status,
                latency_ms=latency_ms,
                detail=trimmed_detail,
                checked_at=now,
                history=history,
            )
        )
    else:
        row.status = status
        row.latency_ms = latency_ms
        row.detail = trimmed_detail
        row.checked_at = now
        row.history = history
    await session.flush()
    return previous


def _day_summary(bucket: dict[str, Any] | None, day: date) -> dict[str, Any]:
    checks = _as_int(bucket.get("checks")) if bucket else 0
    if not bucket or checks <= 0:
        return {"date": day.isoformat(), "status": "no_data", "uptime": None}
    down = _as_int(bucket.get("down"))
    degraded = _as_int(bucket.get("degraded"))
    status: DayStatus
    if down / checks >= DOWN_DAY_RATIO:
        status = "down"
    elif down or degraded:
        status = "degraded"
    else:
        status = "operational"
    uptime = round((checks - down) / checks * 100, 3)
    return {"date": day.isoformat(), "status": status, "uptime": uptime}


def _incidents(service: str, history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pair status transitions into incidents: first non-operational event → next operational event."""
    events: list[tuple[str, str]] = []
    for bucket in history:
        for event in bucket.get("events") or []:
            if isinstance(event, dict) and event.get("at") and event.get("status") in CHECK_STATUSES:
                events.append((str(event["at"]), str(event["status"])))
    events.sort()
    incidents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for at, status in events:
        if status == "operational":
            if current is not None:
                current["resolved_at"] = at
                incidents.append(current)
                current = None
            continue
        if current is None:
            current = {"service": service, "status": status, "started_at": at, "resolved_at": None}
        elif _SEVERITY[status] > _SEVERITY[current["status"]]:
            current["status"] = status
    if current is not None:
        incidents.append(current)
    return incidents


async def public_summary(session: AsyncSession, *, now: datetime | None = None) -> dict[str, Any]:
    """Payload of the public status page: current state, 90 daily bars and recent incidents per service."""
    now = _utc(now or datetime.now(UTC))
    today = now.date()
    rows = {r.service: r for r in (await session.execute(select(ServiceHealth))).scalars()}
    days = [today - timedelta(days=offset) for offset in range(HISTORY_DAYS - 1, -1, -1)]
    services: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    updated_at: datetime | None = None
    for key in SERVICES:
        row = rows.get(key)
        history = _prune(list(row.history or []), today) if row is not None else []
        by_day = {str(b.get("date")): b for b in history}
        checked_at = _utc(row.checked_at) if row is not None else None
        current: PublicStatus = "unknown"
        if row is not None and checked_at is not None and now - checked_at <= STALE_AFTER:
            current = cast(PublicStatus, row.status if row.status in CHECK_STATUSES else "unknown")
        if checked_at is not None and (updated_at is None or checked_at > updated_at):
            updated_at = checked_at
        total = sum(_as_int(b.get("checks")) for b in history)
        down = sum(_as_int(b.get("down")) for b in history)
        services.append(
            {
                "key": key,
                "status": current,
                "latency_ms": row.latency_ms if row is not None and current != "unknown" else None,
                "checked_at": checked_at.isoformat() if checked_at else None,
                "uptime_90d": round((total - down) / total * 100, 3) if total else None,
                "days": [_day_summary(by_day.get(d.isoformat()), d) for d in days],
            }
        )
        incidents.extend(_incidents(key, history))
    known = [s["status"] for s in services if s["status"] != "unknown"]
    overall: PublicStatus = max(known, key=lambda s: _SEVERITY[s]) if known else "unknown"
    if overall == "operational" and len(known) < len(services):
        # Some services have no recent data: do not claim that everything is operational.
        overall = "unknown"
    incidents.sort(key=lambda i: str(i["started_at"]), reverse=True)
    return {
        "status": overall,
        "updated_at": updated_at.isoformat() if updated_at else None,
        "generated_at": now.isoformat(),
        "history_days": HISTORY_DAYS,
        "services": services,
        "incidents": incidents[:MAX_INCIDENTS],
    }
