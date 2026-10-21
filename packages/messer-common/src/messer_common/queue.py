"""Background job queue (arq on Redis). Job names are the contract between producers and the worker."""

from __future__ import annotations

from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from .settings import get_settings

QUEUE_NAME = "messer:queue"


class Jobs:
    INGEST_FILE = "ingest_file"
    REEMBED_CHUNK = "reembed_chunk"
    RUN_SYNC = "run_sync"
    RUN_EVALS = "run_evals"
    DEPLOY = "deploy"
    FIRE_TRIGGER = "fire_trigger"
    RESUME_RUN = "resume_run"
    COMPOSER_PLAN = "composer_plan"
    COMPOSER_BUILD = "composer_build"
    SEND_EMAIL = "send_email"
    NOTIFY_APPROVAL = "notify_approval"
    CHANNEL_INBOUND = "channel_inbound"
    DATA_EXPORT = "data_export"
    DATA_DELETE = "data_delete"
    KB_BACKUP = "kb_backup"
    KB_RESTORE = "kb_restore"
    ENTITY_RESOLUTION = "entity_resolution"
    GUARD_GENERATE = "guard_generate"
    GITHUB_PUSH = "github_push"
    GITHUB_PULL = "github_pull"


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings(), default_queue_name=QUEUE_NAME)
    return _pool


async def enqueue(
    job: str, *args: Any, _job_id: str | None = None, _defer_by: float | None = None, **kwargs: Any
) -> str | None:
    pool = await get_queue()
    result = await pool.enqueue_job(job, *args, _job_id=_job_id, _defer_by=_defer_by, _queue_name=QUEUE_NAME, **kwargs)
    return result.job_id if result else None


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
