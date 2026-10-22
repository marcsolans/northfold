"""Analytics filters, run status groups and time buckets (time-zone aware)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import ColumnElement

from ..db.models import Run

Bucket = Literal["hour", "day", "week"]
BUCKETS: tuple[Bucket, ...] = ("hour", "day", "week")

# Statuses that count as a failure in rates and alarms; "terminal" runs are the denominator of the rates.
FAILED_STATUSES: tuple[str, ...] = ("error", "timeout", "budget_exceeded", "blocked")
TERMINAL_STATUSES: tuple[str, ...] = ("success", "cancelled", *FAILED_STATUSES)

MAX_RANGE_DAYS = 400
MAX_POINTS = 2000
DEFAULT_RANGE_DAYS = 30


class AnalyticsError(ValueError):
    """Invalid analytics request (bad time zone, range or bucket). The API answers 422."""

    def __init__(self, message: str, *, code: str = "invalid_analytics_query") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AnalyticsError(f"Zona horaria desconocida: {tz}", code="invalid_timezone") from exc


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Filters:
    """What to aggregate: one organization's runs started in ``[since, until)`` plus optional scopes."""

    org_id: uuid.UUID
    since: datetime
    until: datetime
    project_id: uuid.UUID | None = None
    environment: str | None = None
    channel: str | None = None
    workforce_name: str | None = None

    @classmethod
    def build(
        cls,
        org_id: uuid.UUID,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        project_id: uuid.UUID | None = None,
        environment: str | None = None,
        channel: str | None = None,
        workforce_name: str | None = None,
        now: datetime | None = None,
    ) -> Filters:
        end = _aware(until) if until is not None else (now or datetime.now(UTC))
        start = _aware(since) if since is not None else end - timedelta(days=DEFAULT_RANGE_DAYS)
        if start >= end:
            raise AnalyticsError("El inicio del periodo debe ser anterior al final", code="invalid_range")
        if end - start > timedelta(days=MAX_RANGE_DAYS):
            raise AnalyticsError(f"El periodo máximo es de {MAX_RANGE_DAYS} días", code="range_too_long")
        return cls(
            org_id=org_id,
            since=start,
            until=end,
            project_id=project_id,
            environment=environment or None,
            channel=channel or None,
            workforce_name=workforce_name or None,
        )

    @property
    def has_run_scope(self) -> bool:
        return any(v is not None for v in (self.project_id, self.environment, self.channel, self.workforce_name))

    def previous(self) -> Filters:
        """The window of the same length right before this one (for period-over-period deltas)."""
        length = self.until - self.since
        return replace(self, since=self.since - length, until=self.since)

    def scope_conditions(self) -> list[ColumnElement[bool]]:
        """Organization and scope filters on ``runs`` without the time window."""
        conds: list[ColumnElement[bool]] = [Run.org_id == self.org_id]
        if self.project_id is not None:
            conds.append(Run.project_id == self.project_id)
        if self.environment is not None:
            conds.append(Run.environment == self.environment)
        if self.channel is not None:
            conds.append(Run.channel == self.channel)
        if self.workforce_name is not None:
            conds.append(Run.workforce_name == self.workforce_name)
        return conds

    def run_conditions(self) -> list[ColumnElement[bool]]:
        return [*self.scope_conditions(), Run.started_at >= self.since, Run.started_at < self.until]


def auto_bucket(since: datetime, until: datetime) -> Bucket:
    span = until - since
    if span <= timedelta(days=3):
        return "hour"
    if span <= timedelta(days=180):
        return "day"
    return "week"


def bucket_starts(since: datetime, until: datetime, bucket: Bucket, tz: str) -> list[datetime]:
    """Local (naive) bucket starts covering ``[since, until)`` — the same values ``date_trunc`` returns in SQL."""
    z = zone(tz)
    start = _aware(since).astimezone(z).replace(tzinfo=None)
    end = _aware(until).astimezone(z).replace(tzinfo=None)
    if bucket == "hour":
        cur, step = start.replace(minute=0, second=0, microsecond=0), timedelta(hours=1)
    elif bucket == "day":
        cur, step = start.replace(hour=0, minute=0, second=0, microsecond=0), timedelta(days=1)
    else:
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        cur, step = day - timedelta(days=day.weekday()), timedelta(days=7)
    out: list[datetime] = []
    while cur < end:
        out.append(cur)
        if len(out) > MAX_POINTS:
            raise AnalyticsError(
                "Demasiados puntos para este periodo: elige una agrupación mayor", code="too_many_points"
            )
        cur += step
    return out


def localize(local: datetime, tz: str) -> datetime:
    """Attach the time zone to a naive local bucket start returned by SQL."""
    return local.replace(tzinfo=zone(tz)) if local.tzinfo is None else local
