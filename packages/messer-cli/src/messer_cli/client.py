"""Small synchronous client of the platform API for the CLI (errors become :class:`CliApiError`)."""

from __future__ import annotations

from typing import Any

import httpx

from . import __version__

# Test hook: route requests to an in-process API (httpx transport).
transport: httpx.BaseTransport | None = None


class CliApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return f"{self.message} (HTTP {self.status}, {self.code})" if self.status else self.message


class Api:
    def __init__(self, base_url: str, api_key: str, *, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        root = self.base_url.removesuffix("/api/v1")
        self._client = httpx.Client(
            base_url=root,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "User-Agent": f"messer-cli/{__version__}",
            },
            timeout=httpx.Timeout(timeout, connect=15.0),
            transport=transport,
        )

    def __enter__(self) -> Api:
        return self

    def __exit__(self, *_: object) -> None:
        self._client.close()

    def request(self, method: str, path: str, /, *, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith(("/v1/", "/api/")) else f"/api/v1{path}"
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            res = self._client.request(method, url, json=json, params=clean or None)
        except httpx.HTTPError as exc:
            raise CliApiError(0, "unreachable", f"No se puede conectar con {self.base_url}: {exc}") from exc
        if res.status_code >= 400:
            code, message, details = "http_error", res.reason_phrase or "Error", {}
            try:
                body = res.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and isinstance(body.get("error"), dict):
                code = str(body["error"].get("code") or code)
                message = str(body["error"].get("message") or message)
                details = body["error"].get("details") or {}
            raise CliApiError(res.status_code, code, message, details if isinstance(details, dict) else {})
        if res.status_code == 204 or not res.content:
            return None
        return res.json() if "application/json" in res.headers.get("content-type", "") else res.text

    def get(self, path: str, /, **params: Any) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any = None, /) -> Any:
        return self.request("POST", path, json=body if body is not None else {})
