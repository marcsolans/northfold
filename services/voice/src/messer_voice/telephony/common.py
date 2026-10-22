"""Shared pieces of the phone transports: number routing, inbound call records, status mapping, signatures."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Conversation, Workforce
from messer_common.db.models.voice import FINAL_CALL_STATUSES, VoiceCall, VoicePhoneNumber
from messer_common.logging import get_logger
from messer_common.residency import allowed_provider, org_residency

from .. import calls

log = get_logger("messer.voice.telephony")

_NON_DIGITS = re.compile(r"[^\d+]")
SIGNATURE_TOLERANCE_S = 300


def normalize_number(value: str | None) -> str:
    raw = _NON_DIGITS.sub("", (value or "").strip())
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    return raw


# ------------------------------------------------------------------------------------------- signatures


def twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """Twilio request signature: base64(HMAC-SHA1(auth_token, url + concatenated sorted params))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(auth_token.encode(), payload.encode(), hashlib.sha1).digest()).decode()


def twilio_signature_valid(urls: list[str], params: dict[str, str], signature: str, auth_token: str) -> bool:
    if not signature or not auth_token:
        return False
    return any(hmac.compare_digest(twilio_signature(url, params, auth_token), signature) for url in urls)


def telnyx_signature_valid(body: bytes, timestamp: str, signature_b64: str, public_key_b64: str) -> bool:
    """Telnyx webhook signature: Ed25519 over ``{timestamp}|{raw body}``, within a 5-minute window."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not (timestamp and signature_b64 and public_key_b64):
        return False
    try:
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_S:
            return False
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64), f"{timestamp}|".encode() + body)
        return True
    except (InvalidSignature, ValueError):
        return False


# ------------------------------------------------------------------------------------------- routing


async def find_number(provider: str, number: str) -> VoicePhoneNumber | None:
    normalized = normalize_number(number)
    if not normalized:
        return None
    async with system_session() as s:
        return (
            await s.execute(
                select(VoicePhoneNumber).where(
                    VoicePhoneNumber.provider == provider,
                    VoicePhoneNumber.number == normalized,
                    VoicePhoneNumber.status == "active",
                )
            )
        ).scalar_one_or_none()


async def provider_allowed(org_id: uuid.UUID, provider: str) -> bool:
    async with system_session() as s:
        residency = await org_residency(s, org_id)
    return allowed_provider(residency, "voice", provider)


async def create_inbound_call(
    *, provider: str, number: VoicePhoneNumber, from_number: str, external_call_id: str | None
) -> VoiceCall:
    """Call record + per-caller conversation (the agent remembers previous calls from the same number)."""
    caller = normalize_number(from_number) or "anonymous"
    async with system_session() as s:
        member = (
            await s.execute(
                select(Workforce).where(
                    Workforce.project_id == number.project_id,
                    Workforce.org_id == number.org_id,
                    Workforce.name == number.workforce_name,
                )
            )
        ).scalar_one_or_none()
        language = str(((member.config_json if member else {}) or {}).get("voice", {}).get("language") or "es")
        channel_key = f"phone:{number.id}"
        conv = (
            await s.execute(
                select(Conversation).where(
                    Conversation.project_id == number.project_id,
                    Conversation.channel_key == channel_key,
                    Conversation.external_user_id == caller,
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
                external_user_id=caller,
                title=caller,
            )
            s.add(conv)
            await s.flush()
        call = VoiceCall(
            org_id=number.org_id,
            project_id=number.project_id,
            workforce_name=number.workforce_name,
            environment=number.environment,
            conversation_id=conv.id,
            phone_number_id=number.id,
            transport=provider,
            channel="phone",
            mode="audio",
            direction="inbound",
            status="ringing",
            from_number=caller,
            to_number=number.number,
            external_call_id=external_call_id,
            language=language,
            record=number.record_calls,
            recording_consent="notice" if number.record_calls else None,
            started_at=datetime.now(UTC),
            meta={"greeting": number.greeting} if number.greeting else {},
        )
        s.add(call)
        await s.flush()
        conv.external_thread_id = str(call.id)
    log.info("voice.phone.inbound_call", provider=provider, call_id=str(call.id), to=number.number)
    return call


async def find_call_by_external(provider: str, external_call_id: str) -> VoiceCall | None:
    async with system_session() as s:
        return (
            await s.execute(
                select(VoiceCall).where(VoiceCall.transport == provider, VoiceCall.external_call_id == external_call_id)
            )
        ).scalar_one_or_none()


def parse_call_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def end_unanswered(call_id: uuid.UUID, status: str, *, reason: str | None = None) -> None:
    """Provider says the call ended. Calls whose media session ran are finalized by the bridge."""
    call = await calls.load_call(call_id)
    if call.status in FINAL_CALL_STATUSES or call.status == "active":
        return
    if status == "completed":
        await calls.update_call(call_id, status="completed", ended_at=datetime.now(UTC), duration_ms=0)
        return
    await calls.fail_call(call_id, code=reason or status, message=reason or status, status=status)


TWILIO_STATUS = {
    "completed": "completed",
    "busy": "busy",
    "no-answer": "no_answer",
    "failed": "failed",
    "canceled": "canceled",
}

TELNYX_HANGUP = {
    "normal_clearing": "completed",
    "user_busy": "busy",
    "call_rejected": "busy",
    "timeout": "no_answer",
    "no_answer": "no_answer",
    "originator_cancel": "canceled",
}
