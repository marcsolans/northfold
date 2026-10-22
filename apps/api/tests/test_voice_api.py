"""/api/v1/voice: session tickets, permissions and plan gates, dictation, voices, phone numbers, LiveKit."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import jwt
import pytest
from sqlalchemy import select, update

from messer_common.db import system_session
from messer_common.db.models import AuditLog, Conversation, Membership, Org, Subscription, User
from messer_common.db.models.voice import VoiceCall, VoicePhoneNumber
from messer_common.security import verify_signed_payload
from messer_common.settings import get_settings

EMAIL = "lucia@acme.example"


async def _setup(client: httpx.AsyncClient, *, voice_enabled: bool = True) -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": EMAIL, "password": "Contrasena123", "name": "Lucía"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Clínica"})).json()["id"]
    agent = (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "citas"})).json()
    cfg = agent["config"]
    cfg["voice"] = {"enabled": voice_enabled, "voice": "", "language": "es", "greeting": "Clínica Acme, ¿dígame?"}
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/citas/config", json=cfg)).status_code == 200
    return str(pid)


async def _org_id() -> uuid.UUID:
    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == EMAIL))).scalar_one()
        return (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalar_one()


async def _business() -> None:
    org_id = await _org_id()
    async with system_session() as s:
        await s.execute(update(Subscription).where(Subscription.org_id == org_id).values(plan_id="business"))
        await s.execute(update(Org).where(Org.id == org_id).values(plan_id="business"))


async def _actions() -> set[str]:
    async with system_session() as s:
        return set((await s.execute(select(AuditLog.action))).scalars())


@pytest.fixture
def fake_providers(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Twilio, ElevenLabs and the voice service's internal API, answered by a recording mock."""
    from messer_api.services import voice as svc

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if "/AvailablePhoneNumbers/ES/Local.json" in path:
            return httpx.Response(
                200,
                json={
                    "available_phone_numbers": [
                        {
                            "phone_number": "+34910111222",
                            "friendly_name": "Madrid",
                            "locality": "Madrid",
                            "iso_country": "ES",
                            "capabilities": {"voice": True},
                        }
                    ]
                },
            )
        if path.endswith("/IncomingPhoneNumbers.json") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "incoming_phone_numbers": [
                        {"sid": "PN1", "phone_number": "+34910111222"},
                        {"sid": "PN2", "phone_number": "+34910333444"},
                    ]
                },
            )
        if path.endswith("/IncomingPhoneNumbers.json") and request.method == "POST":
            return httpx.Response(201, json={"sid": "PN9", "phone_number": "+34910111222", "friendly_name": "Madrid"})
        if "/IncomingPhoneNumbers/" in path:
            return httpx.Response(204 if request.method == "DELETE" else 200, json={"sid": "PN9"})
        if path.endswith("/Calls.json"):
            return httpx.Response(400, json={"message": "The number is unverified"})
        if path == "/v1/voices":
            return httpx.Response(
                200,
                json={
                    "voices": [{"voice_id": "v1", "name": "Lucía", "labels": {"language": "es", "gender": "female"}}]
                },
            )
        if path == "/internal/v1/livekit/join":
            return httpx.Response(200, json={"room": "r", "status": "joined"})
        return httpx.Response(404, json={"message": f"unexpected {request.method} {path}"})

    monkeypatch.setattr(svc, "transport", httpx.MockTransport(handler))
    return requests


