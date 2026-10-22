"""Outbound HTTP for channel providers (one place to inject a mock transport in tests)."""

from __future__ import annotations

from typing import Any

import httpx

from .base import SendError

# Test hook: route every provider call through a custom transport (e.g. ``httpx.MockTransport``).
transport: httpx.AsyncBaseTransport | None = None

USER_AGENT = "Messer-Channels/1.0"


def client(timeout: float = 15.0, **kwargs: Any) -> httpx.AsyncClient:
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10), transport=transport, headers=headers, **kwargs)


def raise_for_send(res: httpx.Response, provider: str, detail: str | None = None) -> None:
    """Map provider HTTP failures to :class:`SendError` (retryable on 429/5xx, auth on 401/403)."""
    if res.status_code < 400:
        return
    message = detail or _short_body(res)
    if res.status_code in (401, 403):
        raise SendError(
            f"{provider} rechazó las credenciales del canal ({res.status_code}): {message}",
            code="auth_failed",
            auth=True,
        )
    if res.status_code == 429 or res.status_code >= 500:
        raise SendError(
            f"{provider} no está disponible ({res.status_code}): {message}", code="provider_unavailable", retryable=True
        )
    raise SendError(f"{provider} rechazó el mensaje ({res.status_code}): {message}", code="rejected")


def _short_body(res: httpx.Response) -> str:
    try:
        return res.text[:300]
    except UnicodeDecodeError:
        return "<binary>"


async def request(method: str, url: str, *, provider: str, timeout_s: float = 15.0, **kwargs: Any) -> httpx.Response:
    """One provider call; network failures become retryable :class:`SendError`."""
    try:
        async with client(timeout_s) as c:
            return await c.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise SendError(
            f"No se pudo contactar con {provider}: {type(exc).__name__}", code="provider_unreachable", retryable=True
        ) from exc
