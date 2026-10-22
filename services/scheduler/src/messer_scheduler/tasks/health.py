"""Service health checks for the public status page (every 60 s).

* HTTP services (api, runtime, voice, mcp, web): ``GET <service url>/health``. 2xx with ``status: ok`` (or no JSON)
  is operational, ``status: degraded`` or a slow answer is degraded, anything else is down. A failed check is
  retried once before it counts, so a single dropped connection does not page anyone.
* worker: the Redis heartbeat key ``messer:heartbeat:worker`` (unix timestamp, refreshed by the worker with a TTL).
* scheduler: this process is running the check, so it is operational while it holds the leader lock.

Results go to ``service_health`` (see ``messer_api.services.service_health``). Status transitions email
``MESSER_OPS_EMAIL``: ``service_down`` when a service degrades or goes down, ``service_recovered`` when it is back.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from redis.exceptions import RedisError

from messer_api.services.service_health import CheckStatus, record_check
from messer_common.db import system_session
from messer_common.email import send_template
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.settings import Settings, get_settings
from messer_scheduler.core import LEADER_KEY, PeriodicTask

log = get_logger("messer.scheduler.health")

HEARTBEAT_KEY = "messer:heartbeat:worker"
HEARTBEAT_MAX_AGE_S = 120
HTTP_TIMEOUT_S = 5.0
SLOW_MS = 2000
RETRY_DELAY_S = 1.0
INTERVAL_S = 60

SERVICE_LABELS = {
    "web": "Web",
    "api": "API",
    "runtime": "Runtime",
    "worker": "Worker",
    "scheduler": "Scheduler",
    "voice": "Voz",
    "mcp": "Servidor MCP",
}


@dataclass(slots=True)
class CheckResult:
    service: str
    status: CheckStatus
    latency_ms: int | None
    detail: str | None


def http_targets(settings: Settings) -> dict[str, str]:
    def health(base: str) -> str:
        return f"{base.rstrip('/')}/health"

    return {
        "web": health(settings.messer_web_url),
        "api": health(settings.messer_api_url),
        "runtime": health(settings.messer_runtime_url),
        "voice": health(settings.messer_voice_url),
        "mcp": health(settings.messer_mcp_url),
    }


def _classify(response: httpx.Response, latency_ms: int) -> tuple[CheckStatus, str | None]:
    if response.status_code >= 300:
        return "down", f"HTTP {response.status_code}"
    body: Any = None
    if "json" in response.headers.get("content-type", ""):
        try:
            body = response.json()
        except ValueError:
            body = None
    reported = str(body.get("status", "ok")).lower() if isinstance(body, dict) else "ok"
    if reported in ("down", "error", "fail", "failed"):
        return "down", f"reported status={reported}"
    if reported not in ("ok", "operational", "healthy", "pass"):
        failing: list[str] = []
        deps = body.get("dependencies") if isinstance(body, dict) else None
        if isinstance(deps, dict):
            failing = [str(k) for k, v in deps.items() if isinstance(v, dict) and not v.get("ok", True)]
        suffix = f" ({', '.join(failing)})" if failing else ""
        return "degraded", f"reported status={reported}{suffix}"
    if latency_ms > SLOW_MS:
        return "degraded", f"slow response: {latency_ms} ms"
    return "operational", None


async def _http_attempt(client: httpx.AsyncClient, url: str) -> tuple[CheckStatus, int | None, str | None]:
    t0 = time.perf_counter()
    try:
        response = await client.get(url, headers={"Accept": "application/json", "User-Agent": "messer-status/1"})
    except httpx.TimeoutException:
        return "down", None, f"timeout after {HTTP_TIMEOUT_S:g} s"
    except httpx.HTTPError as exc:
        return "down", None, f"{type(exc).__name__}: {exc}"[:500]
    latency_ms = int((time.perf_counter() - t0) * 1000)
    status, detail = _classify(response, latency_ms)
    return status, latency_ms, detail


async def check_http(
    client: httpx.AsyncClient, service: str, url: str, *, retry_delay_s: float = RETRY_DELAY_S
) -> CheckResult:
    status, latency_ms, detail = await _http_attempt(client, url)
    if status != "operational":
        await asyncio.sleep(retry_delay_s)
        status, latency_ms, detail = await _http_attempt(client, url)
    return CheckResult(service, status, latency_ms, detail)


def _heartbeat_age_s(raw: str, now: float) -> float | None:
    """Age of a heartbeat value: unix seconds or milliseconds, or an ISO-8601 timestamp."""
    try:
        ts = float(raw)
        if ts > 1e12:  # milliseconds
            ts /= 1000
        return now - ts
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return now - parsed.timestamp()


async def check_worker() -> CheckResult:
    t0 = time.perf_counter()
    try:
        raw = await get_redis().get(HEARTBEAT_KEY)
    except RedisError as exc:
        return CheckResult("worker", "down", None, f"redis unavailable: {type(exc).__name__}")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    if raw is None:
        return CheckResult("worker", "down", latency_ms, "no heartbeat")
    age = _heartbeat_age_s(str(raw), time.time())
    if age is not None and age > HEARTBEAT_MAX_AGE_S:
        return CheckResult("worker", "down", latency_ms, f"last heartbeat {int(age)} s ago")
    return CheckResult("worker", "operational", latency_ms, None)


async def check_scheduler() -> CheckResult:
    t0 = time.perf_counter()
    try:
        leader = await get_redis().get(LEADER_KEY)
    except RedisError as exc:
        return CheckResult("scheduler", "degraded", None, f"redis unavailable: {type(exc).__name__}")
    latency_ms = int((time.perf_counter() - t0) * 1000)
    return CheckResult("scheduler", "operational", latency_ms, f"leader {leader}" if leader else None)


async def run_checks(
    transport: httpx.AsyncBaseTransport | None = None, *, retry_delay_s: float = RETRY_DELAY_S
) -> list[CheckResult]:
    targets = http_targets(get_settings())
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S, transport=transport, follow_redirects=False) as client:
        http_results = await asyncio.gather(
            *(check_http(client, service, url, retry_delay_s=retry_delay_s) for service, url in targets.items())
        )
    worker, scheduler = await asyncio.gather(check_worker(), check_scheduler())
    by_service = {r.service: r for r in [*http_results, worker, scheduler]}
    order = ("web", "api", "runtime", "worker", "scheduler", "voice", "mcp")
    return [by_service[s] for s in order if s in by_service]


async def _notify(result: CheckResult, previous: str | None, now: datetime) -> None:
    settings = get_settings()
    label = SERVICE_LABELS.get(result.service, result.service)
    url = f"{settings.messer_web_url.rstrip('/')}/status"
    if result.status == "operational":
        context: dict[str, object] = {"service": label, "since": now.strftime("%d/%m/%Y %H:%M UTC"), "url": url}
        template = "service_recovered"
    else:
        state = "caído" if result.status == "down" else "degradado"
        detail = result.detail or state
        context = {"service": label, "detail": f"{state} — {detail}", "url": url}
        template = "service_down"
    try:
        await send_template(settings.ops_email, template, context, "es")
    except Exception as exc:  # an alert failure must never stop the checks
        log.error("health.notify_failed", service=result.service, template=template, error=str(exc))
    log.info("health.transition", service=result.service, previous=previous, status=result.status)


def should_notify(previous: str | None, current: str) -> bool:
    if previous == current:
        return False
    if previous is None:
        return current != "operational"  # first check: only alert if it starts unhealthy
    return True


async def check_all(
    transport: httpx.AsyncBaseTransport | None = None, *, retry_delay_s: float = RETRY_DELAY_S
) -> list[CheckResult]:
    """Run every check, persist the results and alert on transitions."""
    results = await run_checks(transport, retry_delay_s=retry_delay_s)
    now = datetime.now(UTC)
    transitions: list[tuple[CheckResult, str | None]] = []
    async with system_session() as s:
        for result in results:
            previous = await record_check(
                s,
                service=result.service,
                status=result.status,
                latency_ms=result.latency_ms,
                detail=result.detail,
                now=now,
            )
            if should_notify(previous, result.status):
                transitions.append((result, previous))
    for result, previous in transitions:
        await _notify(result, previous, now)
    return results


async def _task() -> None:
    await check_all()


TASKS = [PeriodicTask("service_health", INTERVAL_S, _task)]
