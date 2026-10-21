"""Interfaces (chat + generated apps), channels, conversations, contact requests."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls


class Interface(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "interfaces"
    __table_args__ = (UniqueConstraint("project_id", "slug", name="uq_interfaces_project_slug"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))  # chat | app
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    published_definition: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    public: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    slug: Mapped[str] = mapped_column(String(80))
    auth_required: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    workforce_name: Mapped[str | None] = mapped_column(String(80), nullable=True)  # chat interfaces
    theme: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("interfaces", read="viewer", write="builder")


class Channel(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "channels"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workforce_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workforce.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(20))  # whatsapp|slack|teams|email|telegram|phone|web
    name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    credentials: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted JSON
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    webhook_secret: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )  # active|demo|error|disabled
    demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    environment: Mapped[str] = mapped_column(String(20), default="production", server_default="production")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


rls("channels", read="viewer", write="builder")


class Conversation(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_project_updated", "project_id", "updated_at"),
        UniqueConstraint("project_id", "channel_key", "external_user_id", name="uq_conversations_thread"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    channel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("channels.id", ondelete="SET NULL"), nullable=True)
    # Stable key for the source of the thread: channel id, "public-chat:<interface>", "studio", "voice:<call>".
    channel_key: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(20), default="web", server_default="web")
    workforce_name: Mapped[str] = mapped_column(String(80))
    external_user_id: Mapped[str] = mapped_column(String(255))
    external_thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    messages: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    memory: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")


rls("conversations", read="viewer", write="builder")


class ContactRequest(Base, IdMixin, CreatedMixin):
    """Submissions of the public contact form."""

    __tablename__ = "contact_requests"

    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(String(40), default="sales", server_default="sales")
    status: Mapped[str] = mapped_column(String(20), default="new", server_default="new")


class ServiceHealth(Base):
    """Last health check results, rendered on the public status page."""

    __tablename__ = "service_health"

    service: Mapped[str] = mapped_column(String(40), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))  # operational | degraded | down
    latency_ms: Mapped[int | None] = mapped_column(nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    history: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