async def test_browser_session_tickets_and_gates(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    pid = await _setup(client, voice_enabled=False)
    status = (await client.get("/api/v1/voice/status")).json()
    assert status["mode"] == "text" and status["dictation"]["mode"] == "browser"
    assert {m["feature"] for m in status["missing"]} == {"audio", "phone", "livekit"}

    res = await client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "citas"})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["mode"] == "text" and body["greeting"] == "Clínica Acme, ¿dígame?" and body["expires_in"] == 60
    assert body["ws_url"].startswith(get_settings().messer_voice_url.replace("http", "ws") + "/v1/session?ticket=")
    claims = verify_signed_payload(body["ticket"])
    assert claims["typ"] == "voice_ticket" and claims["purpose"] == "session" and claims["call"] == body["call_id"]
    async with system_session() as s:
        call = await s.get(VoiceCall, uuid.UUID(body["call_id"]))
        assert call is not None and call.status == "pending" and call.transport == "browser"
        conv = await s.get(Conversation, call.conversation_id)
        assert conv is not None and conv.provider == "voice" and conv.channel_key == f"voice:{call.id}"
    assert "voice.session_started" in await _actions()

    # Production calls need the plan feature, the agent's voice switch and a deployment.
    prod = await client.post(
        "/api/v1/voice/sessions", json={"project_id": pid, "workforce": "citas", "environment": "production"}
    )
    assert prod.status_code == 402 and prod.json()["error"]["details"]["feature"] == "voice"
    await _business()
    prod = await client.post(
        "/api/v1/voice/sessions", json={"project_id": pid, "workforce": "citas", "environment": "production"}
    )
    assert prod.status_code == 400 and prod.json()["error"]["code"] == "voice_disabled"
    audio = await client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "citas", "mode": "audio"})
    assert audio.status_code == 409 and audio.json()["error"]["code"] == "audio_unavailable"
    missing = await client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "nadie"})
    assert missing.status_code == 404

    # Continuing someone else's conversation is refused; viewers cannot start calls.
    other = await client.post(
        "/api/v1/voice/sessions",
        json={"project_id": pid, "workforce": "citas", "conversation_id": str(uuid.uuid4())},
    )
    assert other.status_code == 404
    viewer = await make_user(email="viewer@acme.example")
    async with system_session() as s:
        s.add(Membership(org_id=await _org_id(), user_id=viewer.id, role="viewer"))
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": "viewer@acme.example", "password": "Sup3rSecret!pass"})
    ).status_code == 200
    client.headers["X-Messer-Org"] = str(await _org_id())
    denied = await client.post("/api/v1/voice/sessions", json={"project_id": pid, "workforce": "citas"})
    assert denied.status_code == 403
    calls = (await client.get("/api/v1/voice/calls", params={"project_id": pid})).json()
    assert calls["total"] == 1 and calls["items"][0]["status"] == "pending"


async def test_dictation_and_voices(
    client: httpx.AsyncClient, fake_providers: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _setup(client)
    assert (await client.post("/api/v1/voice/transcriptions", json={})).json()["mode"] == "browser"
    assert (await client.get("/api/v1/voice/voices")).json() == {"provider": "browser", "default": None, "items": []}
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg")
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "el")
    dictation = (await client.post("/api/v1/voice/transcriptions", json={"language": "es"})).json()
    assert dictation["mode"] == "server" and dictation["stt"].startswith("deepgram/")
    assert verify_signed_payload(dictation["ticket"])["purpose"] == "transcribe"
    voices = (await client.get("/api/v1/voice/voices", params={"language": "es"})).json()
    assert voices["provider"] == "elevenlabs" and voices["items"][0]["id"] == "elevenlabs:v1"
    assert (await client.get("/api/v1/voice/status")).json()["mode"] == "audio"


