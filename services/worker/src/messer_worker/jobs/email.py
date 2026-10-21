"""Transactional email delivery off the request path."""

from __future__ import annotations

from typing import Any

from messer_common.email import send_template


async def send_email(
    _ctx: dict[str, Any], to: str, template: str, context: dict[str, Any], locale: str = "es"
) -> str | None:
    return await send_template(to, template, context, locale)


JOBS = [send_email]
