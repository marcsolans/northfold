"""Governance workstream tables (migration 0013).

* ``alarm_events`` — every state transition of an alarm (ok → firing → ok) with the value that caused it and
  what was delivered (in-app, email, Slack). Written by the alarm evaluator on the owner connection; members
  read it through RLS.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls


class AlarmEvent(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "alarm_events"
    __table_args__ = (Index("ix_alarm_events_alarm_created", "alarm_id", "created_at"),)

    alarm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("alarms.id", ondelete="CASCADE"))
    from_state: Mapped[str] = mapped_column(String(10))  # ok | firing
    to_state: Mapped[str] = mapped_column(String(10))  # ok | firing
    value: Mapped[float | None] = mapped_column(nullable=True)
    metric: Mapped[str] = mapped_column(String(80))
    comparator: Mapped[str] = mapped_column(String(4))
    threshold: Mapped[float] = mapped_column()
    window_minutes: Mapped[int] = mapped_column()
    # {"in_app": 2, "email": 2, "slack": "posted" | "skipped:<reason>" | "failed:<reason>"}
    delivery: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("alarm_events", read="viewer", write="system")
