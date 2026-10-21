"""arq worker entry point: ``python -m messer_worker``."""

from __future__ import annotations

from typing import Any

from arq import run_worker
from arq.worker import Worker

from messer_common.db import dispose_engines
from messer_common.events import close_redis
from messer_common.logging import configure_logging, get_logger
from messer_common.queue import QUEUE_NAME, close_queue, redis_settings

from .registry import discover_jobs

log = get_logger("messer.worker")


async def startup(ctx: dict[str, Any]) -> None:
    log.info("worker.startup", jobs=len(WorkerSettings.functions))


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_queue()
    await close_redis()
    await dispose_engines()


class WorkerSettings:
    functions = discover_jobs()
    queue_name = QUEUE_NAME
    redis_settings = redis_settings()
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
