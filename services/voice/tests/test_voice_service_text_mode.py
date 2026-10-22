"""End to end, demo (text) mode: browser ↔ voice service ↔ runtime. Two turns with memory, traces, call record."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import websockets
from sqlalchemy import select
from voice_support import anthropic_memory_reply, recv_until, setup_agent

from messer_common.db import system_session
from messer_common.db.models import Conversation, Run, Span
from messer_common.db.models.voice import VoiceCall
from messer_common.settings import get_settings
from messer_runtime.testing import Harness


@pytest.fixture
def memory_model(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    gateway.anthropic_transport = httpx.MockTransport(anthropic_memory_reply())
    yield
    gateway.anthropic_transport = None


async def test_text_mode_call_two_turns_with_memory(
    api_client: httpx.AsyncClient,
    voice_server,
    runtime: Harness,
    memory_model,  # type: ignore[no-untyped-def]
) -> None:
    pid = await setup_agent(api_client, voice={"greeting": "Hola, soy la recepcionista de Acme."})
    status = (await api_client.get("/api/v1/voice/status")).json()
    assert status["mode"] == "text" and status["audio"]["available"] is False

    res = await api_client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "recepcion"})
    assert res.status_code == 201, res.text
    session = res.json()
    assert session["mode"] == "text" and session["ws_url"].startswith(voice_server.ws_url)

    frames: list[dict] = []
    async with websockets.connect(session["ws_url"]) as ws:
        started = await recv_until(ws, "session_started", into=frames)
        assert started["mode"] == "text" and started["call_id"] == session["call_id"]
        # The opener is spoken by the browser: a speak segment, then the bubble closes.
        greeting = await recv_until(ws, "speak", into=frames)
        assert greeting["text"] == "Hola, soy la recepcionista de Acme."
        await recv_until(ws, "agent_text_done", into=frames)
        await ws.send(json.dumps({"type": "playback", "played_ms": greeting["duration_ms"]}))
        await ws.send(json.dumps({"type": "speech_done"}))

        await ws.send(
            json.dumps({"type": "user_text", "text": "Me llamo Marta y quiero revisar una factura", "final": True})
        )
        committed = await recv_until(ws, "transcript_committed", into=frames)
        assert committed["text"].startswith("Me llamo Marta")
        first: list[dict] = []
        done1 = await recv_until(ws, "agent_text_done", into=first)
        assert "Llevo 1 mensajes" in done1["text"] and done1["run_id"]
        spoken = [f for f in first if f["type"] == "speak"]
        assert spoken and "".join(f["text"] for f in spoken).replace(" ", "") == done1["text"].replace(" ", "")
        metrics1 = await recv_until(ws, "metrics", into=frames)
        assert metrics1["metrics"]["run_id"] == done1["run_id"] and metrics1["metrics"]["interrupted"] is False
        played = greeting["duration_ms"] + sum(f["duration_ms"] for f in spoken)
        await ws.send(json.dumps({"type": "playback", "played_ms": played}))
        await ws.send(json.dumps({"type": "speech_done"}))

        await ws.send(json.dumps({"type": "user_text", "text": "¿Recuerdas cómo me llamo?", "final": True}))
        done2 = await recv_until(ws, "agent_text_done", into=frames)
        # Same memory as the chat: the second run sees the first turn.
        assert "Llevo 2 mensajes" in done2["text"] and "Me llamo Marta" in done2["text"]
        await recv_until(ws, "metrics", into=frames)
        await ws.send(json.dumps({"type": "hangup"}))
        transcript = await recv_until(ws, "session_transcript", into=frames)
        summary = await recv_until(ws, "call_summary", into=frames)

    assert [e["role"] for e in transcript["entries"]] == ["assistant", "user", "assistant", "user", "assistant"]
    assert summary["status"] == "completed" and summary["turns"] == 2
    call_id = uuid.UUID(session["call_id"])
    async with system_session() as s:
        call = await s.get(VoiceCall, call_id)
        assert call is not None and call.status == "completed" and call.mode == "text"
        assert call.ended_at is not None and call.duration_ms is not None
        assert [t["status"] for t in call.turns] == ["success", "success"]
        run1, run2 = (uuid.UUID(hex=t["run_id"]) for t in call.turns)
        assert call.turns[1]["parent_run_id"] == call.turns[0]["run_id"]
        assert call.turns[0]["metrics"]["eou_to_first_audio_ms"] is not None
        assert call.usage["stt"]["provider"] == "browser" and call.voice_cost_usd == 0
        assert len(call.transcript) == 5 and call.transcript[0]["offset_ms"] >= 0
        runs = {r.id: r for r in (await s.execute(select(Run).where(Run.id.in_([run1, run2])))).scalars()}
        assert runs[run1].channel == "voice" and runs[run2].parent_run_id == run1
        assert runs[run1].conversation_id == call.conversation_id
        conv = await s.get(Conversation, call.conversation_id)
        assert conv is not None and conv.provider == "voice" and conv.last_run_id == run2
        assert [m["role"] for m in conv.messages] == ["user", "assistant", "user", "assistant"]
        voice_spans = (
            (await s.execute(select(Span).where(Span.run_id.in_([run1, run2]), Span.name == "voice"))).scalars().all()
        )
        assert len(voice_spans) == 2
        assert all(sp.meta["voice"]["call_id"] == str(call_id) for sp in voice_spans)
        assert all(sp.parent_call_id is not None for sp in voice_spans)

    detail = (await api_client.get(f"/api/v1/voice/calls/{call_id}")).json()
    assert detail["status"] == "completed" and len(detail["turn_details"]) == 2
    assert detail["latency"]["avg_first_audio_ms"] is not None
    calls = (await api_client.get("/api/v1/voice/calls", params={"project_id": pid})).json()
    assert calls["total"] == 1 and calls["items"][0]["id"] == str(call_id)


async def test_ticket_is_single_use_and_checked(
    api_client: httpx.AsyncClient,
    voice_server,
    runtime: Harness,  # type: ignore[no-untyped-def]
) -> None:
    pid = await setup_agent(api_client)
    session = (
        await api_client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "recepcion"})
    ).json()
    async with websockets.connect(f"{voice_server.ws_url}/v1/session?ticket=forged") as ws:
        error = json.loads(await ws.recv())
        assert error["type"] == "error" and error["code"] == "invalid_ticket"
    async with websockets.connect(session["ws_url"]) as ws:
        await recv_until(ws, "session_started")
        await ws.send(json.dumps({"type": "hangup"}))
        await recv_until(ws, "call_summary")
    # Replaying the same ticket is refused.
    async with websockets.connect(session["ws_url"]) as ws:
        error = json.loads(await ws.recv())
        assert error["code"] == "invalid_ticket"
