"""Any MCP server, by URL (streamable HTTP + headers) or by command (stdio), through the engine's MCPServer."""

from __future__ import annotations

import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from messer_common.settings import get_settings

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
from ..http import ensure_public_url
from ..registry import register
from ..util import validate_args

CONNECT_TIMEOUT_S = 30.0
CALL_TIMEOUT_S = 120.0


def _tool_out(tool: Any) -> dict[str, Any]:
    annotations = getattr(tool, "tool_annotations", None) or {}
    read_only = bool(annotations.get("readOnlyHint"))
    return {
        "name": tool.name,
        "title": getattr(tool, "title", None),
        "description": tool.description,
        "input_schema": getattr(tool, "input_schema", {}) or {"type": "object", "properties": {}},
        "annotations": annotations,
        "read_only": read_only,
        "side_effect": not read_only,
    }


def _result_out(value: Any) -> Any:
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, list | dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    return str(value)


@register
class McpAdapter(ConnectorAdapter):
    spec = ConnectorSpec(
        key="mcp",
        name="Servidor MCP",
        category="developer",
        auth_type="mcp",
        description="Cualquier servidor MCP por URL (HTTP con cabeceras) o por comando (stdio): sus herramientas pasan a tus agentes.",
        description_en="Any MCP server by URL (HTTP with headers) or command (stdio): its tools become available to agents.",
        icon="mcp",
        capabilities=Capabilities(actions=["list_tools", "call_tool"]),
        config_fields=[
            ConfigField(key="transport", kind="select", options=["http", "stdio"], default="http", required=True),
            ConfigField(key="url", kind="url", placeholder="https://mcp.ejemplo.com/mcp"),
            ConfigField(key="headers", kind="json", secret=True),
            ConfigField(key="command", kind="text", placeholder="npx -y @modelcontextprotocol/server-everything"),
            ConfigField(key="env", kind="json", secret=True),
        ],
        docs_url="https://modelcontextprotocol.io",
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_tools", title="Listar herramientas", description="Herramientas que expone el servidor MCP."
            ),
            ActionSpec(
                name="call_tool",
                title="Ejecutar herramienta",
                description="Ejecuta una herramienta del servidor MCP con sus argumentos.",
                input_schema=obj_schema(
                    {"tool": {"type": "string", "minLength": 1}, "arguments": {"type": "object", "default": {}}},
                    ["tool"],
                ),
                side_effect=True,
            ),
        ]

    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        transport = config.get("transport", "http")
        if transport == "http":
            url = str(config.get("url") or "")
            if not url.startswith(("http://", "https://")):
                raise ConfigError("Indica la URL http(s) del servidor MCP", details={"field": "url"})
        elif transport == "stdio":
            if not config.get("command"):
                raise ConfigError("Indica el comando que arranca el servidor MCP", details={"field": "command"})
        else:
            raise ConfigError("Transporte no válido: usa «http» o «stdio»", details={"field": "transport"})
        for key in ("headers", "env"):
            value = credentials.get(key)
            if value is not None and not (isinstance(value, dict) and all(isinstance(v, str) for v in value.values())):
                raise ConfigError(f"«{key}» debe ser un objeto de textos", details={"field": key})

    def prepare(self, config: dict[str, Any], credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        config = dict(config)
        credentials = dict(credentials)
        for key in ("headers", "env"):  # secrets never live in clear config
            if key in config:
                credentials[key] = config.pop(key)
        if config.get("transport") == "stdio" and isinstance(config.get("command"), str) and not config.get("args"):
            parts = shlex.split(str(config["command"]))
            config["command"], config["args"] = parts[0], parts[1:]
        config.setdefault("transport", "http")
        return config, credentials

    @asynccontextmanager
    async def server(self, ctx: ConnectionContext) -> AsyncIterator[Any]:
        try:
            from messer.core import MCPServer
        except ImportError as exc:  # pragma: no cover - messer-core is part of the platform install
            raise ConnectorError("El motor (messer-core) no está instalado", code="engine_missing") from exc

        transport = ctx.config.get("transport", "http")
        name = str(ctx.config.get("server_name") or "mcp")
        if transport == "http":
            url = str(ctx.config.get("url") or "")
            await ensure_public_url(url)
            server = MCPServer(
                name=name,
                transport="http",
                url=url,
                headers=dict(ctx.credentials.get("headers") or {}),
                connect_timeout=CONNECT_TIMEOUT_S,
                timeout=CALL_TIMEOUT_S,
                elicitation=False,
            )
        else:
            if not get_settings().mcp_stdio_enabled:
                raise ConnectorError(
                    "Los servidores MCP por comando se ejecutan en el runtime del proyecto o en un agente on-premise; "
                    "aquí solo se admiten servidores por URL.",
                    code="mcp_stdio_disabled",
                )
            server = MCPServer(
                name=name,
                transport="stdio",
                command=str(ctx.config.get("command")),
                args=[str(a) for a in ctx.config.get("args") or []],
                env=dict(ctx.credentials.get("env") or {}),
                connect_timeout=CONNECT_TIMEOUT_S,
                timeout=CALL_TIMEOUT_S,
                elicitation=False,
            )
        try:
            yield server
        finally:
            await server.close()

    async def list_tools(self, ctx: ConnectionContext) -> list[dict[str, Any]]:
        async with self.server(ctx) as server:
            try:
                tools = await server.resolve()
            except (TimeoutError, ConnectionError, OSError) as exc:
                raise ConnectorError(
                    f"No se puede conectar con el servidor MCP: {exc}", code="mcp_unreachable"
                ) from exc
            except Exception as exc:  # the MCP SDK raises ExceptionGroups and McpError on handshake failures
                raise ConnectorError(f"El servidor MCP ha fallado: {_describe(exc)}", code="mcp_error") from exc
        prefix = f"{server.name}__" if server.name else ""
        out = []
        for tool in tools:
            item = _tool_out(tool)
            if prefix and item["name"].startswith(prefix):
                item["name"] = item["name"][len(prefix) :]
            out.append(item)
        return out

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        data = validate_args(self.action(action), args)
        if action == "list_tools":
            return await self.list_tools(ctx)
        if action == "call_tool":
            async with self.server(ctx) as server:
                try:
                    tools = await server.resolve()
                    wanted = str(data["tool"])
                    match = next((t for t in tools if t.name in (wanted, f"{server.name}__{wanted}")), None)
                    if match is None:
                        raise ConnectorError(
                            f"El servidor MCP no tiene la herramienta «{wanted}»", code="mcp_tool_not_found"
                        )
                    result = await match.handler(**dict(data.get("arguments") or {}))
                except ConnectorError:
                    raise
                except Exception as exc:
                    raise ConnectorError(f"La herramienta MCP ha fallado: {_describe(exc)}", code="mcp_error") from exc
            return {"tool": data["tool"], "result": _result_out(result)}
        return await super().run_action(ctx, action, args)

    async def test(self, ctx: ConnectionContext) -> TestResult:
        tools = await self.list_tools(ctx)
        return TestResult(
            ok=True, message=f"Servidor MCP disponible: {len(tools)} herramientas", details={"tools": len(tools)}
        )


def _describe(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(_describe(e) for e in exc.exceptions)
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
