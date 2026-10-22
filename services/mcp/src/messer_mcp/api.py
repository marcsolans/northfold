"""Platform API client used by the MCP tools: every call carries the MCP caller's own bearer token, so the API
enforces roles, scopes, project-scoped keys and RLS exactly as for any other client."""

from __future__ import annotations

from typing import Any

import httpx

# Test hook: an ASGI/mock transport for the platform API.
transport: httpx.AsyncBaseTransport | None = None
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


class MesserApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        extra = f" {self.details}" if self.details else ""
        return f"Messer API {self.status} ({self.code}): {self.message}{extra}"


def _error(res: httpx.Response) -> MesserApiError:
    code, message, details = "http_error", res.reason_phrase or "Error", {}
    try:
        body = res.json()
    except ValueError:
        body = None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        err = body["error"]
        code = str(err.get("code") or code)
        message = str(err.get("message") or message)
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
    elif res.text:
        message = res.text[:500]
    return MesserApiError(res.status_code, code, message, details)


class ApiClient:
    def __init__(self, base_url: str, token: str, *, request_id: str | None = None) -> None:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": "messer-mcp/1.0"}
        if request_id:
            headers["X-Request-Id"] = request_id
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=TIMEOUT, transport=transport
        )

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        /,
        *,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("/v1/") or path.startswith("/api/") else f"/api/v1{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        res = await self._client.request(method, url, json=json, params=clean or None)
        if res.status_code >= 400:
            raise _error(res)
        if res.status_code == 204 or not res.content:
            return None
        if "application/json" in res.headers.get("content-type", ""):
            return res.json()
        return res.text

    async def get(self, path: str, /, **params: Any) -> Any:
        return await self.request("GET", path, params=params)

    async def post(self, path: str, body: Any = None, /) -> Any:
        return await self.request("POST", path, json=body if body is not None else {})

    async def put(self, path: str, body: Any, /) -> Any:
        return await self.request("PUT", path, json=body)
