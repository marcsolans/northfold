"""FastAPI application factory for the Messer platform API (control plane)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from messer_common.db import dispose_engines
from messer_common.events import close_redis
from messer_common.logging import configure_logging, get_logger
from messer_common.queue import close_queue
from messer_common.settings import get_settings

from . import routers
from .errors import ApiError, api_error_handler, http_error_handler, unhandled_error_handler, validation_error_handler

log = get_logger("messer.api")

API_PREFIX = "/api/v1"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.unbind_contextvars("request_id", "path")
        response.headers["x-request-id"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        if get_settings().is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload")
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await close_queue()
    await close_redis()
    await dispose_engines()


def create_app() -> FastAPI:
    configure_logging("api")
    settings = get_settings()
    app = FastAPI(
        title="Messer Platform API",
        version="1.0.0",
        description="API de la plataforma Messer: proyectos, agentes, flujos, conocimiento, despliegues y gobierno.",
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.messer_web_url],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Messer-Org", "X-Request-Id"],
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    for module in routers.discover():
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router, prefix=API_PREFIX)
        public = getattr(module, "public_router", None)
        if public is not None:
            app.include_router(public)
    return app


app = create_app()
