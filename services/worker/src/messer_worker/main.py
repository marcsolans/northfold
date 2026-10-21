"""arq worker entry point: ``python -m messer_worker``."""

from __future__ import annotations

import time
from typing import Any

from arq import cron, run_worker
from arq.worker import Worker

from messer_common.db import dispose_engines
from messer_common.events import close_redis, get_redis
from messer_common.logging import configure_logging, get_logger
from messer_common.queue import QUEUE_NAME, close_queue, redis_settings

from .registry import discover_jobs

log = get_logger("messer.worker")

HEARTBEAT_KEY = "messer:heartbeat:worker"  # read by the scheduler's health check and the status page


async def heartbeat(_ctx: dict[str, Any]) -> None:
    await get_redis().set(HEARTBEAT_KEY, int(time.time()), ex=120)


async def startup(ctx: dict[str, Any]) -> None:
    await heartbeat(ctx)
    log.info("worker.startup", jobs=len(WorkerSettings.functions))


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_queue()
    await close_redis()
    await dispose_engines()


class WorkerSettings:
    functions = discover_jobs()
    queue_name = QUEUE_NAME
    redis_settings = redis_settings()
    cron_jobs = [cron(heartbeat, second={0, 30})]  # type: ignore[arg-type]
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
    job_timeout = 60 * 30
    keep_result = 3600
    allow_abort_jobs = True


def main() -> Worker:
    configure_logging("worker")
    return run_worker(WorkerSettings)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
