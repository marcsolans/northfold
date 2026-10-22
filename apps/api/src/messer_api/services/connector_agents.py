"""On-prem connector agents: enrollment tokens, secret exchange and the WebSocket hub.

Agents connect outbound to ``GET /api/v1/connector-agents/connect`` (WebSocket) with ``X-Messer-Agent-Id`` and
``Authorization: Bearer <agent secret>``. The API instance holding the socket subscribes to the Redis channel
``agent-rpc:<agent_id>`` and forwards requests; the agent's responses are pushed to the caller's reply list
(see :mod:`messer_connectors.agent_rpc`). Heartbeats update ``status`` / ``last_seen_at``.

Protocol (JSON text frames)::

    server → agent  {"type": "welcome", "agent_id", "heartbeat_s"}
    agent  → server {"type": "hello", "version", "hostname", "platform", "sources": [{name, type}], "paths": [...]}
    agent  → server {"type": "heartbeat"}                      server → agent {"type": "heartbeat_ack"}
    server → agent  {"type": "request", "id", "method", "params", "timeout_ms"}
    agent  → server {"type": "response", "id", "ok": true, "result": ...} | {"ok": false, "error": {code, message}}
    server → agent  {"type": "close", "reason"}                (agent deleted or re-enrolled)
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import ConnectorAgent
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.security import constant_time_equals, hash_token, random_token
from messer_common.settings import get_settings
from messer_connectors.agent_rpc import push_reply, request_channel

from ..errors import ApiError, NotFound
from .auth import consume_one_time_token, create_one_time_token

log = get_logger("messer.connector_agents")

ENROLL_PURPOSE = "connector_agent_enroll"
ENROLL_TTL = timedelta(hours=24)
HEARTBEAT_S = 20
IDLE_TIMEOUT_S = 75
LAST_SEEN_WRITE_S = 15
CONNECT_PATH = "/api/v1/connector-agents/connect"


def agent_status(agent: ConnectorAgent, now: datetime | None = None) -> str:
    if agent.enrolled_at is None:
        return "pending"
    now = now or datetime.now(UTC)
    if (
        agent.status == "online"
        and agent.last_seen_at
        and agent.last_seen_at > now - timedelta(seconds=IDLE_TIMEOUT_S + 15)
    ):
        return "online"
    return "offline"


def enroll_command(token: str) -> dict[str, str]:
    api = get_settings().messer_web_url.rstrip("/")
    return {
        "binary": f"messer-connector-agent enroll --api {api} --token {token}",
        "python": f"python -m messer_connector_agent enroll --api {api} --token {token}",
        "docker": (
            "docker run -d --name messer-agent --restart unless-stopped "
            "-v messer-agent:/etc/messer-agent -v $(pwd)/agent.yaml:/etc/messer-agent/agent.yaml:ro "
            f"ghcr.io/messer/connector-agent:latest enroll-and-run --api {api} --token {token}"
        ),
        "run": "messer-connector-agent run",
    }


async def issue_enrollment_token(agent: ConnectorAgent, user_id: uuid.UUID | None) -> str:
    """Single-use token (24 h). Issuing a new one invalidates the previous one."""
    async with system_session() as s:
        token = await create_one_time_token(
            s,
            purpose=ENROLL_PURPOSE,
            user_id=user_id,
            ttl=ENROLL_TTL,
            payload={"agent_id": str(agent.id), "org_id": str(agent.org_id)},
        )
    agent.enrollment_token_hash = hash_token(token)
    return token


async def enroll(token: str, *, hostname: str | None, version: str | None, ip: str | None) -> dict[str, Any]:
    async with system_session() as s:
        try:
            row = await consume_one_time_token(s, purpose=ENROLL_PURPOSE, token=token)
        except ApiError as exc:
            raise ApiError(
                "Token de alta no válido o caducado", code="invalid_enrollment_token", status_code=401
            ) from exc
        agent_id = uuid.UUID(str(row.payload.get("agent_id")))
        agent = (
            await s.execute(select(ConnectorAgent).where(ConnectorAgent.id == agent_id).with_for_update())
        ).scalar_one_or_none()
        if agent is None or not constant_time_equals(agent.enrollment_token_hash, hash_token(token)):
            raise ApiError(
                "Token de alta no válido o sustituido por otro", code="invalid_enrollment_token", status_code=401
            )
        secret = random_token(48)
        now = datetime.now(UTC)
        agent.agent_secret_hash = hash_token(secret)
        agent.enrollment_token_hash = hash_token(random_token(32))  # the token can never be used again
        agent.enrolled_at = now
        agent.status = "offline"
        agent.hostname = (hostname or "")[:255] or agent.hostname
        agent.version = (version or "")[:40] or agent.version
        await audit.record(
            s,
            action="connector_agent.enrolled",
            principal=Principal(user_id=None, org_id=agent.org_id),
            entity_type="connector_agent",
            entity_id=agent.id,
            diff={"hostname": agent.hostname, "version": agent.version},
            ip=ip,
        )
        org_id = agent.org_id
    await disconnect(agent_id, reason="re-enrolled")
    return {
        "agent_id": str(agent_id),
        "org_id": str(org_id),
        "agent_secret": secret,
        "connect_path": CONNECT_PATH,
        "heartbeat_s": HEARTBEAT_S,
    }


async def disconnect(agent_id: uuid.UUID, *, reason: str) -> None:
    """Ask whichever API instance holds the agent socket to close it."""
    try:
        await get_redis().publish(
            request_channel(agent_id), json.dumps({"type": "control", "action": "close", "reason": reason})
        )
    except Exception as exc:  # best effort: the socket also dies on the next failed auth
        log.warning("agent.disconnect_publish_failed", error=str(exc))


async def authenticate(agent_id_raw: str | None, secret: str | None) -> ConnectorAgent | None:
    if not agent_id_raw or not secret:
        return None
    try:
        agent_id = uuid.UUID(agent_id_raw)
    except ValueError:
        return None
    async with system_session() as s:
        agent = await s.get(ConnectorAgent, agent_id)
    if agent is None or agent.enrolled_at is None or not agent.agent_secret_hash:
        return None
    if not constant_time_equals(agent.agent_secret_hash, hash_token(secret)):
        return None
    return agent


_background: set[asyncio.Task[None]] = set()


def disconnect_after_commit(db: AsyncSession, agent_id: uuid.UUID, *, reason: str) -> None:
    """Close the agent's live socket once the request transaction (e.g. the deletion) has committed."""
    loop = asyncio.get_running_loop()

    def after_commit(_session: Any) -> None:
        task = loop.create_task(disconnect(agent_id, reason=reason))
        _background.add(task)
        task.add_done_callback(_background.discard)

    event.listen(db.sync_session, "after_commit", after_commit, once=True)


