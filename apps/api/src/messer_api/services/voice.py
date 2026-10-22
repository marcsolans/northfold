"""Voice (control plane): session tickets, call records, phone numbers (Twilio/Telnyx), LiveKit rooms.

Live audio never touches the API: the browser, the carriers and LiveKit talk to the voice service
(``services/voice``), which drives the agent through the runtime. The API authorizes and creates calls, mints the
short-lived single-use tickets the voice service redeems, manages the deployment's phone numbers through the
providers' REST APIs and places outbound calls.

Provider choice mirrors the voice service: audio mode needs a hosted STT *and* TTS from ``config/models.yaml``
(``voice.stt`` / ``voice.tts``) with a configured key that the organization's residency allows; otherwise browser
sessions run in text mode (the browser's Web Speech API does STT and TTS).
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import Conversation, Project, Workforce
from messer_common.db.models.voice import VoiceCall, VoicePhoneNumber
from messer_common.logging import get_logger
from messer_common.models_config import load_models_config
from messer_common.residency import Residency, allowed_provider
from messer_common.security import random_token, sign_payload
from messer_common.settings import REPO_ROOT, get_settings

from ..errors import ApiError

log = get_logger("messer.api.voice")

# Test hook: route provider and voice-service HTTP calls through a custom transport.
transport: httpx.AsyncBaseTransport | None = None

TICKET_TTL_S = 60
PHONE_TICKET_TTL_S = 300
TWILIO_API = "https://api.twilio.com/2010-04-01"
TELNYX_API = "https://api.telnyx.com/v2"
ELEVENLABS_API = "https://api.elevenlabs.io/v1"
OPENAI_VOICES = [
    "alloy",
    "ash",
    "ballad",
    "cedar",
    "coral",
    "echo",
    "fable",
    "marin",
    "nova",
    "onyx",
    "sage",
    "shimmer",
]
PhoneProvider = Literal["twilio", "telnyx"]


class VoiceSettings(BaseSettings):
    """Voice variables the API needs besides the shared settings (same names as the voice service)."""

    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    messer_voice_public_url: str = ""
    telnyx_public_key: str = ""
    telnyx_connection_id: str = ""

    @property
    def public_url(self) -> str:
        return (self.messer_voice_public_url or get_settings().messer_voice_url).rstrip("/")

    @property
    def public_ws_url(self) -> str:
        base = self.public_url
        for scheme, ws in (("https://", "wss://"), ("http://", "ws://")):
            if base.startswith(scheme):
                return ws + base[len(scheme) :]
        return base


@lru_cache(maxsize=1)
def voice_settings() -> VoiceSettings:
    return VoiceSettings()


class VoiceUnavailable(ApiError):
    status_code = 409
    code = "voice_unavailable"


class ProviderError(ApiError):
    status_code = 502
    code = "voice_provider_error"


# ------------------------------------------------------------------------------------------- providers


@dataclass(frozen=True, slots=True)
class SpeechProvider:
    kind: Literal["stt", "tts"]
    provider: str
    model: str
    voices: dict[str, str]

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def _key(provider: str) -> str:
    s = get_settings()
    return {"deepgram": s.deepgram_api_key, "elevenlabs": s.elevenlabs_api_key, "openai": s.openai_api_key}.get(
        provider, ""
    )


def _speech(kind: Literal["stt", "tts"], residency: Residency | None) -> SpeechProvider | None:
    raw = (load_models_config().get("voice") or {}).get(kind) or []
    for item in raw:
        if not isinstance(item, dict) or not item.get("provider"):
            continue
        provider = str(item["provider"])
        if not _key(provider):
            continue
        if residency is not None and not allowed_provider(residency, "voice", provider):
            continue
        voices = {str(k): str(v) for k, v in (item.get("voices") or {}).items()}
        return SpeechProvider(kind=kind, provider=provider, model=str(item.get("model") or ""), voices=voices)
    return None


def audio_providers(residency: Residency | None) -> tuple[SpeechProvider, SpeechProvider] | None:
    stt, tts = _speech("stt", residency), _speech("tts", residency)
    return (stt, tts) if stt is not None and tts is not None else None


def telephony_configured() -> dict[str, bool]:
    s = get_settings()
    return {
        "twilio": bool(s.twilio_account_sid and s.twilio_auth_token),
        "telnyx": bool(
            s.telnyx_api_key and voice_settings().telnyx_public_key and voice_settings().telnyx_connection_id
        ),
    }


def livekit_configured() -> bool:
    s = get_settings()
    return bool(s.livekit_url and s.livekit_api_key and s.livekit_api_secret)


def status(residency: Residency | None) -> dict[str, Any]:
    s = get_settings()
    audio = audio_providers(residency)
    stt = _speech("stt", residency)
    phone = telephony_configured()
    missing: list[dict[str, str]] = []
    if audio is None:
        missing.append({"variable": "DEEPGRAM_API_KEY / ELEVENLABS_API_KEY / OPENAI_API_KEY", "feature": "audio"})
    if not phone["twilio"] and not phone["telnyx"]:
        missing.append({"variable": "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN", "feature": "phone"})
        missing.append({"variable": "TELNYX_API_KEY / TELNYX_PUBLIC_KEY / TELNYX_CONNECTION_ID", "feature": "phone"})
    if not livekit_configured():
        missing.append({"variable": "LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET", "feature": "livekit"})
    return {
        "mode": "audio" if audio else "text",
        "audio": {
            "available": audio is not None,
            "stt": audio[0].label if audio else None,
            "tts": audio[1].label if audio else None,
        },
        "dictation": {"mode": "server" if stt else "browser", "stt": stt.label if stt else None},
        "telephony": phone,
        "livekit": livekit_configured(),
        "region": s.messer_voice_region or None,
        "residency": residency.mode if residency else None,
        "missing": missing,
    }


# ------------------------------------------------------------------------------------------- tickets


def mint_ticket(purpose: str, *, ttl_s: int, call_id: uuid.UUID | None = None, **claims: Any) -> str:
    """Same format as ``messer_voice.tickets``: HS256, ``typ=voice_ticket``, ``purpose``, single-use ``jti``."""
    payload: dict[str, Any] = {"typ": "voice_ticket", "purpose": purpose, "jti": random_token(16), **claims}
    if call_id is not None:
        payload["call"] = str(call_id)
    return sign_payload(payload, ttl_s)


def session_ws_url(ticket: str) -> str:
    return f"{voice_settings().public_ws_url}/v1/session?{urlencode({'ticket': ticket})}"


def transcribe_ws_url(ticket: str) -> str:
    return f"{voice_settings().public_ws_url}/v1/transcribe?{urlencode({'ticket': ticket})}"


# ------------------------------------------------------------------------------------------- calls


def agent_voice(member: Workforce) -> dict[str, Any]:
    raw = (member.config_json or {}).get("voice") or {}
    return {
        "enabled": bool(raw.get("enabled")),
        "voice": str(raw.get("voice") or ""),
        "language": str(raw.get("language") or "es"),
        "greeting": str(raw.get("greeting") or ""),
    }


async def phone_conversation(session: AsyncSession, *, number: VoicePhoneNumber, party: str) -> Conversation:
    """The per-number, per-party conversation shared by inbound and outbound calls (memory across calls)."""
    channel_key = f"phone:{number.id}"
    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.project_id == number.project_id,
                Conversation.channel_key == channel_key,
                Conversation.external_user_id == party,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        conv = Conversation(
            org_id=number.org_id,
            project_id=number.project_id,
            channel_key=channel_key,
            provider="phone",
            workforce_name=number.workforce_name,
            external_user_id=party,
            title=party,
        )
        session.add(conv)
        await session.flush()
    return conv


def call_cost(call: VoiceCall) -> Decimal:
    return (call.voice_cost_usd or Decimal("0")) + (call.model_cost_usd or Decimal("0"))


# ------------------------------------------------------------------------------------------- HTTP helpers


async def _request(
    method: str,
    url: str,
    *,
    provider: str,
    auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | list[tuple[str, Any]] | None = None,
    timeout_s: float = 20,
) -> Any:
    try:
        async with httpx.AsyncClient(timeout=timeout_s, transport=transport) as client:
            res = await client.request(
                method, url, auth=auth, headers=headers, data=data, json=json_body, params=params
            )
    except httpx.HTTPError as exc:
        raise ProviderError(f"No se pudo contactar con {provider}: {exc}") from exc
    if res.status_code >= 400:
        detail = res.text[:300]
        try:
            body = res.json()
            detail = str(
                body.get("message")
                or (body.get("errors") or [{}])[0].get("detail")
                or (body.get("detail") if isinstance(body.get("detail"), str) else None)
                or detail
            )
        except (ValueError, AttributeError, IndexError, TypeError):
            pass
        raise ProviderError(f"{provider} respondió {res.status_code}: {detail}", details={"provider": provider})
    if res.status_code == 204 or not res.content:
        return {}
    try:
        return res.json()
    except ValueError:
        return {}


def _twilio() -> tuple[str, tuple[str, str]]:
    s = get_settings()
    if not (s.twilio_account_sid and s.twilio_auth_token):
        raise VoiceUnavailable("Twilio no está configurado", code="twilio_not_configured")
    return f"{TWILIO_API}/Accounts/{s.twilio_account_sid}", (s.twilio_account_sid, s.twilio_auth_token)


def _telnyx_headers() -> dict[str, str]:
    if not telephony_configured()["telnyx"]:
        raise VoiceUnavailable("Telnyx no está configurado", code="telnyx_not_configured")
    return {"Authorization": f"Bearer {get_settings().telnyx_api_key}"}


def twilio_voice_url(call_id: uuid.UUID | None = None) -> str:
    base = f"{voice_settings().public_url}/telephony/twilio/voice"
    return f"{base}?{urlencode({'call': str(call_id)})}" if call_id else base


def twilio_status_url(call_id: uuid.UUID | None = None) -> str:
    base = f"{voice_settings().public_url}/telephony/twilio/status"
    return f"{base}?{urlencode({'call': str(call_id)})}" if call_id else base


def telnyx_webhook_url() -> str:
    return f"{voice_settings().public_url}/telephony/telnyx/webhook"


# ------------------------------------------------------------------------------------------- numbers


def _twilio_number(item: dict[str, Any]) -> dict[str, Any]:
    caps = item.get("capabilities") or {}
    return {
        "provider": "twilio",
        "number": str(item.get("phone_number") or ""),
        "external_id": str(item.get("sid") or ""),
        "label": str(item.get("friendly_name") or ""),
        "locality": item.get("locality") or item.get("region") or None,
        "country": item.get("iso_country") or None,
        "voice": bool(caps.get("voice", caps.get("Voice", True))),
    }


def _telnyx_number(item: dict[str, Any]) -> dict[str, Any]:
    region = item.get("region_information") or []
    locality = next((r.get("region_name") for r in region if isinstance(r, dict) and r.get("region_name")), None)
    features = [f.get("name") if isinstance(f, dict) else f for f in item.get("features") or []]
    return {
        "provider": "telnyx",
        "number": str(item.get("phone_number") or ""),
        "external_id": str(item.get("id") or ""),
        "label": str(item.get("connection_name") or ""),
        "locality": locality,
        "country": item.get("country_code") or None,
        "voice": not features or "voice" in features,
    }


async def search_available(provider: PhoneProvider, *, country: str, contains: str | None) -> list[dict[str, Any]]:
    country = country.upper()[:2]
    if provider == "twilio":
        base, auth = _twilio()
        params: dict[str, Any] = {"VoiceEnabled": "true", "PageSize": 20}
        if contains:
            params["Contains"] = contains
        data = await _request(
            "GET", f"{base}/AvailablePhoneNumbers/{country}/Local.json", provider="Twilio", auth=auth, params=params
        )
        return [_twilio_number(i) for i in data.get("available_phone_numbers") or []]
    headers = _telnyx_headers()
    query: list[tuple[str, Any]] = [
        ("filter[country_code]", country),
        ("filter[features][]", "voice"),
        ("filter[limit]", 20),
    ]
    if contains:
        query.append(("filter[phone_number][contains]", contains))
    data = await _request(
        "GET", f"{TELNYX_API}/available_phone_numbers", provider="Telnyx", headers=headers, params=query
    )
    return [_telnyx_number(i) for i in data.get("data") or []]


async def owned_numbers(provider: PhoneProvider) -> list[dict[str, Any]]:
    if provider == "twilio":
        base, auth = _twilio()
        data = await _request(
            "GET", f"{base}/IncomingPhoneNumbers.json", provider="Twilio", auth=auth, params={"PageSize": 100}
        )
        return [_twilio_number(i) for i in data.get("incoming_phone_numbers") or []]
    data = await _request(
        "GET", f"{TELNYX_API}/phone_numbers", provider="Telnyx", headers=_telnyx_headers(), params={"page[size]": 100}
    )
    return [_telnyx_number(i) for i in data.get("data") or []]


async def _telnyx_number_id(number: str) -> str:
    data = await _request(
        "GET",
        f"{TELNYX_API}/phone_numbers",
        provider="Telnyx",
        headers=_telnyx_headers(),
        params={"filter[phone_number]": number},
    )
    items = data.get("data") or []
    return str(items[0].get("id") or "") if items else ""


async def _telnyx_route(external_id: str) -> None:
    """Point the number and the Call Control application at the voice service."""
    vs = voice_settings()
    headers = _telnyx_headers()
    await _request(
        "PATCH",
        f"{TELNYX_API}/call_control_applications/{vs.telnyx_connection_id}",
        provider="Telnyx",
        headers=headers,
        json_body={"webhook_event_url": telnyx_webhook_url()},
    )
    if external_id:
        await _request(
            "PATCH",
            f"{TELNYX_API}/phone_numbers/{external_id}",
            provider="Telnyx",
            headers=headers,
            json_body={"connection_id": vs.telnyx_connection_id},
        )


async def provision_number(
    provider: PhoneProvider, *, number: str, external_id: str | None, buy: bool
) -> dict[str, Any]:
    """Buy (``buy=True``) or take an owned number, and route its calls to the voice service."""
    if provider == "twilio":
        base, auth = _twilio()
        hooks = {
            "VoiceUrl": twilio_voice_url(),
            "VoiceMethod": "POST",
            "StatusCallback": twilio_status_url(),
            "StatusCallbackMethod": "POST",
        }
        if buy:
            item = await _request(
                "POST",
                f"{base}/IncomingPhoneNumbers.json",
                provider="Twilio",
                auth=auth,
                data={"PhoneNumber": number, **hooks},
            )
        else:
            sid = external_id or ""
            if not sid:
                owned = {n["number"]: n["external_id"] for n in await owned_numbers("twilio")}
                sid = owned.get(number, "")
            if not sid:
                raise ApiError("El número no pertenece a la cuenta de Twilio", code="number_not_owned")
            item = await _request(
                "POST", f"{base}/IncomingPhoneNumbers/{sid}.json", provider="Twilio", auth=auth, data=hooks
            )
        return _twilio_number(item)
    headers = _telnyx_headers()
    if buy:
        await _request(
            "POST",
            f"{TELNYX_API}/number_orders",
            provider="Telnyx",
            headers=headers,
            json_body={
                "phone_numbers": [{"phone_number": number}],
                "connection_id": voice_settings().telnyx_connection_id,
            },
        )
        external_id = await _telnyx_number_id(number)
    elif not external_id:
        external_id = await _telnyx_number_id(number)
        if not external_id:
            raise ApiError("El número no pertenece a la cuenta de Telnyx", code="number_not_owned")
    await _telnyx_route(external_id or "")
    return {"provider": "telnyx", "number": number, "external_id": external_id or "", "label": ""}


async def release_number(row: VoicePhoneNumber) -> None:
    if row.provider == "twilio":
        base, auth = _twilio()
        if row.external_id:
            await _request(
                "DELETE", f"{base}/IncomingPhoneNumbers/{row.external_id}.json", provider="Twilio", auth=auth
            )
        return
    if row.external_id:
        await _request(
            "DELETE", f"{TELNYX_API}/phone_numbers/{row.external_id}", provider="Telnyx", headers=_telnyx_headers()
        )


# ------------------------------------------------------------------------------------------- outbound calls


async def dial(call: VoiceCall, number: VoicePhoneNumber) -> str:
    """Place the call at the provider; returns its call id (Twilio CallSid / Telnyx call_control_id)."""
    if number.provider == "twilio":
        base, auth = _twilio()
        data = await _request(
            "POST",
            f"{base}/Calls.json",
            provider="Twilio",
            auth=auth,
            data={
                "To": call.to_number,
                "From": number.number,
                "Url": twilio_voice_url(call.id),
                "Method": "POST",
                "StatusCallback": twilio_status_url(call.id),
                "StatusCallbackMethod": "POST",
                "StatusCallbackEvent": "completed",
                "Timeout": 30,
            },
        )
        return str(data.get("sid") or "")
    ticket = mint_ticket("telephony", ttl_s=PHONE_TICKET_TTL_S, call_id=call.id, org=str(call.org_id))
    stream = (
        f"{voice_settings().public_ws_url}/telephony/telnyx/media?{urlencode({'call': str(call.id), 'ticket': ticket})}"
    )
    data = await _request(
        "POST",
        f"{TELNYX_API}/calls",
        provider="Telnyx",
        headers=_telnyx_headers(),
        json_body={
            "connection_id": voice_settings().telnyx_connection_id,
            "to": call.to_number,
            "from": number.number,
            "stream_url": stream,
            "stream_track": "inbound_track",
            "stream_bidirectional_mode": "rtp",
            "stream_bidirectional_codec": "PCMU",
            "client_state": base64.b64encode(str(call.id).encode()).decode(),
            "webhook_url": telnyx_webhook_url(),
            "timeout_secs": 30,
        },
    )
    return str((data.get("data") or {}).get("call_control_id") or "")


async def hangup(call: VoiceCall) -> None:
    if not call.external_call_id:
        return
    if call.transport == "twilio":
        base, auth = _twilio()
        await _request(
            "POST",
            f"{base}/Calls/{call.external_call_id}.json",
            provider="Twilio",
            auth=auth,
            data={"Status": "completed"},
        )
    elif call.transport == "telnyx":
        await _request(
            "POST",
            f"{TELNYX_API}/calls/{call.external_call_id}/actions/hangup",
            provider="Telnyx",
            headers=_telnyx_headers(),
            json_body={},
        )


# ------------------------------------------------------------------------------------------- LiveKit


def livekit_room(call_id: uuid.UUID) -> str:
    return f"messer-{call_id.hex}"


def livekit_token(identity: str, room: str, *, name: str, ttl_s: int = 3600) -> str:
    s = get_settings()
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": s.livekit_api_key,
        "sub": identity,
        "name": name,
        "nbf": now - 5,
        "exp": now + ttl_s,
        "video": {"room": room, "roomJoin": True, "canPublish": True, "canSubscribe": True, "canPublishData": True},
    }
    return jwt.encode(claims, s.livekit_api_secret, algorithm="HS256")


async def livekit_join(call_id: uuid.UUID) -> dict[str, Any]:
    """Ask the voice service to put the agent in the call's room."""
    s = get_settings()
    return await _request(
        "POST",
        f"{s.messer_voice_url.rstrip('/')}/internal/v1/livekit/join",
        provider="Messer voice",
        headers={"Authorization": f"Bearer {s.service_token}"},
        json_body={"call_id": str(call_id)},
        timeout_s=40,
    )


