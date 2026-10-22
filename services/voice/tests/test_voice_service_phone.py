"""Phone calls: Twilio (signed TwiML webhook, Media Streams, outbound) and Telnyx (signed Call Control, streaming)."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import select
from voice_support import anthropic_text, setup_agent, upgrade_plan, use_fake_speech

from messer_common.db import system_session
from messer_common.db.models import Conversation, Membership, User
from messer_common.db.models.voice import VoiceCall, VoicePhoneNumber
from messer_common.settings import get_settings
from messer_runtime.testing import Harness
from messer_voice.telephony.common import twilio_signature

TOKEN = "twilio-auth-token-test"
EMAIL = "marta@acme.example"
ULAW_SILENCE_FRAME = base64.b64encode(b"\xff" * 160).decode()


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    gateway.anthropic_transport = httpx.MockTransport(anthropic_text("Buenos días, le ayudo con su factura."))
    yield
    gateway.anthropic_transport = None


@pytest.fixture
def twilio(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Twilio credentials plus a fake Twilio REST API recording every request."""
    from messer_api.services import voice as api_voice

    monkeypatch.setattr(get_settings(), "twilio_account_sid", "AC123")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", TOKEN)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/IncomingPhoneNumbers/PN123.json"):
            return httpx.Response(200, json={"sid": "PN123", "phone_number": "+34910000000", "friendly_name": "Madrid"})
        if path.endswith("/Calls.json"):
            return httpx.Response(201, json={"sid": f"CA-out-{len(requests)}", "status": "queued"})
        if "/Calls/" in path:
            return httpx.Response(200, json={"sid": path.rsplit("/", 1)[-1][:-5], "status": "completed"})
        return httpx.Response(404, json={"message": "not found"})

    monkeypatch.setattr(api_voice, "transport", httpx.MockTransport(handler))
    return requests


async def _assign_number(api_client: httpx.AsyncClient, pid: str, *, provider: str = "twilio") -> dict[str, Any]:
    res = await api_client.post(
        "/api/v1/voice/numbers",
        json={
            "project_id": pid,
            "provider": provider,
            "number": "+34 910 000 000",
            "external_id": "PN123",
            "workforce": "recepcion",
            "environment": "development",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _signed(url: str, params: dict[str, str]) -> dict[str, str]:
    return {"X-Twilio-Signature": twilio_signature(url, params, TOKEN)}


def _twiml_stream(xml: str) -> tuple[str, str, str]:
    url = re.search(r'<Stream url="([^"]+)"', xml)
    call_id = re.search(r'name="call_id" value="([^"]+)"', xml)
    ticket = re.search(r'name="ticket" value="([^"]+)"', xml)
    assert url and call_id and ticket, xml
    return url.group(1), call_id.group(1), ticket.group(1)


async def _wait_turn(call_id: uuid.UUID, timeout_s: float = 60) -> VoiceCall:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with system_session() as s:
            call = await s.get(VoiceCall, call_id)
        if call is not None and any(t.get("status") == "success" for t in call.turns or []):
            return call
        await asyncio.sleep(0.2)
    raise AssertionError("the turn never finished")


async def _phone_call(ws_url: str, start: dict[str, Any], call_id: uuid.UUID, *, telnyx: bool = False) -> list[dict]:
    """Play the carrier: start, caller audio, echo marks; hang up once the agent has answered."""
    received: list[dict] = []
    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"event": "connected"}))
        await ws.send(json.dumps(start))

        async def reader() -> None:
            async for raw in ws:
                frame = json.loads(raw)
                received.append(frame)
                if frame.get("event") == "mark":
                    await ws.send(json.dumps({"event": "mark", "mark": frame["mark"]} if telnyx else frame))

        task = asyncio.create_task(reader())
        for _ in range(40):
            media: dict[str, Any] = {"event": "media", "media": {"track": "inbound", "payload": ULAW_SILENCE_FRAME}}
            if not telnyx:
                media["streamSid"] = "MZ1"
            await ws.send(json.dumps(media))
            await asyncio.sleep(0.01)
        await _wait_turn(call_id)
        for _ in range(100):
            if any(f.get("event") == "media" for f in received):
                break
            await asyncio.sleep(0.05)
        await ws.send(json.dumps({"event": "stop", "streamSid": "MZ1"}))
        await asyncio.wait_for(task, timeout=60)
    return received


async def _final_call(call_id: uuid.UUID, timeout_s: float = 30) -> VoiceCall:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        async with system_session() as s:
            call = await s.get(VoiceCall, call_id)
        if call is not None and call.status in ("completed", "failed", "no_answer", "busy", "canceled"):
            return call
        await asyncio.sleep(0.1)
    raise AssertionError("the call never ended")


