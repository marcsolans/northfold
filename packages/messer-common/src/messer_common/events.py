"""Real-time fan-out over Redis pub/sub, consumed by SSE endpoints.

Channels: ``org:<org_id>`` (notifications), ``kb:<kb_id>`` (ingestion status),
``composer:<session_id>`` (builder progress), ``run:<run_id>`` (live run events),
``workflow:<run_id>`` (node status). Messages are JSON objects with a ``type`` key.
Recent messages are also kept in a capped Redis list so late subscribers can replay.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from .settings import get_settings

_redis: aioredis.Redis | None = None
REPLAY_LIMIT = 500


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def publish(channel: str, message: dict[str, Any], *, replay: bool = True, ttl_s: int = 3600) -> None:
    r = get_redis()
    data = json.dumps(message, default=str)
    if replay:
        key = f"replay:{channel}"
        pipe = r.pipeline()
        pipe.rpush(key, data)
        pipe.ltrim(key, -REPLAY_LIMIT, -1)
        pipe.expire(key, ttl_s)
        await pipe.execute()
    await r.publish(channel, data)


async def replay(channel: str) -> list[dict[str, Any]]:
    items: list[str] = await get_redis().lrange(f"replay:{channel}", 0, -1)  # type: ignore[misc]
    return [json.loads(i) for i in items]


async def subscribe(channel: str, *, with_replay: bool = True) -> AsyncIterator[dict[str, Any]]:
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)
    try:
        if with_replay:
            for item in await replay(channel):
                yield item
        async for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            yield json.loads(raw["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
