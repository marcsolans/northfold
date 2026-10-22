"""Connector events received by inbound webhooks (owner: connectors workstream).

Rows are written on the owner connection by the public webhook endpoint after HMAC verification and read
by members of the organization and by workflow triggers (``webhooks`` adapter, event ``received``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls


class ConnectorEvent(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "connector_events"
    __table_args__ = (Index("ix_connector_events_connection", "connection_id", "id"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("connections.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(60), default="received", server_default="received")
    # Parsed JSON body (or {"raw": "..."} for non-JSON bodies), selected headers and query parameters.
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    headers: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    query: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


rls("connector_events", read="viewer", write="system", delete="admin")
