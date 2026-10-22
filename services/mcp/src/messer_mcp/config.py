"""Configuration of the MCP server.

* ``MESSER_MCP_URL`` (shared setting) — public URL of this server; the MCP endpoint is ``<url>/mcp``.
* ``MESSER_API_URL`` (shared setting) — public URL of the platform API, also the OAuth issuer.
* ``MESSER_MCP_API_URL`` — where this server calls the API (e.g. ``http://api:8000`` inside a private network);
  defaults to ``MESSER_API_URL``.
* ``MESSER_MCP_HOST`` / ``MESSER_MCP_PORT`` — bind address (default ``127.0.0.1:8400``).
* ``MESSER_MCP_ALLOWED_HOSTS`` — extra ``Host`` values accepted (comma-separated) besides the public URL's host
  and localhost (DNS-rebinding protection).
* ``MESSER_MCP_STATEFUL`` — ``1`` keeps MCP sessions in memory (needs sticky routing); stateless by default so the
  service scales horizontally.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from messer_common.settings import get_settings


@dataclass(slots=True)
class McpConfig:
    public_url: str
    issuer_url: str
    api_url: str
    host: str = "127.0.0.1"
    port: int = 8400
    stateless: bool = True
    extra_hosts: list[str] = field(default_factory=list)

    @property
    def resource_url(self) -> str:
        return f"{self.public_url}/mcp"

    @property
    def web_url(self) -> str:
        return get_settings().messer_web_url.rstrip("/")

    def allowed_hosts(self) -> list[str]:
        hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *self.extra_hosts]
        netloc = urlsplit(self.public_url).netloc
        if netloc and netloc not in hosts:
            hosts.append(netloc)
            if ":" not in netloc:
                hosts.append(f"{netloc}:*")
        return hosts

    def allowed_origins(self) -> list[str]:
        origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*", self.web_url]
        parts = urlsplit(self.public_url)
        if parts.scheme and parts.netloc:
            origins.append(f"{parts.scheme}://{parts.netloc}")
        return origins

    @classmethod
    def from_env(cls) -> McpConfig:
        settings = get_settings()
        env = os.environ
        return cls(
            public_url=settings.messer_mcp_url.rstrip("/"),
            issuer_url=settings.messer_api_url.rstrip("/"),
            api_url=(env.get("MESSER_MCP_API_URL") or settings.messer_api_url).rstrip("/"),
            host=env.get("MESSER_MCP_HOST", "127.0.0.1"),
            port=int(env.get("MESSER_MCP_PORT", "8400") or 8400),
            stateless=env.get("MESSER_MCP_STATEFUL", "").strip().lower() not in ("1", "true", "yes", "on"),
            extra_hosts=[h.strip() for h in env.get("MESSER_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()],
        )
