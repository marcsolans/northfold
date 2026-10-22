"""Voice service settings (env / repository ``.env``), on top of the shared :mod:`messer_common.settings`.

Shared keys (provider credentials, URLs, region) come from :func:`messer_common.settings.get_settings`; the
variables below are specific to the voice gateway.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from messer_common.settings import REPO_ROOT, get_settings

TurnDetectorMode = Literal["lexical", "local", "heuristic", "provider"]


class VoiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Public base URL of this service (what browsers and Twilio/Telnyx reach), e.g. https://voice.messer.eu.
    # Empty → MESSER_VOICE_URL.
    messer_voice_public_url: str = ""
    # Telnyx: public key of the account (webhook Ed25519 signatures) and the Call Control application id.
    telnyx_public_key: str = ""
    telnyx_connection_id: str = ""
    # Behaviour.
    messer_voice_max_call_secs: int = Field(default=900, ge=30)
    messer_voice_idle_secs: float = Field(default=10.0, gt=0)
    messer_voice_idle_hangup_secs: float = Field(default=120.0, gt=0)
    messer_voice_phone_idle_hangup_secs: float = Field(default=45.0, gt=0)
    messer_voice_turn_timeout_secs: float = Field(default=60.0, gt=0)
    messer_voice_filler_delay_secs: float = Field(default=1.0, ge=0)
    # Turn detector for STT providers without native end-of-turn ("local" downloads Smart Turn/Namo models).
    messer_voice_turn_detector: TurnDetectorMode = "lexical"
    # Local scratch directory for recordings before they are uploaded to storage.
    messer_voice_recording_dir: str = "./.data/voice-recordings"
    messer_voice_host: str = "0.0.0.0"  # noqa: S104 - container entrypoint
    messer_voice_port: int = 8300

    @property
    def public_url(self) -> str:
        return (self.messer_voice_public_url or get_settings().messer_voice_url).rstrip("/")

    @property
    def public_ws_url(self) -> str:
        base = self.public_url
        if base.startswith("https://"):
            return "wss://" + base[len("https://") :]
        if base.startswith("http://"):
            return "ws://" + base[len("http://") :]
        return base


@lru_cache(maxsize=1)
def get_voice_settings() -> VoiceSettings:
    return VoiceSettings()


def reset_voice_settings_cache() -> None:
    get_voice_settings.cache_clear()