class AgentGone(Exception):
    """The agent was deleted or re-enrolled while its socket was open."""


async def _update_agent(agent_id: uuid.UUID, **values: Any) -> bool:
    async with system_session() as s:
        agent = await s.get(ConnectorAgent, agent_id)
        if agent is None:
            return False
        for key, value in values.items():
            setattr(agent, key, value)
    return True


async def get_agent(session: Any, org_id: uuid.UUID, agent_id: uuid.UUID) -> ConnectorAgent:
    agent = await session.get(ConnectorAgent, agent_id)
    if agent is None or agent.org_id != org_id:
        raise NotFound("Agente no encontrado", code="agent_not_found")
    return agent


class AgentSession:
    """One live agent socket on this API instance."""

    def __init__(self, websocket: WebSocket, agent: ConnectorAgent) -> None:
        self.ws = websocket
        self.agent_id = agent.id
        self.org_id = agent.org_id
        self._send_lock = asyncio.Lock()
        self._last_seen_write = 0.0

    async def send(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            if self.ws.application_state == WebSocketState.CONNECTED:
                await self.ws.send_text(json.dumps(message, default=str))

    async def run(self) -> None:
        pubsub = get_redis().pubsub()
        await pubsub.subscribe(request_channel(self.agent_id))
        now = datetime.now(UTC)
        await _update_agent(self.agent_id, status="online", last_seen_at=now)
        log.info("agent.connected", agent_id=str(self.agent_id))
        await self.send({"type": "welcome", "agent_id": str(self.agent_id), "heartbeat_s": HEARTBEAT_S})
        reader = asyncio.create_task(self._read_loop())
        forwarder = asyncio.create_task(self._forward_loop(pubsub))
        try:
            done, pending = await asyncio.wait({reader, forwarder}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in pending:
                try:
                    await task
                except (asyncio.CancelledError, Exception):  # noqa: S110 - shutting the session down
                    pass
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect | AgentGone | TimeoutError):
                    log.warning("agent.session_error", agent_id=str(self.agent_id), error=repr(exc))
        finally:
            try:
                await pubsub.unsubscribe(request_channel(self.agent_id))
                await pubsub.aclose()
            except Exception as exc:
                log.warning("agent.unsubscribe_failed", error=str(exc))
            await _update_agent(self.agent_id, status="offline", last_seen_at=datetime.now(UTC))
            log.info("agent.disconnected", agent_id=str(self.agent_id))
            if self.ws.application_state == WebSocketState.CONNECTED:
                try:
                    await self.ws.close()
                except RuntimeError:
                    pass

    async def _touch(self, force: bool = False, **extra: Any) -> None:
        loop_now = asyncio.get_running_loop().time()
        if force or loop_now - self._last_seen_write >= LAST_SEEN_WRITE_S:
            self._last_seen_write = loop_now
            if not await _update_agent(self.agent_id, status="online", last_seen_at=datetime.now(UTC), **extra):
                await self.send({"type": "close", "reason": "deleted"})
                raise AgentGone(str(self.agent_id))

    async def _read_loop(self) -> None:
        while True:
            raw = await asyncio.wait_for(self.ws.receive_text(), timeout=IDLE_TIMEOUT_S)
            try:
                message = json.loads(raw)
            except ValueError:
                continue
            kind = message.get("type")
            if kind == "heartbeat":
                await self._touch()
                await self.send({"type": "heartbeat_ack", "ts": datetime.now(UTC).isoformat()})
            elif kind == "hello":
                capabilities = {
                    "sources": [
                        {"name": str(s.get("name")), "type": str(s.get("type"))}
                        for s in message.get("sources") or []
                        if isinstance(s, dict) and s.get("name")
                    ][:100],
                    "paths": [str(p) for p in message.get("paths") or []][:100],
                    "platform": str(message.get("platform") or "")[:120],
                }
                await self._touch(
                    force=True,
                    capabilities=capabilities,
                    version=str(message.get("version") or "")[:40] or None,
                    hostname=str(message.get("hostname") or "")[:255] or None,
                )
            elif kind == "response" and message.get("id"):
                await push_reply(
                    str(message["id"]),
                    {"ok": bool(message.get("ok")), "result": message.get("result"), "error": message.get("error")},
                )
                await self._touch()

    async def _forward_loop(self, pubsub: Any) -> None:
        async for item in pubsub.listen():
            if item.get("type") != "message":
                continue
            try:
                message = json.loads(item["data"])
            except ValueError:
                continue
            if message.get("type") == "control":
                if message.get("action") == "close":
                    await self.send({"type": "close", "reason": message.get("reason", "")})
                    return
                continue
            await self.send(
                {
                    "type": "request",
                    "id": message.get("id"),
                    "method": message.get("method"),
                    "params": message.get("params") or {},
                    "timeout_ms": message.get("timeout_ms"),
                }
            )


async def serve(websocket: WebSocket) -> None:
    agent = await authenticate(
        websocket.headers.get("x-messer-agent-id"), _bearer(websocket.headers.get("authorization"))
    )
    if agent is None:
        await websocket.close(code=4401, reason="invalid agent credentials")
        return
    await websocket.accept()
    await AgentSession(websocket, agent).run()


def _bearer(header: str | None) -> str | None:
    if header and header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None
