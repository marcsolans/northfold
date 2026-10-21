"""Fixed-window rate limiting on Redis (public endpoints, login, signup)."""

from __future__ import annotations

import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request
from redis.exceptions import RedisError

from messer_common.events import get_redis
from messer_common.logging import get_logger

from .deps import client_ip
from .errors import RateLimited

log = get_logger("messer.api.ratelimit")


async def hit(key: str, limit: int, window_s: int) -> tuple[bool, int]:
    """Count one hit; return (allowed, retry_after_seconds)."""
    bucket = int(time.time() // window_s)
    redis_key = f"rl:{key}:{bucket}"
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_s + 1)
        count, _ = await pipe.execute()
    except RedisError as exc:  # fail open: availability over strictness when Redis is down
        log.warning("ratelimit.redis_unavailable", error=str(exc))
        return True, 0
    if int(count) > limit:
        return False, window_s - int(time.time() % window_s)
    return True, 0


def rate_limit(name: str, limit: int, window_s: int = 60) -> Callable[[Request], Coroutine[Any, Any, None]]:
    async def dependency(request: Request) -> None:
        ip = client_ip(request) or "unknown"
        allowed, retry_after = await hit(f"{name}:{ip}", limit, window_s)
        if not allowed:
            raise RateLimited(
                "Demasiadas solicitudes. Inténtalo de nuevo en unos segundos.",
                details={"retry_after": retry_after},
            )

    return dependency
