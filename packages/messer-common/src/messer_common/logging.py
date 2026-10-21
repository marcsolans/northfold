"""Structured logging (structlog, JSON in staging/production) and Sentry initialisation."""

from __future__ import annotations

import logging
import sys

import structlog

from .settings import get_settings

_configured = False


def configure_logging(service: str) -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    json_logs = settings.messer_env in ("staging", "production")
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(structlog.processors.JSONRenderer() if json_logs else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service)
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(message)s")
    init_sentry(service)
    _configured = True


def init_sentry(service: str) -> bool:
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.messer_env,
        server_name=service,
        traces_sample_rate=0.1 if settings.is_production else 1.0,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service)
    return True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