# ------------------------------------------------------------------------------------------- voices


async def voices(residency: Residency | None, language: str) -> dict[str, Any]:
    """Voices of the TTS provider in use (``provider:voice`` ids); ``browser`` means the client lists its own."""
    pair = audio_providers(residency)
    if pair is None:
        return {"provider": "browser", "items": []}
    tts = pair[1]
    lang = (language or "es")[:2]
    items: list[dict[str, Any]] = []
    if tts.provider == "elevenlabs":
        data = await _request(
            "GET", f"{ELEVENLABS_API}/voices", provider="ElevenLabs", headers={"xi-api-key": _key("elevenlabs")}
        )
        for v in data.get("voices") or []:
            labels = v.get("labels") or {}
            items.append(
                {
                    "id": f"elevenlabs:{v.get('voice_id')}",
                    "name": str(v.get("name") or v.get("voice_id")),
                    "language": labels.get("language") or None,
                    "description": " · ".join(str(x) for x in (labels.get("accent"), labels.get("gender")) if x)
                    or None,
                }
            )
    elif tts.provider == "openai":
        items = [
            {"id": f"openai:{name}", "name": name, "language": None, "description": None} for name in OPENAI_VOICES
        ]
    else:
        items = [
            {"id": f"{tts.provider}:{voice}", "name": voice, "language": code, "description": None}
            for code, voice in tts.voices.items()
        ]
    default = tts.voices.get(lang) or tts.voices.get("es")
    return {"provider": tts.provider, "default": f"{tts.provider}:{default}" if default else None, "items": items}


async def ensure_agent(session: AsyncSession, project: Project, name: str) -> Workforce:
    member = (
        await session.execute(select(Workforce).where(Workforce.project_id == project.id, Workforce.name == name))
    ).scalar_one_or_none()
    if member is None:
        raise ApiError(f"No existe «{name}» en este proyecto", code="not_found", status_code=404)
    if member.kind != "agent":
        raise ApiError("La voz solo está disponible para agentes", code="voice_agent_only")
    return member
