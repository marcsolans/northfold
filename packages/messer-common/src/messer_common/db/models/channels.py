"""Channel message log (owner: channels workstream).

One row per message received from or sent to a provider (WhatsApp, Slack, Teams, Telegram, email). Inbound rows
make webhook processing idempotent (unique per channel and provider message id) and drive the
``channel_inbound`` worker job; outbound rows record what was delivered (or stored, for demo channels and the
simulator) and why a delivery failed. The readable thread of a conversation stays in ``conversations.messages``
(written by the runtime); this table adds delivery state and provider context (reply addresses, threads).

Rows are written on the owner connection only (webhooks, worker, simulator); members read, admins delete.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls

INBOUND_STATUSES = ("received", "processing", "processed", "ignored", "failed")
OUTBOUND_STATUSES = ("sent", "stored", "failed")


class ChannelMessage(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "channel_messages"
    __table_args__ = (
        UniqueConstraint("channel_id", "direction", "external_id", name="uq_channel_messages_external"),
        Index("ix_channel_messages_channel_created", "channel_id", "created_at"),
        Index("ix_channel_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_channel_messages_run", "run_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    channel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(10))  # inbound | outbound
    provider: Mapped[str] = mapped_column(String(20))
    # Provider message id: idempotency key for inbound rows, id returned by the provider for outbound rows.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # answer | approval_pending | error (outbound) · text | media | interactive | location (inbound)
    kind: Mapped[str] = mapped_column(String(30), default="text", server_default="text")
    sender_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Inbound: conversation_key, thread_id, reply context, attachments. Outbound: parts, provider ids, reason.
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)  # outbound → inbound message answered
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    claimed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("channel_messages", read="viewer", write="system", delete="admin")
