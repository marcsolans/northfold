"""Audio mode with fake hosted STT/TTS: protocol, barge-in, tool-call filler, recording with consent, cost."""

from __future__ import annotations

import base64
import json
import uuid
from decimal import Decimal

import httpx
import pytest
import websockets
from sqlalchemy import select
from voice_support import (
    anthropic_text,
    anthropic_tool_then_text,
    recv_until,
    say,
    setup_agent,
    use_fake_speech,
)

from messer_common.db import system_session
from messer_common.db.models import AuditLog, CreditLedger
from messer_common.db.models.voice import VoiceCall
from messer_common.settings import get_settings
from messer_common.storage import get_storage
from messer_runtime.testing import Harness


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")

    def use(handler) -> None:  # type: ignore[no-untyped-def]
        gateway.anthropic_transport = httpx.MockTransport(handler)

    yield use
    gateway.anthropic_transport = None


async def test_audio_session_barge_in_recording_and_cost(
    api_client: httpx.AsyncClient,
    voice_server,  # type: ignore[no-untyped-def]
    runtime: Harness,
    model,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 60 ms of audio per character: the reply keeps "playing" long enough to be interrupted.
    fakes = use_fake_speech(monkeypatch, ms_per_char=60)
    model(anthropic_text("Claro. Su factura de marzo está pagada y la de abril vence el día treinta."))
    pid = await setup_agent(api_client)
    status = (await api_client.get("/api/v1/voice/status")).json()
    assert status["mode"] == "audio" and status["audio"]["stt"].startswith("deepgram/")

    refused = await api_client.post(
        "/api/v1/voice/sessions", json={"project_id": pid, "workforce": "recepcion", "record": True}
    )
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "recording_consent_required"
    res = await api_client.post(
        "/api/v1/voice/sessions",
        json={"project_id": pid, "workforce": "recepcion", "record": True, "consent": True},
    )
    assert res.status_code == 201, res.text
    session = res.json()
    assert session["mode"] == "audio" and session["recording"] is True

    frames: list[dict] = []
    async with websockets.connect(session["ws_url"]) as ws:
        started = await recv_until(ws, "session_started", into=frames)
        assert started["mode"] == "audio" and started["stt_provider"] == "deepgram" and started["recording"]
        await ws.send(say("¿Cómo van mis facturas?"))
        await recv_until(ws, "transcript_committed", into=frames)
        turn1: list[dict] = []
        done1 = await recv_until(ws, "agent_text_done", into=turn1)
        audio = [f for f in turn1 if f["type"] == "audio"]
        assert audio and len(base64.b64decode(audio[0]["data"])) > 0
        metrics = await recv_until(ws, "metrics", into=frames)
        assert metrics["metrics"]["run_id"] == done1["run_id"]
        assert metrics["metrics"]["eou_to_first_audio_ms"] is not None
        # Barge-in while the reply is still playing (no playback acks: wall-clock estimate).
        await ws.send(say("Espera, una pregunta más"))
        interrupted = await recv_until(ws, "interrupted", into=frames)
        assert interrupted["heard_text"] is not None
        await recv_until(ws, "agent_text_done", into=frames)
        await recv_until(ws, "metrics", into=frames)
        await ws.send(json.dumps({"type": "hangup"}))
        summary = await recv_until(ws, "call_summary", into=frames)

    assert summary["recording"] is True and summary["turns"] == 2
    assert fakes["tts"][0].texts, "the reply was synthesized"
    call_id = uuid.UUID(session["call_id"])
    async with system_session() as s:
        call = await s.get(VoiceCall, call_id)
        assert call is not None and call.status == "completed" and call.mode == "audio"
        assert call.recording_key and call.recording_consent == "explicit"
        assert call.usage["stt"]["provider"] == "deepgram" and call.usage["stt"]["seconds"] > 0
        assert call.usage["tts"]["characters"] > 0
        assert call.voice_cost_usd > 0 and call.credits > 0
        ledger = (
            await s.execute(select(CreditLedger).where(CreditLedger.idempotency_key == f"usage:{call_id}"))
        ).scalar_one()
        assert ledger.amount == -call.credits and (ledger.note or "").startswith("voz")
    assert await get_storage().exists(call.recording_key)

    rec = await api_client.get(f"/api/v1/voice/calls/{call_id}/recording")
    assert rec.status_code == 200 and rec.headers["content-type"] == "audio/mpeg" and len(rec.content) > 100
    deleted = await api_client.delete(f"/api/v1/voice/calls/{call_id}/recording")
    assert deleted.status_code == 204
    assert not await get_storage().exists(call.recording_key)
    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action))).scalars())
    assert {"voice.session_started", "voice.recording_accessed", "voice.recording_deleted"} <= actions
    detail = (await api_client.get(f"/api/v1/voice/calls/{call_id}")).json()
    assert detail["has_recording"] is False and Decimal(detail["voice_cost_usd"]) > 0


async def test_filler_phrase_while_a_tool_runs(
    api_client: httpx.AsyncClient,
    voice_server,  # type: ignore[no-untyped-def]
    runtime: Harness,
    model,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from messer_voice.config import get_voice_settings

    monkeypatch.setattr(get_voice_settings(), "messer_voice_filler_delay_secs", 0.2)
    use_fake_speech(monkeypatch)
    model(anthropic_tool_then_text("El IVA de 120 euros son 25,20 euros.", delay_s=2.0))
    pid = await setup_agent(api_client, tools=[{"type": "builtin", "key": "calculator"}])
    session = (await api_client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "recepcion"})).json()
    frames: list[dict] = []
    async with websockets.connect(session["ws_url"]) as ws:
        await recv_until(ws, "session_started", into=frames)
        await ws.send(say("¿Cuánto es el IVA de 120 euros?"))
        status = await recv_until(ws, "agent_status", into=frames)
        assert "calculator" in status["text"]
        filler = await recv_until(ws, "filler", into=frames)
        assert filler["text"] in {"Un momento, lo compruebo.", "Déjame mirarlo.", "Dame un segundo.", "Lo consulto ahora mismo."}
        done = await recv_until(ws, "agent_text_done", into=frames)
        assert "25,20" in done["text"]
        metrics = await recv_until(ws, "metrics", into=frames)
        assert metrics["metrics"]["filler_spoken"] is True
        await ws.send(json.dumps({"type": "hangup"}))
        await recv_until(ws, "call_summary", into=frames)
    async with system_session() as s:
        call = await s.get(VoiceCall, uuid.UUID(session["call_id"]))
        assert call is not None and call.turns[0]["tools"] == ["calculator"]
        assert any(e.get("filler") for e in call.transcript)
