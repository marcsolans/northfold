"""Outbound WebSocket client: keeps one connection to the control plane, reconnects with backoff, answers RPCs."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import ssl
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidURI

from . import __version__
from .config import AgentConfig, AgentState
from .handlers import AgentError, dispatch, ping

log = logging.getLogger("messer.connector_agent")

MAX_MESSAGE_BYTES = 64 * 1024 * 1024
DEFAULT_HEARTBEAT_S = 20
MAX_BACKOFF_S = 60.0
AUTH_BACKOFF_S = 300.0


class AgentClient:
    def __init__(self, state: AgentState, config: AgentConfig, *, ssl_context: ssl.SSLContext | None = None) -> None:
        self.state = state
        self.config = config
        self.ssl_context = ssl_context
        self.connected = asyncio.Event()
        self.sessions = 0
        self._semaphore = asyncio.Semaphore(config.max_concurrency)
        self._tasks: set[asyncio.Task[None]] = set()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.state.agent_secret}",
            "X-Messer-Agent-Id": self.state.agent_id,
            "User-Agent": f"messer-connector-agent/{__version__}",
        }

    async def run_forever(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        backoff = 1.0
        while not stop.is_set():
            delay = backoff
            try:
                kwargs: dict[str, Any] = {}
                if self.state.ws_url.startswith("wss://") and self.ssl_context is not None:
                    kwargs["ssl"] = self.ssl_context
                async with connect(
                    self.state.ws_url,
                    additional_headers=self._headers(),
                    open_timeout=15,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=MAX_MESSAGE_BYTES,
                    **kwargs,
                ) as ws:
                    backoff = 1.0
                    self.sessions += 1
                    log.info("connected to %s", self.state.ws_url)
                    await self._session(ws, stop)
                    delay = 1.0
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    log.error("the control plane rejected the agent credentials (HTTP %s); re-enroll the agent", status)
                    delay = AUTH_BACKOFF_S
                else:
                    log.warning("connection refused (HTTP %s)", status)
            except InvalidURI as exc:
                log.error("invalid control plane URL: %s", exc)
                return
            except (OSError, TimeoutError, ConnectionClosed) as exc:
                log.warning("connection lost: %s", exc)
            finally:
                self.connected.clear()
            if stop.is_set():
                break
            backoff = min(backoff * 2, MAX_BACKOFF_S)
            sleep_for = delay * (0.8 + random.random() * 0.4)  # noqa: S311 - jitter, not crypto
            try:
                await asyncio.wait_for(stop.wait(), timeout=sleep_for)
            except TimeoutError:
                pass
        await self._drain()

    async def _session(self, ws: ClientConnection, stop: asyncio.Event) -> None:
        hello = await ping(self.config, {})
        await ws.send(json.dumps({"type": "hello", **hello}))
        heartbeat_s = DEFAULT_HEARTBEAT_S
        heartbeat = asyncio.create_task(self._heartbeat(ws, lambda: heartbeat_s))
        stopper = asyncio.create_task(stop.wait())
        try:
            while True:
                receive = asyncio.create_task(ws.recv())
                done, _ = await asyncio.wait({receive, stopper}, return_when=asyncio.FIRST_COMPLETED)
                if stopper in done:
                    receive.cancel()
                    await ws.close()
                    return
                raw = receive.result()
                try:
                    message = json.loads(raw)
                except ValueError:
                    continue
                kind = message.get("type")
                if kind == "welcome":
                    # Sent once the control plane is subscribed to this agent's requests.
                    heartbeat_s = int(message.get("heartbeat_s") or DEFAULT_HEARTBEAT_S)
                    self.connected.set()
                elif kind == "request":
                    task = asyncio.create_task(self._handle(ws, message))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
                elif kind == "close":
                    log.warning("the control plane closed the session: %s", message.get("reason"))
                    await ws.close()
                    return
        finally:
            heartbeat.cancel()
            stopper.cancel()

    async def _heartbeat(self, ws: ClientConnection, interval: Any) -> None:
        while True:
            await asyncio.sleep(interval())
            await ws.send(json.dumps({"type": "heartbeat"}))

    async def _handle(self, ws: ClientConnection, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = str(message.get("method") or "")
        params = message.get("params") or {}
        timeout_s = max(1.0, float(message.get("timeout_ms") or 30_000) / 1000)
        async with self._semaphore:
            try:
                result = await asyncio.wait_for(dispatch(self.config, method, params), timeout=timeout_s)
                reply: dict[str, Any] = {"type": "response", "id": request_id, "ok": True, "result": result}
            except AgentError as exc:
                reply = {
                    "type": "response",
                    "id": request_id,
                    "ok": False,
                    "error": {"code": exc.code, "message": exc.message},
                }
            except TimeoutError:
                reply = {
                    "type": "response",
                    "id": request_id,
                    "ok": False,
                    "error": {"code": "timeout", "message": f"La operación ha superado {int(timeout_s)} s"},
                }
            except Exception as exc:  # report every failure back to the caller instead of dropping the reply
                log.exception("request %s (%s) failed", request_id, method)
                reply = {
                    "type": "response",
                    "id": request_id,
                    "ok": False,
                    "error": {"code": "internal", "message": f"{type(exc).__name__}: {exc}"},
                }
        try:
            await ws.send(json.dumps(reply, default=str))
        except ConnectionClosed:
            log.warning("connection closed before replying to %s", request_id)

    async def _drain(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
