"""Request/response RPC to on-prem connector agents, from any process (API, worker, runtime).

Agents keep one outbound WebSocket to an API instance. That instance subscribes to the Redis channel
``agent-rpc:<agent_id>`` and forwards requests to the socket; replies are pushed to the Redis list
``agent-rpc-reply:<request_id>``, which the caller pops with a timeout. ``PUBLISH`` returning zero
receivers means no API instance holds the agent's socket (the agent is offline).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from messer_common.events import get_redis
from messer_common.settings import get_settings

from .base import AgentUnavailable, ConnectorError, ReadOnlyViolation

REQUEST_CHANNEL = "agent-rpc:{agent_id}"
REPLY_KEY = "agent-rpc-reply:{request_id}"
REPLY_TTL_S = 120
# Agent error codes caused by the request itself (bad source, path outside the allowed folders…).
CALLER_ERRORS = {
    "unknown_source",
    "path_not_allowed",
    "no_paths",
    "not_found",
    "too_large",
    "unknown_method",
    "timeout",
}


def request_channel(agent_id: uuid.UUID | str) -> str:
    return REQUEST_CHANNEL.format(agent_id=agent_id)


def reply_key(request_id: str) -> str:
    return REPLY_KEY.format(request_id=request_id)


class AgentRpcError(ConnectorError):
    code = "agent_error"
    status_code = 502


async def call(
    agent_id: uuid.UUID | str, method: str, params: dict[str, Any] | None = None, *, timeout_s: float | None = None
) -> Any:
    timeout = float(timeout_s or get_settings().messer_connector_agent_rpc_timeout_s)
    request_id = uuid.uuid4().hex
    message = {
        "id": request_id,
        "method": method,
        "params": params or {},
        "timeout_ms": int(timeout * 1000),
    }
    redis = get_redis()
    receivers = await redis.publish(request_channel(agent_id), json.dumps(message, default=str))
    if not receivers:
        raise AgentUnavailable(
            "El agente on-premise no está conectado. Comprueba que el servicio está en marcha.",
            details={"agent_id": str(agent_id)},
        )
    popped = await redis.blpop([reply_key(request_id)], timeout=timeout + 2)  # type: ignore[misc]
    if popped is None:
        raise AgentUnavailable(
            f"El agente on-premise no ha respondido en {int(timeout)} s",
            code="agent_timeout",
            details={"agent_id": str(agent_id), "method": method},
        )
    reply = json.loads(popped[1])
    if not reply.get("ok"):
        error = reply.get("error") or {}
        message = str(error.get("message") or "El agente ha devuelto un error")
        code = str(error.get("code") or "agent_error")
        if code == "sql_read_only":
            raise ReadOnlyViolation(message, details={"method": method})
        if code.startswith("sql_") or code in CALLER_ERRORS:
            raise ConnectorError(message, code=code, details={"method": method})
        raise AgentRpcError(message, code=code, details={"method": method})
    return reply.get("result")


async def push_reply(request_id: str, reply: dict[str, Any]) -> None:
    """Called by the API instance that holds the agent socket."""
    redis = get_redis()
    key = reply_key(request_id)
    pipe = redis.pipeline()
    pipe.rpush(key, json.dumps(reply, default=str))
    pipe.expire(key, REPLY_TTL_S)
    await pipe.execute()


class AgentSqlEngine:
    """Same surface as :class:`messer_connectors.sql.SqlEngine`, executed by an agent next to the database."""

    def __init__(self, agent_id: uuid.UUID, *, source: str, dialect: str) -> None:
        self.agent_id = agent_id
        self.source = source
        self.dialect = dialect

    async def ping(self) -> dict[str, Any]:
        return await call(self.agent_id, "sql.ping", {"source": self.source})

    async def query(
        self,
        sql: str,
        params: list[Any] | None = None,
        *,
        limit: int = 1000,
        timeout_ms: int = 15_000,
        allow_write: bool = False,
    ) -> dict[str, Any]:
        # Writes are never routed through agents: agents are read-only by design.
        return await call(
            self.agent_id,
            "sql.query",
            {"source": self.source, "sql": sql, "params": params or [], "limit": limit, "timeout_ms": timeout_ms},
            timeout_s=timeout_ms / 1000 + 5,
        )

    async def introspect(self, *, schemas: list[str] | None = None) -> dict[str, Any]:
        return await call(
            self.agent_id, "sql.introspect", {"source": self.source, "schemas": schemas or []}, timeout_s=90
        )

    async def fetch_batch(
        self,
        *,
        schema: str | None,
        table: str,
        columns: list[str],
        key_columns: list[str],
        key_types: list[str],
        after: list[Any] | None = None,
        lower_bound: Any = None,
        limit: int = 500,
        timeout_ms: int = 120_000,
    ) -> dict[str, Any]:
        params = {
            "source": self.source,
            "schema": schema,
            "table": table,
            "columns": columns,
            "key_columns": key_columns,
            "key_types": key_types,
            "after": after,
            "lower_bound": lower_bound,
            "limit": limit,
            "timeout_ms": timeout_ms,
        }
        return await call(self.agent_id, "sql.fetch_batch", params, timeout_s=timeout_ms / 1000 + 5)
