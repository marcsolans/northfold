"""Base class for OAuth 2 SaaS connectors (Google, Microsoft, Slack, Notion, HubSpot, Salesforce)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import httpx

from .. import demo
from .. import http as chttp
from ..base import ConnectionContext, ConnectorAdapter, ConnectorAuthError, TestResult


class ApiSession:
    """One HTTP client per operation; refreshes the OAuth token once on a 401 and retries."""

    def __init__(self, adapter: OAuthAdapter, ctx: ConnectionContext, client: httpx.AsyncClient) -> None:
        self.adapter = adapter
        self.ctx = ctx
        self.client = client
        self._refreshed = False

    async def call(self, method: str, path: str, *, raw: bool = False, **kwargs: Any) -> Any:
        while True:
            headers = {**self.adapter.auth_headers(self.ctx), **kwargs.pop("headers", {})}
            try:
                res = await chttp.request(
                    self.client, method, path, provider=self.adapter.spec.name, headers=headers, **kwargs
                )
                self.adapter.check_response(res)
            except ConnectorAuthError:
                if not self._refreshed and await self.adapter.try_refresh(self.ctx):
                    self._refreshed = True
                    kwargs["headers"] = {k: v for k, v in headers.items() if k.lower() != "authorization"}
                    continue
                raise
            if raw:
                return res
            if not res.content:
                return {}
            try:
                return res.json()
            except ValueError:
                return {"text": res.text}

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.call("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.call("POST", path, **kwargs)


class OAuthAdapter(ConnectorAdapter):
    api_base: ClassVar[str] = ""
    demo_handler: ClassVar[Callable[..., httpx.Response] | None] = None

    def base_url(self, ctx: ConnectionContext) -> str:
        return self.api_base

    def auth_headers(self, ctx: ConnectionContext) -> dict[str, str]:
        return {"Authorization": f"Bearer {ctx.access_token}"}

    def extra_headers(self, ctx: ConnectionContext) -> dict[str, str]:
        return {}

    def check_response(self, res: httpx.Response) -> None:
        """Provider-specific error detection on 2xx responses (Slack answers ``ok: false`` with HTTP 200)."""

    def transport(self, ctx: ConnectionContext) -> httpx.AsyncBaseTransport | None:
        if ctx.demo:
            handler = type(self).demo_handler
            if handler is None:
                raise ConnectorAuthError("Este conector no tiene modo demo")
            return demo.transport(handler, ctx)
        return None

    @asynccontextmanager
    async def session(self, ctx: ConnectionContext, *, base_url: str | None = None) -> AsyncIterator[ApiSession]:
        async with chttp.client(
            base_url=base_url if base_url is not None else self.base_url(ctx),
            headers=self.extra_headers(ctx),
            transport=self.transport(ctx),
        ) as c:
            yield ApiSession(self, ctx, c)

    async def try_refresh(self, ctx: ConnectionContext) -> bool:
        if ctx.demo or not ctx.credentials.get("refresh_token") or self.spec.oauth is None:
            return False
        if not self.spec.oauth.supports_refresh:
            return False
        from ..credentials import refresh_connection

        ctx.credentials = await refresh_connection(ctx.connection_id, ctx.org_id, force=True)
        return True

    async def test(self, ctx: ConnectionContext) -> TestResult:
        info = await self.whoami(ctx)
        label = info.get("email") or info.get("name") or info.get("account") or self.spec.name
        prefix = "Modo demo: " if ctx.demo else ""
        return TestResult(ok=True, message=f"{prefix}conectado como {label}", details=info)

    async def whoami(self, ctx: ConnectionContext) -> dict[str, Any]:
        return {}
