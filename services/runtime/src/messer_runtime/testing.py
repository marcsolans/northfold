"""Pytest support for tests that need a live runtime (registered as a plugin by the root ``conftest.py``)."""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from messer_common.projects_repo import ProjectRepo
from messer_common.settings import get_settings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Harness:
    app: FastAPI
    base_url: str
    client: httpx.AsyncClient

    async def stream_run(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        async with self.client.stream("POST", "/internal/v1/runs/stream", json=body) as res:
            assert res.status_code == 200, await res.aread()
            async for line in res.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        return events


@pytest.fixture
async def runtime(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Harness]:
    """The runtime's internal API on a real port (sandboxes call back into it over HTTP).

    Also points the control plane's runtime client and model helper at it (``MESSER_RUNTIME_URL``).
    """
    from messer_runtime import code_cache, gateway
    from messer_runtime.internal import router
    from messer_runtime.runs import RunExecutor
    from messer_runtime.sandbox.manager import SandboxPool

    async def local_archive(project_id: uuid.UUID, ref: str) -> tuple[str, bytes]:
        repo = ProjectRepo.for_project(str(project_id))
        commit = await repo.resolve(ref)
        return commit, await repo.archive(commit)

    monkeypatch.setattr(code_cache, "fetch_archive", local_archive)
    gateway.invalidate_caches()

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    pool = SandboxPool(internal_base_url=base_url)
    app = FastAPI()
    app.include_router(router)
    app.state.pool = pool
    app.state.executor = RunExecutor(pool)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    monkeypatch.setattr(get_settings(), "messer_runtime_url", base_url)
    headers = {"Authorization": f"Bearer {get_settings().service_token}"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120) as client:
        try:
            yield Harness(app=app, base_url=base_url, client=client)
        finally:
            server.should_exit = True
            await task
            await pool.shutdown()
            gateway.anthropic_transport = None
            gateway.bedrock_client_factory = None


def anthropic_reply(
    text: str, usage: dict[str, int], model: str = "claude-sonnet-5-5"
) -> Callable[[httpx.Request], httpx.Response]:
    """Mock of the Anthropic Messages API (JSON or SSE depending on the request's ``stream`` flag)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        message = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", model),
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }
        if not body.get("stream"):
            return httpx.Response(200, json=message)
        start = {
            **message,
            "content": [],
            "stop_reason": None,
            "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 1},
        }
        events = [
            ("message_start", {"type": "message_start", "message": start}),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            ),
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": usage["output_tokens"]},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        raw = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
        return httpx.Response(200, content=raw.encode(), headers={"content-type": "text/event-stream"})

    return handler
