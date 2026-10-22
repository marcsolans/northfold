"""Fixtures for the voice service: the voice app on a real port (WebSockets), the platform API in-process."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx
import pytest
import uvicorn

from messer_common.settings import get_settings
from messer_runtime.testing import free_port


@dataclass
class VoiceHarness:
    base_url: str
    ws_url: str
    client: httpx.AsyncClient


@pytest.fixture
async def voice_server(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[VoiceHarness]:
    from messer_api.services import voice as api_voice
    from messer_voice.config import get_voice_settings
    from messer_voice.main import create_app

    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(get_voice_settings(), "messer_voice_public_url", base_url)
    monkeypatch.setattr(get_voice_settings(), "messer_voice_idle_secs", 60.0)
    monkeypatch.setattr(api_voice.voice_settings(), "messer_voice_public_url", base_url)
    monkeypatch.setattr(get_settings(), "messer_voice_url", base_url)
    app = create_app()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning", ws="websockets-sansio")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    headers = {"Authorization": f"Bearer {get_settings().service_token}"}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=60) as client:
        try:
            yield VoiceHarness(base_url=base_url, ws_url=f"ws://127.0.0.1:{port}", client=client)
        finally:
            server.should_exit = True
            await task


@pytest.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    from messer_api.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver", timeout=120) as c:
        yield c
