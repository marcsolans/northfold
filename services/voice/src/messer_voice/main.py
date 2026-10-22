"""Messer voice gateway (FastAPI): browser WebSocket sessions, phone calls (Twilio, Telnyx), LiveKit rooms."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from messer_common.db import dispose_engines
from messer_common.events import close_redis
from messer_common.logging import configure_logging, get_logger
from messer_common.settings import get_settings

from . import browser, internal, livekit, transcribe
from .runner import ACTIVE
from .status import voice_status
from .telephony import telnyx, twilio

log = get_logger("messer.voice")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    status = voice_status()
    log.info("voice.started", audio=status["audio"]["available"], telephony=status["telephony"])
    try:
        yield
    finally:
        for bundle in list(ACTIVE.values()):
            await bundle.session.close()
        await livekit.shutdown()
        await close_redis()
        await dispose_engines()


def create_app() -> FastAPI:
    configure_logging("voice")
    app = FastAPI(title="Messer voice", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.include_router(browser.router)
    app.include_router(transcribe.router)
    app.include_router(twilio.router)
    app.include_router(telnyx.router)
    app.include_router(internal.router)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "sessions": len(ACTIVE), "env": get_settings().messer_env})

    return app


app = create_app()
