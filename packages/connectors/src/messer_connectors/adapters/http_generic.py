"""Generic HTTP API: configurable base URL and auth header. GET needs no approval; other methods are side effects."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .. import http as chttp
from ..base import (
    ActionSpec,
    Capabilities,
    ConfigError,
    ConfigField,
    ConnectionContext,
    ConnectorAdapter,
    ConnectorError,
    ConnectorSpec,
    TestResult,
    obj_schema,
)
from ..registry import register
from ..util import truncate, validate_args

MAX_BODY_CHARS = 100_000
BLOCKED_HEADERS = {"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer"}
_HEADER_MAP = {"type": "object", "additionalProperties": {"type": "string"}}
_QUERY = {"type": "object", "additionalProperties": {"type": ["string", "number", "boolean"]}}


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    return parts.scheme, (parts.hostname or "").lower(), parts.port


@register
class HttpAdapter(ConnectorAdapter):
    spec = ConnectorSpec(
        key="http",
        name="HTTP genérico",
        category="developer",
        auth_type="api_key",
        description="Cualquier API REST con URL base y cabecera de autenticación. Las peticiones que no son GET requieren aprobación.",
        description_en="Any REST API with a base URL and an auth header. Non-GET requests require approval.",
        icon="globe",
        capabilities=Capabilities(actions=["get", "request"]),
        config_fields=[
            ConfigField(key="base_url", kind="url", required=True, placeholder="https://api.ejemplo.com/v1"),
            ConfigField(key="auth_header_name", kind="text", default="Authorization"),
            ConfigField(key="auth_header_value", kind="secret", secret=True, placeholder="Bearer …"),
            ConfigField(key="default_headers", kind="json"),
        ],
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="get",
                title="GET",
                description="Petición GET a la API (ruta relativa a la URL base). No requiere aprobación.",
                input_schema=obj_schema(
                    {"path": {"type": "string", "default": "/"}, "query": _QUERY, "headers": _HEADER_MAP}
                ),
            ),
            ActionSpec(
                name="request",
                title="Petición con efectos",
                description="POST, PUT, PATCH o DELETE a la API. Requiere aprobación.",
                input_schema=obj_schema(
                    {
                        "method": {"type": "string", "enum": ["POST", "PUT", "PATCH", "DELETE"]},
                        "path": {"type": "string", "default": "/"},
                        "query": _QUERY,
                        "headers": _HEADER_MAP,
                        "json": {"description": "Cuerpo JSON"},
                        "body": {"type": "string", "description": "Cuerpo en texto (si no se usa json)"},
                    },
                    ["method"],
                ),
                side_effect=True,
            ),
        ]

    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        base = str(config.get("base_url") or "")
        parts = urlsplit(base)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConfigError("Indica una URL base http(s) válida", details={"field": "base_url"})
        headers = config.get("default_headers")
        if headers is not None and not (
            isinstance(headers, dict) and all(isinstance(v, str) for v in headers.values())
        ):
            raise ConfigError(
                "Las cabeceras por defecto deben ser un objeto de textos", details={"field": "default_headers"}
            )

    def prepare(self, config: dict[str, Any], credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        config = dict(config)
        config["base_url"] = str(config["base_url"]).rstrip("/") + "/"
        config["auth_header_name"] = str(config.get("auth_header_name") or "Authorization")
        if "auth_header_value" in config:  # never store the secret in clear config
            credentials = {**credentials, "auth_header_value": config.pop("auth_header_value")}
        return config, credentials

    def _url(self, ctx: ConnectionContext, path: str) -> str:
        base = str(ctx.config.get("base_url") or "")
        if not base:
            raise ConfigError("La conexión no tiene URL base")
        if path.startswith(("http://", "https://")):
            if _origin(path) != _origin(base):
                raise ConnectorError("La URL debe pertenecer a la API configurada", code="foreign_origin")
            return path
        return urljoin(base, path.lstrip("/"))

    def _headers(self, ctx: ConnectionContext, extra: dict[str, str] | None) -> dict[str, str]:
        headers: dict[str, str] = {}
        for source in (ctx.config.get("default_headers") or {}, extra or {}):
            for k, v in source.items():
                if k.lower() not in BLOCKED_HEADERS:
                    headers[str(k)] = str(v)
        value = ctx.credentials.get("auth_header_value")
        if value:
            headers[str(ctx.config.get("auth_header_name") or "Authorization")] = str(value)
        return headers

    async def _send(self, ctx: ConnectionContext, method: str, path: str, data: dict[str, Any]) -> dict[str, Any]:
        url = self._url(ctx, path)
        kwargs: dict[str, Any] = {"params": {k: str(v) for k, v in (data.get("query") or {}).items()}}
        if method != "GET":
            if data.get("json") is not None:
                kwargs["json"] = data["json"]
            elif data.get("body") is not None:
                kwargs["content"] = str(data["body"]).encode()
        async with chttp.client(
            headers=self._headers(ctx, data.get("headers")), guard_url=url, request_timeout=30
        ) as c:
            try:
                res = await c.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                raise ConnectorError("La API no ha respondido a tiempo", code="provider_timeout") from exc
            except httpx.HTTPError as exc:
                raise ConnectorError(f"No se puede conectar con la API: {exc}", code="provider_unreachable") from exc
        return _response_out(res)

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        if action == "get":
            return await self._send(ctx, "GET", str(data["path"]), data)
        if action == "request":
            return await self._send(ctx, str(data["method"]).upper(), str(data["path"]), data)
        return await super().run_action(ctx, action, args)

    async def test(self, ctx: ConnectionContext) -> TestResult:
        out = await self._send(ctx, "GET", "", {})
        ok = int(out["status"]) < 500
        return TestResult(
            ok=ok,
            message=f"La API responde ({out['status']})" if ok else f"La API devuelve un error ({out['status']})",
            details={"status": out["status"]},
        )


def _response_out(res: httpx.Response) -> dict[str, Any]:
    content_type = res.headers.get("content-type", "")
    out: dict[str, Any] = {
        "status": res.status_code,
        "ok": res.is_success,
        "headers": {k: v for k, v in res.headers.items() if k.lower() in ("content-type", "location", "etag", "link")},
    }
    if "json" in content_type:
        try:
            out["json"] = res.json()
            text = json.dumps(out["json"], ensure_ascii=False)
            if len(text) > MAX_BODY_CHARS:
                out.pop("json")
                out["text"] = truncate(text, MAX_BODY_CHARS)
            return out
        except ValueError:
            pass
    out["text"] = truncate(res.text, MAX_BODY_CHARS) if res.content else ""
    return out
