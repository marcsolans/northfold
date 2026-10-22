"""Everything a voice session needs to know about the call it serves."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from messer_common.residency import Residency

Transport = Literal["browser", "twilio", "telnyx", "livekit"]
Mode = Literal["audio", "text"]


@dataclass(slots=True)
class CallContext:
    call_id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    workforce: str
    environment: str
    ref: str
    environment_id: uuid.UUID | None
    version_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    user_id: uuid.UUID | None
    external_user_id: str | None
    channel: Literal["voice", "phone"]
    transport: Transport
    mode: Mode
    direction: Literal["inbound", "outbound"]
    language: str
    voice: str
    greeting: str
    record: bool
    residency: Residency

    @property
    def session_id(self) -> str:
        """Engine session id (recording file stem): ``[A-Za-z0-9_-]{1,128}``."""
        return self.call_id.hex
