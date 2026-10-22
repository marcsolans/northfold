"""Units of the voice service: prices, provider choice and residency, tickets, text mode, dictation, internals."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import httpx
import jwt
import pytest
import websockets
from sqlalchemy import select
from voice_support import ScriptedSTT, recv_until, say

from messer_common.db import system_session
from messer_common.db.models import CreditLedger
from messer_common.residency import Residency
from messer_common.settings import get_settings
from messer_voice import providers, tickets
from messer_voice.pricing import CallUsage, speech_options, telephony_rate
from messer_voice.providers import BrowserTTS, SpokenPlaybackTracker, resolve_voice, select_pipeline


def _residency(mode: str) -> Residency:
    return Residency(org_id=uuid.uuid4(), mode=mode, region="eu-central-1")  # type: ignore[arg-type]


def test_voice_prices_come_from_models_yaml() -> None:
    stt = speech_options("stt")
    tts = speech_options("tts")
    assert [o.provider for o in stt][:2] == ["deepgram", "elevenlabs"]
    assert stt[0].price > 0 and tts[0].price > 0
    assert telephony_rate("twilio", "outbound") > telephony_rate("twilio", "inbound") > 0
    usage = CallUsage(stt=stt[0], tts=tts[0], telephony_provider="twilio", direction="inbound")
    usage.add_stt_audio(16_000 * 2 * 60, 16_000)  # one minute of audio
    usage.add_tts_text("x" * 1000)
    usage.line_seconds = 120
    costs = usage.costs()
    assert costs["stt"] == stt[0].price.quantize(Decimal("0.000001"))
    assert costs["tts"] == tts[0].price.quantize(Decimal("0.000001"))
    assert costs["telephony"] == (2 * telephony_rate("twilio", "inbound")).quantize(Decimal("0.000001"))
    assert costs["total"] == costs["stt"] + costs["tts"] + costs["telephony"]
    assert usage.as_dict()["stt"]["seconds"] == 60.0
    assert CallUsage().costs()["total"] == 0


def test_provider_choice_follows_keys_and_residency(monkeypatch: pytest.MonkeyPatch) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "deepgram_api_key", "")
    monkeypatch.setattr(s, "elevenlabs_api_key", "")
    monkeypatch.setattr(s, "openai_api_key", "")
    assert select_pipeline(None) is None  # demo mode: the browser speaks
    monkeypatch.setattr(s, "openai_api_key", "sk-openai")
    pipeline = select_pipeline(_residency("standard"))
    assert pipeline is not None and pipeline.stt.provider == "openai" and pipeline.tts.provider == "openai"
    # eu_strict never sends audio to a provider without an EU region.
    assert select_pipeline(_residency("eu_strict")) is None
    monkeypatch.setattr(s, "deepgram_api_key", "dg")
    monkeypatch.setattr(s, "elevenlabs_api_key", "el")
    monkeypatch.setattr(s, "messer_voice_region", "")
    assert select_pipeline(_residency("eu_strict")) is None
    monkeypatch.setattr(s, "messer_voice_region", "eu")
    strict = select_pipeline(_residency("eu_strict"))
    assert strict is not None and strict.stt.provider == "deepgram" and strict.tts.provider == "elevenlabs"
    stt, cfg = providers.build_stt(strict.stt, language="es-ES")
    assert type(stt).__name__ == "DeepgramFluxSTT" and cfg.language == "es"
    assert cfg.extra["stt_host"] == "api.eu.deepgram.com"
    tts, out = providers.build_tts(strict.tts, language="es", voice="elevenlabs:abc123")
    assert tts.provider_id == "elevenlabs" and out.voice == "abc123" and out.extra["tts_host"]


def test_agent_voice_choice_only_applies_to_its_provider() -> None:
    deepgram = next(o for o in speech_options("tts") if o.provider == "deepgram")
    assert resolve_voice(deepgram, language="es", voice="elevenlabs:abc") == "aura-2-celeste-es"
    assert resolve_voice(deepgram, language="en", voice="") == "aura-2-thalia-en"
    assert resolve_voice(deepgram, language="es", voice="deepgram:aura-2-estrella-es") == "aura-2-estrella-es"


async def test_browser_tts_paces_segments_and_tracker_trusts_the_browser() -> None:
    from messer.voice.providers import AudioOutputConfig

    segments: list[dict] = []
    tts = BrowserTTS(on_segment=segments.append)
    await tts.connect(AudioOutputConfig(sample_rate=16_000))
    audio = b"".join([chunk async for chunk in tts.synthesize("Hola, ¿en qué puedo ayudarte?")])
    assert segments[0]["text"] == "Hola, ¿en qué puedo ayudarte?" and segments[0]["segment"] == 1
    assert len(audio) == int(16_000 * segments[0]["duration_ms"] / 1000) * 2 and not any(audio)

    now = [100.0]
    tracker = SpokenPlaybackTracker(bytes_per_second=32_000, clock=lambda: now[0])
    tracker.on_audio_emitted(64_000)  # two seconds scheduled
    assert tracker.is_playing
    tracker.on_playback_ack(500)
    now[0] += 2.5  # the estimate has run out but the browser is still speaking
    tracker.on_playback_ack(1500)
    assert tracker.is_playing
    tracker.on_speech_done()
    assert not tracker.is_playing


async def test_tickets_are_typed_signed_and_single_use() -> None:
    call_id = uuid.uuid4()
    token = tickets.mint("session", ttl_s=30, call_id=call_id, org=str(uuid.uuid4()))
    with pytest.raises(tickets.TicketError):
        tickets.decode(token, "telephony")
    with pytest.raises(tickets.TicketError):
        tickets.decode(token + "x", "session")
    expired = tickets.mint("session", ttl_s=-10, call_id=call_id)
    with pytest.raises(tickets.TicketError):
        tickets.decode(expired, "session")
    ticket = await tickets.redeem(token, "session")
    assert ticket.call_id == call_id
    with pytest.raises(tickets.TicketError, match="already used"):
        await tickets.redeem(token, "session")
    # The API mints the same format.
    from messer_api.services.voice import mint_ticket

    api_token = mint_ticket("session", ttl_s=30, call_id=call_id)
    assert (await tickets.redeem(api_token, "session")).call_id == call_id


async def test_internal_endpoints_need_the_service_token(voice_server) -> None:  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(base_url=voice_server.base_url) as anon:
        assert (await anon.get("/internal/v1/status")).status_code == 401
        assert (await anon.get("/internal/v1/status", headers={"Authorization": "Bearer nope"})).status_code == 401
        assert (await anon.get("/health")).json()["status"] == "ok"
    res = await voice_server.client.get("/internal/v1/status")
    assert res.status_code == 200 and res.json()["sessions"] == 0
    join = await voice_server.client.post("/internal/v1/livekit/join", json={"call_id": str(uuid.uuid4())})
    assert join.status_code == 503  # LiveKit not configured


def test_livekit_tokens_grant_one_room(monkeypatch: pytest.MonkeyPatch) -> None:
    from messer_voice import livekit

    monkeypatch.setattr(get_settings(), "livekit_api_key", "APIkey")
    monkeypatch.setattr(get_settings(), "livekit_api_secret", "secret-secret-secret-secret-secret")
    token = livekit.access_token("agent-1", "messer-abc", name="recepcion", agent=True)
    claims = jwt.decode(token, "secret-secret-secret-secret-secret", algorithms=["HS256"])
    assert claims["iss"] == "APIkey" and claims["sub"] == "agent-1" and claims["kind"] == "agent"
    assert claims["video"] == {
        "room": "messer-abc",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }


async def test_dictation_transcribes_and_charges(
    voice_server,
    make_org,
    monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
) -> None:
    from messer_voice import transcribe

    org, _owner = await make_org()
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg-test")
    fakes: list[ScriptedSTT] = []

    def fake_stt(option, *, language):  # type: ignore[no-untyped-def]
        from messer.voice.providers import AudioInputConfig

        stt = ScriptedSTT()
        fakes.append(stt)
        return stt, AudioInputConfig(language=language)

    monkeypatch.setattr(transcribe, "build_stt", fake_stt)
    refused = tickets.mint("session", ttl_s=30, org=str(org.id))
    async with websockets.connect(f"{voice_server.ws_url}/v1/transcribe?ticket={refused}") as ws:
        with pytest.raises(websockets.ConnectionClosed) as closed:
            await ws.recv()
        assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401
    token = tickets.mint("transcribe", ttl_s=30, org=str(org.id), language="es")
    async with websockets.connect(f"{voice_server.ws_url}/v1/transcribe?ticket={token}") as ws:
        ready = await recv_until(ws, "ready")
        assert ready["provider"] == "deepgram"
        await ws.send(say("Quiero un asistente para mis facturas"))
        for _ in range(20):
            await ws.send(b"\x00" * 3200)
        committed = await recv_until(ws, "transcript_committed")
        assert committed["text"] == "Quiero un asistente para mis facturas"
        await ws.send(json.dumps({"type": "stop"}))
        done = await recv_until(ws, "done")
        assert done["text"] == "Quiero un asistente para mis facturas"
    assert fakes[0].closed
    async with system_session() as s:
        entry = (
            await s.execute(select(CreditLedger).where(CreditLedger.org_id == org.id, CreditLedger.kind == "usage"))
        ).scalar_one()
        assert (entry.note or "").startswith("voz · dictado") and entry.amount < 0
