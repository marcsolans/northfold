"""Service health task: HTTP/heartbeat checks, persistence in service_health and alert emails on transitions."""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx
import pytest

from messer_common.db import system_session
from messer_common.db.models import ServiceHealth
from messer_common.email import ConsoleEmailAdapter
from messer_common.events import get_redis
from messer_common.settings import get_settings
from messer_scheduler.core import discover_tasks
from messer_scheduler.tasks import health

Handler = Callable[[httpx.Request], httpx.Response]


def _transport(statuses: dict[str, int | Exception | dict[str, object]]) -> httpx.MockTransport:
    """Map service base URL → HTTP status, exception, or JSON body (200)."""
    targets = health.http_targets(get_settings())
    by_url = {url: statuses.get(service, 200) for service, url in targets.items()}

    def handler(request: httpx.Request) -> httpx.Response:
        outcome = by_url.get(str(request.url), 404)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict):
            return httpx.Response(200, json=outcome)
        return httpx.Response(outcome, json={"status": "ok"})

    return httpx.MockTransport(handler)


async def _rows() -> dict[str, ServiceHealth]:
    from sqlalchemy import select

    async with system_session() as s:
        return {r.service: r for r in (await s.execute(select(ServiceHealth))).scalars()}


@pytest.fixture(autouse=True)
def _clear_outbox() -> None:
    ConsoleEmailAdapter.sent.clear()


def _alerts() -> list[str]:
    return [e.subject for e in ConsoleEmailAdapter.sent if {"service_down", "service_recovered"} & set(e.tags)]


async def test_task_is_registered_every_minute() -> None:
    task = next(t for t in discover_tasks() if t.name == "service_health")
    assert task.interval_s == 60


async def test_all_services_operational() -> None:
    await get_redis().set(health.HEARTBEAT_KEY, str(time.time()), ex=90)
    results = await health.check_all(_transport({}), retry_delay_s=0)
    assert [r.service for r in results] == ["web", "api", "runtime", "worker", "scheduler", "voice", "mcp"]
    assert {r.status for r in results} == {"operational"}
    rows = await _rows()
    assert set(rows) == {"web", "api", "runtime", "worker", "scheduler", "voice", "mcp"}
    assert rows["api"].history[-1]["checks"] == 1
    assert rows["api"].history[-1]["operational"] == 1
    # Healthy first checks do not page anyone.
    assert _alerts() == []


async def test_transitions_send_down_and_recovered_emails() -> None:
    await get_redis().set(health.HEARTBEAT_KEY, str(time.time()), ex=90)
    await health.check_all(_transport({}), retry_delay_s=0)

    results = await health.check_all(
        _transport({"runtime": 503, "voice": httpx.ConnectError("refused"), "mcp": {"status": "degraded"}}),
        retry_delay_s=0,
    )
    by_service = {r.service: r for r in results}
    assert by_service["runtime"].status == "down" and by_service["runtime"].detail == "HTTP 503"
    assert by_service["voice"].status == "down" and "ConnectError" in (by_service["voice"].detail or "")
    assert by_service["mcp"].status == "degraded"
    alerts = _alerts()
    assert sorted(alerts) == sorted(
        ["Servicio degradado: Runtime", "Servicio degradado: Voz", "Servicio degradado: Servidor MCP"]
    )
    assert all(e.to == get_settings().ops_email for e in ConsoleEmailAdapter.sent)
    down_email = next(e for e in ConsoleEmailAdapter.sent if "Runtime" in e.subject)
    assert "HTTP 503" in down_email.text and "/status" in down_email.text

    # Still down: no repeated alert.
    ConsoleEmailAdapter.sent.clear()
    await health.check_all(
        _transport({"runtime": 503, "voice": httpx.ConnectError("refused"), "mcp": {"status": "degraded"}}),
        retry_delay_s=0,
    )
    assert _alerts() == []

    # Recovery.
    await health.check_all(_transport({}), retry_delay_s=0)
    assert sorted(_alerts()) == sorted(
        ["Servicio recuperado: Runtime", "Servicio recuperado: Voz", "Servicio recuperado: Servidor MCP"]
    )
    rows = await _rows()
    today = rows["runtime"].history[-1]
    assert (today["checks"], today["operational"], today["down"]) == (4, 2, 2)
    assert [e["status"] for e in today["events"]] == ["operational", "down", "operational"]


async def test_single_failure_is_retried_before_counting() -> None:
    await get_redis().set(health.HEARTBEAT_KEY, str(time.time()), ex=90)
    calls = {"n": 0}
    api_url = health.http_targets(get_settings())["api"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == api_url:
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json={"status": "ok"})

    results = await health.check_all(httpx.MockTransport(handler), retry_delay_s=0)
    assert calls["n"] == 2
    assert next(r for r in results if r.service == "api").status == "operational"


async def test_worker_heartbeat_missing_or_stale_is_down() -> None:
    redis = get_redis()
    await redis.delete(health.HEARTBEAT_KEY)
    missing = await health.check_worker()
    assert (missing.status, missing.detail) == ("down", "no heartbeat")

    await redis.set(health.HEARTBEAT_KEY, str(time.time() - 600))
    stale = await health.check_worker()
    assert stale.status == "down" and "ago" in (stale.detail or "")

    await redis.set(health.HEARTBEAT_KEY, str(int(time.time() * 1000)))  # milliseconds are accepted
    assert (await health.check_worker()).status == "operational"

    await redis.set(health.HEARTBEAT_KEY, "2999-01-01T00:00:00+00:00")
    assert (await health.check_worker()).status == "operational"


async def test_slow_or_degraded_responses() -> None:
    ok = httpx.Response(200, json={"status": "ok"})
    assert health._classify(ok, 3000) == ("degraded", "slow response: 3000 ms")
    assert health._classify(ok, 50) == ("operational", None)
    degraded = httpx.Response(
        200, json={"status": "degraded", "dependencies": {"database": {"ok": False}, "redis": {"ok": True}}}
    )
    assert health._classify(degraded, 50) == ("degraded", "reported status=degraded (database)")
    assert health._classify(httpx.Response(200, text="OK"), 10) == ("operational", None)
    assert health._classify(httpx.Response(500, text="boom"), 10) == ("down", "HTTP 500")


def test_should_notify() -> None:
    assert health.should_notify(None, "operational") is False
    assert health.should_notify(None, "down") is True
    assert health.should_notify("operational", "operational") is False
    assert health.should_notify("operational", "degraded") is True
    assert health.should_notify("degraded", "down") is True
    assert health.should_notify("down", "operational") is True
