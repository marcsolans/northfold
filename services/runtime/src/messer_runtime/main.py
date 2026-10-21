"""Messer runtime (data plane): sandboxes, model gateway, tracing backend and run orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from messer_common.db import dispose_engines
from messer_common.logging import configure_logging, get_logger
from messer_common.settings import get_settings

from .internal import router as internal_router
from .runs import RunExecutor
from .sandbox.manager import SandboxPool

log = get_logger("messer.runtime")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    pool = SandboxPool(internal_base_url=settings.messer_runtime_url)
    app.state.pool = pool
    app.state.executor = RunExecutor(pool)
    pool.start_reaper()
    log.info("runtime.started", pending_keys=settings.pending_keys())
    try:
        yield
    finally:
        await pool.shutdown()
        await dispose_engines()


def create_app() -> FastAPI:
    configure_logging("runtime")
    app = FastAPI(title="Messer runtime", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(internal_router)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "sandboxes": len(app.state.pool.stats())})

    return app


app = create_app()
