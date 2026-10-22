"""Demo mode: realistic fixture data served by in-process fake provider APIs.

When a provider's OAuth app is not configured, "Conectar" creates a demo connection. Adapters then run
their normal code path against an :class:`httpx.MockTransport` that emulates the provider's REST API
from the fixtures in ``demo/data`` and ``demo/files``. Writes (send an email, create a contact…) are
accepted and answered like the real API without leaving the process.

Time-based fixtures are relative to the connection's ``config.demo_epoch``: history items have negative
offsets, and an "incoming" pool produces a new item every ``INCOMING_PERIOD_MIN`` minutes after the
epoch so that event triggers (new email, new contact, new file…) fire during a demo.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from ..base import ConnectionContext

DATA_DIR = Path(__file__).parent / "data"
FILES_DIR = Path(__file__).parent / "files"
INCOMING_FIRST_MIN = 3
INCOMING_PERIOD_MIN = 120
INCOMING_MAX = 500


@lru_cache(maxsize=32)
def fixture(name: str) -> Any:
    return json.loads((DATA_DIR / f"{name}.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=64)
def file_bytes(name: str) -> bytes:
    path = (FILES_DIR / name).resolve()
    if FILES_DIR.resolve() not in path.parents:
        raise FileNotFoundError(name)
    return path.read_bytes()


def demo_epoch(ctx: ConnectionContext) -> datetime:
    raw = ctx.config.get("demo_epoch")
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            pass
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass(slots=True)
class DemoClock:
    epoch: datetime
    now: datetime

    def at(self, offset_min: float) -> datetime:
        return self.epoch + timedelta(minutes=offset_min)

    def incoming(self, pool: list[dict[str, Any]]) -> list[tuple[int, datetime, dict[str, Any]]]:
        """Items of the incoming pool that have "arrived" by now: (sequence, arrival time, template)."""
        if not pool:
            return []
        out: list[tuple[int, datetime, dict[str, Any]]] = []
        for k in range(INCOMING_MAX):
            when = self.at(INCOMING_FIRST_MIN + k * INCOMING_PERIOD_MIN)
            if when > self.now:
                break
            out.append((k, when, pool[k % len(pool)]))
        return out


def clock_for(ctx: ConnectionContext) -> DemoClock:
    return DemoClock(epoch=demo_epoch(ctx), now=datetime.now(UTC))


def iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def json_response(data: Any, status: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=data, headers=headers)


def error_response(status: int, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": status, "message": message}})


def new_id(prefix: str = "demo") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def request_json(request: httpx.Request) -> dict[str, Any]:
    if not request.content:
        return {}
    try:
        data = json.loads(request.content)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


Handler = Callable[[httpx.Request, DemoClock, ConnectionContext], httpx.Response]


def transport(handler: Handler, ctx: ConnectionContext) -> httpx.MockTransport:
    clock = clock_for(ctx)

    def handle(request: httpx.Request) -> httpx.Response:
        try:
            return handler(request, clock, ctx)
        except KeyError as exc:
            return error_response(404, f"Recurso de demostración no encontrado: {exc}")

    return httpx.MockTransport(handle)


def route(path: str, pattern: str) -> re.Match[str] | None:
    return re.fullmatch(pattern, path)


def words_match(query: str, *texts: str | None) -> bool:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
    if not terms:
        return True
    haystack = " ".join(t or "" for t in texts).lower()
    return all(term in haystack for term in terms)
