"""What this deployment can do for voice (shown in the UI setup states and in ``/internal/v1/status``)."""

from __future__ import annotations

from typing import Any

from messer_common.settings import get_settings

from .config import get_voice_settings
from .providers import select_pipeline


def telephony_configured() -> dict[str, bool]:
    s = get_settings()
    vs = get_voice_settings()
    return {
        "twilio": bool(s.twilio_account_sid and s.twilio_auth_token),
        "telnyx": bool(s.telnyx_api_key and vs.telnyx_public_key),
    }


def livekit_configured() -> bool:
    s = get_settings()
    return bool(s.livekit_url and s.livekit_api_key and s.livekit_api_secret)


def voice_status() -> dict[str, Any]:
    pipeline = select_pipeline(None)
    s = get_settings()
    return {
        "audio": {
            "available": pipeline is not None,
            "stt": pipeline.stt.label if pipeline else None,
            "tts": pipeline.tts.label if pipeline else None,
        },
        "telephony": telephony_configured(),
        "livekit": livekit_configured(),
        "region": s.messer_voice_region or None,
        "public_url": get_voice_settings().public_url,
    }
