"""Health checks: /health (liveness + dependencies) and /api/v1/system/status (pending keys, modes)."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from messer_common.db import system_session
from messer_common.events import get_redis
from messer_common.settings import get_settings

router = APIRouter(prefix="/system", tags=["system"])
public_router = APIRouter(tags=["system"])


async def check_dependencies() -> dict[str, Any]:
    result: dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        async with system_session() as s:
            await s.execute(text("select 1"))
        result["database"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        result["database"] = {"ok": False, "error": type(exc).__name__}
    t0 = time.perf_counter()
    try:
        await get_redis().ping()
        result["redis"] = {"ok": True, "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    except Exception as exc:
        result["redis"] = {"ok": False, "error": type(exc).__name__}
    return result


@public_router.get("/health")
async def health() -> dict[str, Any]:
    deps = await check_dependencies()
    ok = all(d.get("ok") for d in deps.values())
    return {"status": "ok" if ok else "degraded", "service": "api", "dependencies": deps}


@router.get("/status")
async def status() -> dict[str, Any]:
    s = get_settings()
    return {
        "environment": s.messer_env,
        "auth_mode": "supabase" if s.has_supabase else "local",
        "models_mode": "anthropic" if s.has_anthropic else "demo",
        "billing_mode": "stripe" if s.has_stripe else "simulated",
        "bedrock_available": s.has_bedrock,
        "pending_keys": s.pending_keys(),
    }
