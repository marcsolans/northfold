"""RPC methods the control plane may call on the agent. Everything is read-only by construction."""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import platform
import socket
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from messer_connectors.sql import SqlError, create_engine

from . import __version__
from .config import AgentConfig

MAX_LIST_ENTRIES = 10_000


class AgentError(Exception):
    def __init__(self, message: str, code: str = "agent_error") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


Handler = Callable[[AgentConfig, dict[str, Any]], Awaitable[Any]]


def _source(config: AgentConfig, params: dict[str, Any]) -> Any:
    name = str(params.get("source") or "")
    source = config.sources.get(name)
    if source is None:
        raise AgentError(f"El agente no tiene un origen llamado «{name}»", code="unknown_source")
    try:
        # Agents never write: read_only is forced regardless of what the caller asks.
        return create_engine(source.type, source.dsn, read_only=True)
    except SqlError as exc:
        raise AgentError(exc.message, code=exc.code) from exc


def _allowed(config: AgentConfig, raw: str) -> Path:
    if not config.paths:
        raise AgentError("El agente no tiene rutas de archivos configuradas", code="no_paths")
    path = Path(raw).expanduser().resolve()
    for root in config.paths:
        if path == root or root in path.parents:
            return path
    raise AgentError("La ruta está fuera de las carpetas permitidas en el agente", code="path_not_allowed")


async def ping(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "version": __version__,
        "platform": f"{platform.system()} {platform.release()} · Python {platform.python_version()}",
        "time": datetime.now(UTC).isoformat(),
        **config.describe(),
    }


async def sql_ping(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    return await _source(config, params).ping()


async def sql_query(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    engine = _source(config, params)
    return await engine.query(
        str(params.get("sql") or ""),
        list(params.get("params") or []),
        limit=int(params.get("limit") or 1000),
        timeout_ms=int(params.get("timeout_ms") or 15_000),
    )


async def sql_introspect(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    schemas = [str(s) for s in params.get("schemas") or []] or None
    return await _source(config, params).introspect(schemas=schemas)


async def sql_fetch_batch(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    engine = _source(config, params)
    return await engine.fetch_batch(
        schema=params.get("schema"),
        table=str(params["table"]),
        columns=[str(c) for c in params.get("columns") or []],
        key_columns=[str(c) for c in params.get("key_columns") or []],
        key_types=[str(c) for c in params.get("key_types") or []],
        after=params.get("after"),
        lower_bound=params.get("lower_bound"),
        limit=int(params.get("limit") or 500),
        timeout_ms=int(params.get("timeout_ms") or 120_000),
    )


def _entry(path: Path) -> dict[str, Any]:
    info = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "is_dir": path.is_dir(),
        "size": 0 if path.is_dir() else info.st_size,
        "modified_at": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
    }


async def files_list(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    root = _allowed(config, str(params.get("path") or ""))
    recursive = bool(params.get("recursive"))
    if not root.exists():
        raise AgentError("La ruta no existe", code="not_found")

    def walk() -> list[dict[str, Any]]:
        if root.is_file():
            return [_entry(root)]
        out: list[dict[str, Any]] = []
        if recursive:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                for name in sorted(filenames):
                    if name.startswith("."):
                        continue
                    candidate = Path(dirpath) / name
                    try:
                        _allowed(config, str(candidate))  # symlinks pointing outside are skipped
                        out.append(_entry(candidate))
                    except (AgentError, OSError):
                        continue
                    if len(out) >= MAX_LIST_ENTRIES:
                        return out
            return out
        for child in sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if child.name.startswith("."):
                continue
            try:
                _allowed(config, str(child))
                out.append(_entry(child))
            except (AgentError, OSError):
                continue
        return out

    return {"path": str(root), "entries": await asyncio.to_thread(walk)}


async def files_read(config: AgentConfig, params: dict[str, Any]) -> dict[str, Any]:
    path = _allowed(config, str(params.get("path") or ""))
    if not path.is_file():
        raise AgentError("El archivo no existe", code="not_found")
    limit = min(int(params.get("max_bytes") or config.max_file_mb * 1024 * 1024), config.max_file_mb * 1024 * 1024)
    size = path.stat().st_size
    if size > limit:
        raise AgentError(f"El archivo supera el máximo permitido ({limit // (1024 * 1024)} MB)", code="too_large")
    data = await asyncio.to_thread(path.read_bytes)
    mime, _ = mimetypes.guess_type(path.name)
    return {
        "path": str(path),
        "size": size,
        "mime": mime or "application/octet-stream",
        "data_b64": base64.b64encode(data).decode(),
    }


HANDLERS: dict[str, Handler] = {
    "ping": ping,
    "sql.ping": sql_ping,
    "sql.query": sql_query,
    "sql.introspect": sql_introspect,
    "sql.fetch_batch": sql_fetch_batch,
    "files.list": files_list,
    "files.read": files_read,
}


async def dispatch(config: AgentConfig, method: str, params: dict[str, Any]) -> Any:
    handler = HANDLERS.get(method)
    if handler is None:
        raise AgentError(f"Método desconocido: {method}", code="unknown_method")
    try:
        return await handler(config, params)
    except SqlError as exc:
        raise AgentError(exc.message, code=f"sql_{exc.code}" if not exc.code.startswith("sql") else exc.code) from exc
