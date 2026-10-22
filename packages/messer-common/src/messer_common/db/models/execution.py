"""Runs, spans, approvals, evals, feedback."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls

RUN_STATUSES = ("running", "success", "error", "paused", "cancelled", "budget_exceeded", "blocked", "timeout")


class Run(Base, OrgScoped):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_project_started", "project_id", "started_at"),
        Index("ix_runs_org_started", "org_id", "started_at"),
        Index("ix_runs_parent", "parent_run_id"),
    )

    # Run ids are minted by the engine (UUIDv7 strings) and kept verbatim.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    environment_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="development", server_default="development")
    version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    workforce_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workforce.id", ondelete="SET NULL"), nullable=True
    )
    workforce_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trigger_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20))
    input: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    usage: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    models: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), server_default="0")
    credits: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0"), server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="studio", server_default="studio")
    source: Mapped[str] = mapped_column(String(20), default="runtime", server_default="runtime")
    # Full engine trace (list of span records) for resume and conversation memory.
    trace: Mapped[Any] = mapped_column(JSONB, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rerun_of: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    ended_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("runs", read="viewer", write="builder")


class Span(Base, OrgScoped):
    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_run", "run_id", "t0"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    call_id: Mapped[str] = mapped_column(String(80))
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    parent_call_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    kind: Mapped[str] = mapped_column(String(12))  # llm | tool | step | agent | workflow | guardrail | guard
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="success", server_default="success")
    input: Mapped[Any] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any] = mapped_column(JSONB, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    input_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), server_default="0")
    t0: Mapped[int] = mapped_column(BigInteger)  # unix ms
    t1: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict, server_default=text("'{}'::jsonb"))


rls("spans", read="viewer", write="builder")


class Approval(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approvals_org_status", "org_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column()
    span_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    engine_approval_id: Mapped[str] = mapped_column(String(200))
    workforce_name: Mapped[str] = mapped_column(String(80), default="", server_default="")
    tool_name: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    context_summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    assigned_role: Mapped[str] = mapped_column(String(20), default="admin", server_default="admin")
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    decided_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(nullable=True)
    decision_via: Mapped[str | None] = mapped_column(String(20), nullable=True)  # app | email | slack | expiry
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_payload: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    expiry_action: Mapped[str] = mapped_column(String(10), default="deny", server_default="deny")  # approve | deny
    resume_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    environment: Mapped[str] = mapped_column(String(20), default="development", server_default="development")
    channel_context: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("approvals", read="viewer", write="builder")


class EvalRun(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "eval_runs"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workforce_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    version_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    trigger: Mapped[str] = mapped_column(
        String(20), default="manual", server_default="manual"
    )  # manual|deploy|composer
    status: Mapped[str] = mapped_column(String(20), default="running", server_default="running")
    results: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    passed: Mapped[int] = mapped_column(default=0, server_default="0")
    failed: Mapped[int] = mapped_column(default=0, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), default=Decimal("0"), server_default="0")
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("eval_runs", read="viewer", write="builder")


class Feedback(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "feedback"

    run_id: Mapped[uuid.UUID] = mapped_column(index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str] = mapped_column(String(4))  # up | down
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


rls("feedback", read="viewer", write="viewer")


class GuardPlaybook(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "guard_playbooks"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    workforce_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workforce.id", ondelete="CASCADE"), unique=True)
    # {"version": 1, "small_model": ..., "large_model": ..., "policies": [...], "output_schema": {...}}
    playbook: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    generated_by: Mapped[str] = mapped_column(String(20), default="llm", server_default="llm")  # llm | rules | manual
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    # Guard (0012): how the playbook was produced (model, cost, warnings) and who last changed it.
    meta: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(nullable=True)


rls("guard_playbooks", read="viewer", write="builder")
