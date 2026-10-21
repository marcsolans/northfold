"""Plans, subscriptions, credits, invoices, budgets and model prices."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls


class Plan(Base, TimestampMixin):
    """Global plan catalog. Prices are configuration (editable in /admin, synced to Stripe)."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # starter | pro | business | enterprise
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    price_month_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_year_eur: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    price_is_starting: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    limits: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    self_serve: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")
    stripe_product_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_price_ids: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


class Subscription(Base, OrgScoped, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("org_id", name="uq_subscriptions_org"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"))
    interval: Mapped[str] = mapped_column(String(10), default="month", server_default="month")
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    # trialing | active | past_due | canceled | incomplete
    status: Mapped[str] = mapped_column(String(20))
    trial_ends_at: Mapped[datetime | None] = mapped_column(nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(nullable=True)
    past_due_since: Mapped[datetime | None] = mapped_column(nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    canceled_at: Mapped[datetime | None] = mapped_column(nullable=True)
    auto_topup: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


rls("subscriptions", read="viewer", write="system")


class CreditLedger(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "credit_ledger"
    __table_args__ = (Index("ix_credit_ledger_org_created", "org_id", "created_at"),)

    kind: Mapped[str] = mapped_column(String(20))  # grant | usage | purchase | adjustment
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4))  # positive adds, negative consumes
    run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)


rls("credit_ledger", read="viewer", write="system")


class Invoice(Base, IdMixin, OrgScoped, CreatedMixin):
    """Mirror of Stripe invoices (written by the webhook handler)."""

    __tablename__ = "invoices"

    stripe_invoice_id: Mapped[str] = mapped_column(String(100), unique=True)
    number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    amount_due_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    amount_paid_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    tax_eur: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    hosted_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_start: Mapped[datetime | None] = mapped_column(nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(nullable=True)


rls("invoices", read="owner", write="system")


class StripeEvent(Base, CreatedMixin):
    """Processed webhook event ids, for idempotency."""

    __tablename__ = "stripe_events"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    processed_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Budget(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "budgets"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    period: Mapped[str] = mapped_column(String(10), default="month", server_default="month")
    limit_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    alert_threshold_pct: Mapped[int] = mapped_column(default=80, server_default="80")
    hard_stop: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_alerted_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("budgets", read="viewer", write="admin")


class ModelPrice(Base):
    __tablename__ = "model_prices"

    model: Mapped[str] = mapped_column(String(120), primary_key=True)  # provider/model
    provider: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    input_per_mtok_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    output_per_mtok_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    cache_read_per_mtok_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    cache_write_per_mtok_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=Decimal("0"))
    context_window: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ModelPolicy(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "model_policies"

    # {"allow": ["anthropic/*"], "deny": ["openai/*"], "max_tier": "powerful"}
    rules: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("model_policies", read="viewer", write="admin")


class FeatureFlag(Base, TimestampMixin):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Per-plan or per-org overrides: {"plans": ["business"], "orgs": ["<uuid>"]}
    targeting: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
