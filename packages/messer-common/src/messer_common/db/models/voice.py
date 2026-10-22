"""Voice calls and phone numbers (owner: voice workstream).

* ``voice_calls``: one row per call, whatever the transport (browser WebSocket, Twilio, Telnyx, LiveKit). Every
  call is also a conversation (``conversations.provider`` = ``voice`` | ``phone``) and every turn a run linked to
  it; the row keeps what the traces UI shows next to those runs: transcript, per-turn latency (engine
  ``TurnMetrics``), speech usage and cost, and the recording. Created by the API (browser sessions, outbound
  calls) or by the voice service on the owner connection (inbound phone calls); finalized by the voice service.
* ``voice_phone_numbers``: numbers of the deployment's Twilio/Telnyx account assigned to a project's agent.
  A number can only be assigned once across the platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, IdMixin, OrgScoped, TimestampMixin, rls

CALL_TRANSPORTS = ("browser", "twilio", "telnyx", "livekit")
CALL_STATUSES = ("pending", "ringing", "active", "completed", "failed", "no_answer", "busy", "canceled")
FINAL_CALL_STATUSES = ("completed", "failed", "no_answer", "busy", "canceled")
PHONE_PROVIDERS = ("twilio", "telnyx")


class VoicePhoneNumber(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "voice_phone_numbers"
    __table_args__ = (
        UniqueConstraint("provider", "number", name="uq_voice_phone_numbers_provider_number"),
        Index("ix_voice_phone_numbers_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    workforce_name: Mapped[str] = mapped_column(String(80))
    environment: Mapped[str] = mapped_column(String(20), default="production", server_default="production")
    provider: Mapped[str] = mapped_column(String(20))  # twilio | telnyx
    number: Mapped[str] = mapped_column(String(40))  # E.164
    external_id: Mapped[str] = mapped_column(String(120), default="", server_default="")
    label: Mapped[str] = mapped_column(String(200), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")  # active|error
    purchased: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    record_calls: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    greeting: Mapped[str] = mapped_column(Text, default="", server_default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


rls("voice_phone_numbers", read="viewer", write="builder", delete="admin")


class VoiceCall(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "voice_calls"
    __table_args__ = (
        Index("ix_voice_calls_project_created", "project_id", "created_at"),
        Index("ix_voice_calls_conversation", "conversation_id"),
        Index("ix_voice_calls_external", "transport", "external_call_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    workforce_name: Mapped[str] = mapped_column(String(80))
    environment: Mapped[str] = mapped_column(String(20), default="development", server_default="development")
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    phone_number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("voice_phone_numbers.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    transport: Mapped[str] = mapped_column(String(20))  # browser | twilio | telnyx | livekit
    channel: Mapped[str] = mapped_column(String(10), default="voice", server_default="voice")  # voice | phone
    mode: Mapped[str] = mapped_column(String(10), default="audio", server_default="audio")  # audio | text
    direction: Mapped[str] = mapped_column(String(10), default="inbound", server_default="inbound")
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    from_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    external_call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="es", server_default="es")
    stt_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tts_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    record: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # "explicit": the caller ticked the consent box (browser); "notice": a recording notice was spoken (phone).
    recording_consent: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recording_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # [{role, text, timestamp, offset_ms, filler}] — the call as heard (engine TranscriptEntry + offset).
    transcript: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    # [{turn_index, run_id, status, user_text, assistant_text, cost_usd, metrics: TurnMetrics}]
    turns: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    # {"stt": {provider, model, seconds}, "tts": {provider, model, characters}, "telephony": {...}, "events": [...]}
    usage: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    voice_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), server_default="0")
    model_cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), server_default="0")
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0")
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


rls("voice_calls", read="viewer", write="builder", delete="admin")