async def test_phone_numbers_lifecycle(
    client: httpx.AsyncClient, fake_providers: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await _setup(client)
    unconfigured = await client.get("/api/v1/voice/numbers/available", params={"provider": "twilio"})
    assert unconfigured.status_code == 409 and unconfigured.json()["error"]["code"] == "twilio_not_configured"
    monkeypatch.setattr(get_settings(), "twilio_account_sid", "AC1")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "tok")
    available = (await client.get("/api/v1/voice/numbers/available", params={"provider": "twilio"})).json()
    assert available[0]["number"] == "+34910111222" and available[0]["locality"] == "Madrid"

    payload: dict[str, Any] = {
        "project_id": pid,
        "provider": "twilio",
        "number": "+34910111222",
        "buy": True,
        "workforce": "citas",
        "record_calls": True,
        "environment": "development",
    }
    gated = await client.post("/api/v1/voice/numbers", json=payload)
    assert gated.status_code == 402
    await _business()
    res = await client.post("/api/v1/voice/numbers", json=payload)
    assert res.status_code == 201, res.text
    number = res.json()
    assert number["purchased"] is True and number["record_calls"] is True and number["status"] == "active"
    buy = next(r for r in fake_providers if r.url.path.endswith("/IncomingPhoneNumbers.json") and r.method == "POST")
    assert b"PhoneNumber=%2B34910111222" in buy.content and b"VoiceUrl=" in buy.content
    duplicate = await client.post("/api/v1/voice/numbers", json=payload)
    assert duplicate.status_code == 409

    owned = (await client.get("/api/v1/voice/numbers/owned", params={"provider": "twilio"})).json()
    assert {n["number"]: n["assigned"] for n in owned} == {"+34910111222": True, "+34910333444": False}
    listed = (await client.get("/api/v1/voice/numbers", params={"project_id": pid})).json()
    assert [n["number"] for n in listed] == ["+34910111222"]

    patched = await client.patch(
        f"/api/v1/voice/numbers/{number['id']}", json={"label": "Recepción", "greeting": "Hola"}
    )
    assert patched.status_code == 200 and patched.json()["label"] == "Recepción"
    wrong = await client.patch(f"/api/v1/voice/numbers/{number['id']}", json={"workforce": "nadie"})
    assert wrong.status_code == 404

    prod = await client.patch(f"/api/v1/voice/numbers/{number['id']}", json={"environment": "production"})
    assert prod.status_code == 200
    undeployed = await client.post("/api/v1/voice/calls", json={"phone_number_id": number["id"], "to": "+34600000001"})
    assert undeployed.status_code == 409 and undeployed.json()["error"]["code"] == "not_deployed"
    await client.patch(f"/api/v1/voice/numbers/{number['id']}", json={"environment": "development"})
    # Calls need hosted speech; a failed dial leaves a failed call record and surfaces the provider's message.
    no_audio = await client.post("/api/v1/voice/calls", json={"phone_number_id": number["id"], "to": "+34600000001"})
    assert no_audio.status_code == 409 and no_audio.json()["error"]["code"] == "audio_unavailable"
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg")
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "el")
    failed = await client.post("/api/v1/voice/calls", json={"phone_number_id": number["id"], "to": "+34600000001"})
    assert failed.status_code == 502 and "unverified" in failed.json()["error"]["message"]
    async with system_session() as s:
        call = (await s.execute(select(VoiceCall).where(VoiceCall.direction == "outbound"))).scalar_one()
        assert call.status == "failed" and call.error and call.channel == "phone"

    removed = await client.delete(f"/api/v1/voice/numbers/{number['id']}", params={"release": "true"})
    assert removed.status_code == 204
    assert any(r.method == "DELETE" and r.url.path.endswith("/IncomingPhoneNumbers/PN9.json") for r in fake_providers)
    async with system_session() as s:
        assert (await s.execute(select(VoicePhoneNumber))).first() is None
    assert {"voice.number_purchased", "voice.number_updated", "voice.call_placed", "voice.number_released"} <= (
        await _actions()
    )


async def test_livekit_rooms(
    client: httpx.AsyncClient, fake_providers: list[httpx.Request], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await _setup(client)
    await _business()
    body = {"project_id": pid, "workforce": "citas"}
    off = await client.post("/api/v1/voice/livekit/sessions", json=body)
    assert off.status_code == 409 and off.json()["error"]["code"] == "livekit_not_configured"
    monkeypatch.setattr(get_settings(), "livekit_url", "wss://lk.example")
    monkeypatch.setattr(get_settings(), "livekit_api_key", "APIk")
    monkeypatch.setattr(get_settings(), "livekit_api_secret", "lk-secret-lk-secret-lk-secret-123")
    no_audio = await client.post("/api/v1/voice/livekit/sessions", json=body)
    assert no_audio.status_code == 409 and no_audio.json()["error"]["code"] == "audio_unavailable"
    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg")
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "el")
    res = await client.post("/api/v1/voice/livekit/sessions", json=body)
    assert res.status_code == 201, res.text
    room = res.json()
    claims = jwt.decode(room["token"], "lk-secret-lk-secret-lk-secret-123", algorithms=["HS256"])
    assert claims["video"]["room"] == room["room"] == f"messer-{uuid.UUID(room['call_id']).hex}"
    assert room["url"] == "wss://lk.example"
    join = next(r for r in fake_providers if r.url.path == "/internal/v1/livekit/join")
    assert join.headers["authorization"] == f"Bearer {get_settings().service_token}"
    async with system_session() as s:
        call = await s.get(VoiceCall, uuid.UUID(room["call_id"]))
        assert call is not None and call.transport == "livekit"
