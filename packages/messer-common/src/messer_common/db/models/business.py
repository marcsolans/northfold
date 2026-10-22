"""Business workstream tables: simulated checkouts (Stripe test mode without keys) and lifecycle notices.

* ``simulated_checkouts`` — checkout sessions created by the simulated billing provider. The web app shows a
  "test mode" payment page for them; confirming fires the same internal webhook handlers as Stripe.
* ``billing_notices`` — one row per lifecycle message already delivered to an organization (trial emails,
  payment failures, budget exceeded, ...). The unique key makes every notice idempotent.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls


class SimulatedCheckout(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "simulated_checkouts"

    kind: Mapped[str] = mapped_column(String(20))  # subscription | credit_pack
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    interval: Mapped[str | None] = mapped_column(String(10), nullable=True)  # month | year
    pack_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    amount_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open")  # open|completed|canceled
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    result: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("simulated_checkouts", read="owner", write="system")


class BillingNotice(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "billing_notices"
    __table_args__ = (UniqueConstraint("org_id", "kind", "ref", name="uq_billing_notices_org_kind_ref"),)

    kind: Mapped[str] = mapped_column(String(60))  # trial_day_1 | trial_expired | payment_failed | budget_exceeded ...
    ref: Mapped[str] = mapped_column(String(160), default="", server_default="")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("billing_notices", read="admin", write="system")
