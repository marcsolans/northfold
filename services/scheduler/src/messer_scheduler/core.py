"""Periodic task runner with Redis leader election (only one scheduler instance acts at a time)."""

from __future__ import annotations

import asyncio
import importlib
import pkgutil
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from messer_common.events import get_redis
from messer_common.logging import get_logger

log = get_logger("messer.scheduler")

LEADER_KEY = "messer:scheduler:leader"
LEADER_TTL_S = 30


@dataclass(slots=True)
class PeriodicTask:
    name: str
    interval_s: float
    fn: Callable[[], Awaitable[None]]
    last_run: float = field(default=0.0)


def discover_tasks() -> list[PeriodicTask]:
    from . import tasks as tasks_pkg

    found: list[PeriodicTask] = []
    for info in sorted(pkgutil.iter_modules(tasks_pkg.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{tasks_pkg.__name__}.{info.name}")
        found.extend(getattr(module, "TASKS", []))
    return found


async def acquire_leadership(identity: str) -> bool:
    r = get_redis()
    if await r.set(LEADER_KEY, identity, nx=True, ex=LEADER_TTL_S):
        return True
    current = await r.get(LEADER_KEY)
    if current == identity:
        await r.expire(LEADER_KEY, LEADER_TTL_S)
        return True
    return False


async def run_due(tasks: list[PeriodicTask], now: float) -> None:
    due = [t for t in tasks if now - t.last_run >= t.interval_s]
    for task in due:
        task.last_run = now
    results = await asyncio.gather(*(t.fn() for t in due), return_exceptions=True)
    for task, result in zip(due, results, strict=True):
        if isinstance(result, BaseException):
            log.error("scheduler.task_failed", task=task.name, error=repr(result))


async def run_forever(tick_s: float = 5.0) -> None:
    identity = f"{socket.gethostname()}:{id(asyncio.get_running_loop())}"
    tasks = discover_tasks()
    log.info("scheduler.start", tasks=[t.name for t in tasks])
    while True:
        try:
            if await acquire_leadership(identity):
                await run_due(tasks, time.monotonic())
        except Exception as exc:
            log.error("scheduler.loop_error", error=repr(exc))
        await asyncio.sleep(tick_s)