async def test_twilio_inbound_call_through_media_streams(
    api_client: httpx.AsyncClient,
    voice_server,  # type: ignore[no-untyped-def]
    runtime: Harness,
    model,  # type: ignore[no-untyped-def]
    twilio,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fake_speech(monkeypatch, script=["Hola, llamo por una factura"])
    pid = await setup_agent(api_client, email=EMAIL)
    blocked = await api_client.post(
        "/api/v1/voice/numbers",
        json={"project_id": pid, "provider": "twilio", "number": "+34910000000", "workforce": "recepcion"},
    )
    assert blocked.status_code == 402 and blocked.json()["error"]["details"]["feature"] == "voice"
    await upgrade_plan(EMAIL)
    number = await _assign_number(api_client, pid)
    assert number["number"] == "+34910000000" and number["provider"] == "twilio"
    configure = next(r for r in twilio if r.url.path.endswith("/IncomingPhoneNumbers/PN123.json"))
    assert parse_qs(configure.content.decode())["VoiceUrl"] == [f"{voice_server.base_url}/telephony/twilio/voice"]

    url = f"{voice_server.base_url}/telephony/twilio/voice"
    params = {"CallSid": "CA1", "From": "+34600111222", "To": "+34910000000", "Direction": "inbound"}
    unsigned = await voice_server.client.post(url, data=params)
    assert unsigned.status_code == 403
    forged = await voice_server.client.post(url, data=params, headers={"X-Twilio-Signature": "bad"})
    assert forged.status_code == 403
    res = await voice_server.client.post(url, data=params, headers=_signed(url, params))
    assert res.status_code == 200 and res.headers["content-type"].startswith("application/xml")
    stream_url, call_id_raw, ticket = _twiml_stream(res.text)
    assert stream_url == f"{voice_server.ws_url}/telephony/twilio/media"
    call_id = uuid.UUID(call_id_raw)

    start = {
        "event": "start",
        "streamSid": "MZ1",
        "start": {
            "callSid": "CA1",
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
            "customParameters": {"call_id": call_id_raw, "ticket": ticket},
        },
    }
    received = await _phone_call(stream_url, start, call_id)
    assert any(f.get("event") == "media" and f.get("streamSid") == "MZ1" for f in received)
    assert any(f.get("event") == "mark" for f in received)

    call = await _final_call(call_id)
    assert call.status == "completed" and call.transport == "twilio" and call.channel == "phone"
    assert call.from_number == "+34600111222" and call.external_call_id == "CA1"
    assert call.turns[0]["user_text"] == "Hola, llamo por una factura" and call.turns[0]["status"] == "success"
    assert call.usage["telephony"]["provider"] == "twilio" and call.usage["telephony"]["seconds"] > 0
    async with system_session() as s:
        conv = await s.get(Conversation, call.conversation_id)
        assert conv is not None and conv.provider == "phone" and conv.external_user_id == "+34600111222"
        assert [m["role"] for m in conv.messages] == ["user", "assistant"]

    # A second call from the same number continues the same conversation (memory across calls).
    params2 = {**params, "CallSid": "CA2"}
    res2 = await voice_server.client.post(url, data=params2, headers=_signed(url, params2))
    _, call2_raw, _ = _twiml_stream(res2.text)
    async with system_session() as s:
        call2 = await s.get(VoiceCall, uuid.UUID(call2_raw))
        assert call2 is not None and call2.conversation_id == call.conversation_id
    status_url = f"{voice_server.base_url}/telephony/twilio/status?call={call2_raw}"
    status_params = {"CallSid": "CA2", "CallStatus": "no-answer"}
    cb = await voice_server.client.post(status_url, data=status_params, headers=_signed(status_url, status_params))
    assert cb.status_code == 204
    assert (await _final_call(uuid.UUID(call2_raw))).status == "no_answer"

    # An unknown number is told the assistant is unavailable.
    params3 = {**params, "CallSid": "CA3", "To": "+34999999999"}
    res3 = await voice_server.client.post(url, data=params3, headers=_signed(url, params3))
    assert "<Say" in res3.text and "<Hangup/>" in res3.text


async def test_twilio_outbound_call(
    api_client: httpx.AsyncClient,
    voice_server,  # type: ignore[no-untyped-def]
    runtime: Harness,
    twilio,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_fake_speech(monkeypatch)
    pid = await setup_agent(api_client, email=EMAIL)
    await upgrade_plan(EMAIL)
    number = await _assign_number(api_client, pid)
    bad = await api_client.post("/api/v1/voice/calls", json={"phone_number_id": number["id"], "to": "600"})
    assert bad.status_code == 422 or bad.json()["error"]["code"] == "invalid_phone_number"
    res = await api_client.post(
        "/api/v1/voice/calls", json={"phone_number_id": number["id"], "to": "+34 600 333 444", "greeting": "Hola"}
    )
    assert res.status_code == 201, res.text
    call = res.json()
    assert call["status"] == "ringing" and call["direction"] == "outbound" and call["to_number"] == "+34600333444"
    dial = next(r for r in twilio if r.url.path.endswith("/Calls.json"))
    form = parse_qs(dial.content.decode())
    assert form["To"] == ["+34600333444"] and form["From"] == ["+34910000000"]
    assert form["Url"] == [f"{voice_server.base_url}/telephony/twilio/voice?call={call['id']}"]
    async with system_session() as s:
        row = await s.get(VoiceCall, uuid.UUID(call["id"]))
        assert row is not None and row.external_call_id
        sid = row.external_call_id

    url = form["Url"][0]
    wrong = {"CallSid": "CA-someone-else", "From": "+34910000000", "To": "+34600333444"}
    assert (await voice_server.client.post(url, data=wrong, headers=_signed(url, wrong))).status_code == 403
    params = {**wrong, "CallSid": sid}
    res = await voice_server.client.post(url, data=params, headers=_signed(url, params))
    _, call_id_raw, _ = _twiml_stream(res.text)
    assert call_id_raw == call["id"]
    hang = await api_client.post(f"/api/v1/voice/calls/{call['id']}/hangup")
    assert hang.status_code == 200, hang.text
    hang_request = twilio[-1]
    assert hang_request.url.path.endswith(f"/Calls/{sid}.json") and parse_qs(hang_request.content.decode()) == {
        "Status": ["completed"]
    }


async def test_telnyx_call_control_and_media(
    api_client: httpx.AsyncClient,
    voice_server,  # type: ignore[no-untyped-def]
    runtime: Harness,
    model,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from messer_voice.config import get_voice_settings
    from messer_voice.telephony import telnyx

    use_fake_speech(monkeypatch, script=["Quiero cambiar mi dirección"])
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    monkeypatch.setattr(get_settings(), "telnyx_api_key", "KEY-test")
    monkeypatch.setattr(get_voice_settings(), "telnyx_public_key", public)
    commands: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        commands.append(request)
        return httpx.Response(200, json={"data": {"result": "ok"}})

    monkeypatch.setattr(telnyx, "transport", httpx.MockTransport(handler))
    pid = await setup_agent(api_client, email=EMAIL)
    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == EMAIL))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalar_one()
        s.add(
            VoicePhoneNumber(
                org_id=org_id,
                project_id=uuid.UUID(pid),
                workforce_name="recepcion",
                environment="development",
                provider="telnyx",
                number="+34930000000",
                external_id="num-1",
            )
        )

    def signed(body: bytes) -> dict[str, str]:
        ts = str(int(time.time()))
        sig = base64.b64encode(key.sign(f"{ts}|".encode() + body)).decode()
        return {"telnyx-timestamp": ts, "telnyx-signature-ed25519": sig, "content-type": "application/json"}

    url = f"{voice_server.base_url}/telephony/telnyx/webhook"
    event = {
        "data": {
            "event_type": "call.initiated",
            "payload": {
                "call_control_id": "cc-1",
                "direction": "incoming",
                "from": "+34611000000",
                "to": "+34930000000",
            },
        }
    }
    body = json.dumps(event).encode()
    assert (
        await voice_server.client.post(url, content=body, headers={"content-type": "application/json"})
    ).status_code == 403
    stale = signed(body) | {"telnyx-timestamp": str(int(time.time()) - 3600)}
    assert (await voice_server.client.post(url, content=body, headers=stale)).status_code == 403
    res = await voice_server.client.post(url, content=body, headers=signed(body))
    assert res.status_code == 204
    answer = next(r for r in commands if r.url.path == "/v2/calls/cc-1/actions/answer")
    options = json.loads(answer.content)
    assert options["stream_bidirectional_mode"] == "rtp" and options["stream_bidirectional_codec"] == "PCMU"
    stream = urlparse(options["stream_url"])
    call_id = uuid.UUID(parse_qs(stream.query)["call"][0])
    start = {
        "event": "start",
        "stream_id": "st-1",
        "start": {"call_control_id": "cc-1", "media_format": {"encoding": "PCMU", "sample_rate": 8000}},
    }
    received = await _phone_call(options["stream_url"], start, call_id, telnyx=True)
    assert any(f.get("event") == "media" for f in received)
    call = await _final_call(call_id)
    assert call.status == "completed" and call.transport == "telnyx" and call.from_number == "+34611000000"
    assert call.turns[0]["user_text"] == "Quiero cambiar mi dirección"

    hangup = {"data": {"event_type": "call.hangup", "payload": {"call_control_id": "cc-unknown"}}}
    hb = json.dumps(hangup).encode()
    assert (await voice_server.client.post(url, content=hb, headers=signed(hb))).status_code == 204
