"""Outbound HTTP for connectors: one client factory, provider error mapping, retries and an SSRF guard.

Tests (and demo mode) swap the network for an ``httpx`` transport: :func:`set_transport` installs a
process-wide override, and adapters pass ``transport=`` explicitly for demo connections.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx

from messer_common.settings import get_settings

from .base import ConnectorAuthError, ConnectorError, ProviderError, RateLimitedError

USER_AGENT = "Messer-Connectors/1.0 (+https://messer.eu)"
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_RETRIES = 3

_transport_override: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Route every connector HTTP call through ``transport`` (tests). ``None`` restores the network."""
    global _transport_override
    _transport_override = transport


def get_transport_override() -> httpx.AsyncBaseTransport | None:
    return _transport_override


# ----------------------------------------------------------------------------- SSRF guard


def private_networks_allowed() -> bool:
    settings = get_settings()
    return settings.messer_connectors_allow_private_networks or settings.messer_env in ("local", "test")


def is_private_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def check_public_host(host: str, *, allow_private: bool) -> None:
    """Refuse hosts that resolve to private, loopback or link-local addresses (cloud metadata, internal APIs).

    Customers reach private networks through the on-prem connector agent instead.
    """
    if allow_private:
        return
    host = host.strip("[]")
    if not host:
        raise ConnectorError("La URL no tiene host", code="invalid_url")
    if host.lower() in ("localhost", "metadata.google.internal") or host.lower().endswith(".localhost"):
        raise ConnectorError(
            "No se permiten destinos de red privados. Usa el agente on-premise para redes internas.",
            code="private_network",
        )
    try:
        addresses = [host] if _is_ip(host) else _resolve(host)
    except OSError as exc:
        raise ConnectorError(f"No se puede resolver el host {host}", code="dns_error") from exc
    for address in addresses:
        if is_private_address(address):
            raise ConnectorError(
                "No se permiten destinos de red privados. Usa el agente on-premise para redes internas.",
                code="private_network",
                details={"host": host},
            )


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})


async def ensure_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ConnectorError("Solo se admiten URLs http(s)", code="invalid_url")
    if _transport_override is not None:
        return
    await asyncio.to_thread(check_public_host, parts.hostname or "", allow_private=private_networks_allowed())


# ----------------------------------------------------------------------------- client


@asynccontextmanager
async def client(
    *,
    base_url: str = "",
    headers: Mapping[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    request_timeout: httpx.Timeout | float | None = None,
    guard_url: str | None = None,
    follow_redirects: bool = True,
) -> AsyncIterator[httpx.AsyncClient]:
    """Async client for provider APIs. ``guard_url`` runs the SSRF guard on user-supplied URLs."""
    if guard_url is not None and transport is None:
        await ensure_public_url(guard_url)
    effective = transport or _transport_override
    all_headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=all_headers,
        transport=effective,
        timeout=request_timeout if request_timeout is not None else DEFAULT_TIMEOUT,
        follow_redirects=follow_redirects and guard_url is None,
    ) as c:
        yield c


def _provider_message(res: httpx.Response) -> str:
    try:
        data = res.json()
    except ValueError:
        text = res.text.strip()
        return text[:300] if text else res.reason_phrase
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)[:300]
        if isinstance(err, str):
            return str(data.get("error_description") or err)[:300]
        for key in ("message", "error_description", "detail", "errorMessage"):
            if data.get(key):
                return str(data[key])[:300]
    if isinstance(data, list) and data and isinstance(data[0], dict):
        first = data[0]
        return str(first.get("message") or first.get("errorCode") or first)[:300]
    return res.reason_phrase


def raise_for_provider(res: httpx.Response, provider: str) -> None:
    if res.status_code < 400:
        return
    message = _provider_message(res)
    if res.status_code == 401:
        raise ConnectorAuthError(
            f"{provider} ha rechazado las credenciales ({message}). Vuelve a conectar la cuenta.",
            details={"status": res.status_code},
        )
    if res.status_code == 403:
        raise ProviderError(
            f"{provider} deniega el acceso: {message}", code="provider_forbidden", details={"status": 403}
        )
    if res.status_code == 404:
        raise ProviderError(f"{provider}: recurso no encontrado ({message})", code="provider_not_found")
    if res.status_code == 429:
        raise RateLimitedError(f"{provider} limita las peticiones; inténtalo más tarde", details={"status": 429})
    raise ProviderError(f"{provider} respondió {res.status_code}: {message}", details={"status": res.status_code})


def _retry_delay(res: httpx.Response | None, attempt: int) -> float:
    if res is not None:
        raw = res.headers.get("retry-after")
        if raw:
            try:
                return min(float(raw), 30.0)
            except ValueError:
                pass
    return min(0.5 * (2**attempt), 8.0)


async def request(
    c: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    retries: int = MAX_RETRIES,
    **kwargs: Any,
) -> httpx.Response:
    """Send a request, retrying 429/5xx (idempotent methods only) and mapping errors to connector errors."""
    idempotent = method.upper() in ("GET", "HEAD", "OPTIONS", "PUT", "DELETE")
    last: httpx.Response | None = None
    for attempt in range(retries + 1):
        try:
            res = await c.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            if idempotent and attempt < retries:
                await asyncio.sleep(_retry_delay(None, attempt))
                continue
            raise ProviderError(f"{provider} no ha respondido a tiempo", code="provider_timeout") from exc
        except httpx.HTTPError as exc:
            if idempotent and attempt < retries:
                await asyncio.sleep(_retry_delay(None, attempt))
                continue
            raise ProviderError(f"No se puede conectar con {provider}: {exc}", code="provider_unreachable") from exc
        last = res
        retryable = res.status_code == 429 or (res.status_code >= 500 and idempotent)
        if retryable and attempt < retries:
            await asyncio.sleep(_retry_delay(res, attempt))
            continue
        raise_for_provider(res, provider)
        return res
    assert last is not None
    raise_for_provider(last, provider)
    return last


async def get_json(c: httpx.AsyncClient, url: str, *, provider: str, **kwargs: Any) -> Any:
    res = await request(c, "GET", url, provider=provider, **kwargs)
    return res.json() if res.content else {}


async def send_json(c: httpx.AsyncClient, method: str, url: str, *, provider: str, **kwargs: Any) -> Any:
    res = await request(c, method, url, provider=provider, **kwargs)
    if not res.content:
        return {}
    try:
        return res.json()
    except ValueError:
        return {"text": res.text}
