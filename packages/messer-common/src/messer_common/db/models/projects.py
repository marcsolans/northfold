"""Projects, workforce, versions, environments, deployments, triggers, secrets, templates."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls


class Project(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "slug", name="uq_projects_org_slug"),)

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    repo_path: Mapped[str] = mapped_column(Text)
    github_repo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    github_config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    default_model_tier: Mapped[str] = mapped_column(String(20), default="standard", server_default="standard")
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("projects", read="viewer", write="builder", delete="admin")


class Workforce(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "workforce"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_workforce_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # agent | workflow
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    path: Mapped[str] = mapped_column(Text)
    config_json: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    # "config": UI config is the source and the code is generated; "code": code was hand-edited.
    source_mode: Mapped[str] = mapped_column(String(10), default="config", server_default="config")
    current_version: Mapped[int] = mapped_column(default=0, server_default="0")
    guard_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


rls("workforce", read="viewer", write="builder")


class Version(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "versions"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "version", name="uq_versions_entity_version"),
        Index("ix_versions_project", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(20))  # project | workforce | interface
    entity_id: Mapped[uuid.UUID] = mapped_column()
    version: Mapped[int] = mapped_column()
    git_commit: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="", server_default="")
    # studio | github | composer | cli (git push to the Messer remote)
    source: Mapped[str] = mapped_column(String(20), default="studio", server_default="studio")


rls("versions", read="viewer", write="builder")


class Environment(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_environments_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(20))  # development | production
    deployed_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("versions.id"), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_domain: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    domain_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # pending|verified|active|failed
    domain_verification_token: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="idle", server_default="idle")
    config_json: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("environments", read="viewer", write="builder")


class Deployment(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "deployments"

    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("versions.id"))
    status: Mapped[str] = mapped_column(String(20))  # pending|evaluating|deploying|live|failed|rolled_back|superseded
    logs: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    eval_run_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    forced_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("deployments", read="viewer", write="builder")


class Trigger(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "triggers"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workforce_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workforce.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # manual|cron|webhook|email|file|connector_event
    name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    secret: Mapped[str | None] = mapped_column(Text, nullable=True)  # encrypted signing secret
    environment: Mapped[str] = mapped_column(String(20), default="production", server_default="production")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_fired_at: Mapped[datetime | None] = mapped_column(nullable=True)
    next_fire_at: Mapped[datetime | None] = mapped_column(nullable=True, index=True)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("triggers", read="viewer", write="builder")


class Secret(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_secrets_project_name"),)

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    encrypted_value: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


rls("secrets", read="builder", write="builder")


class Template(Base, TimestampMixin):
    __tablename__ = "templates"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    sector: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    name_en: Mapped[str] = mapped_column(String(200), default="", server_default="")
    description: Mapped[str] = mapped_column(Text)
    description_en: Mapped[str] = mapped_column(Text, default="", server_default="")
    repo_snapshot: Mapped[str] = mapped_column(Text)  # path of the template directory in packages/templates
    preview_image: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    manifest: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    public: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(default=0, server_default="0")


class ComposerSession(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "composer_sessions"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(20), default="standard", server_default="standard"
    )  # fast|standard|powerful
    # asking | planning | awaiting_approval | building | done | done_with_warnings | blocked | rejected | stopped
    status: Mapped[str] = mapped_column(String(30))
    request: Mapped[str] = mapped_column(Text)
    messages: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    plan: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    builders: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    template_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    cost_usd: Mapped[float] = mapped_column(default=0, server_default="0")
    credits: Mapped[float] = mapped_column(default=0, server_default="0")


rls("composer_sessions", read="viewer", write="builder")


class Alarm(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "alarms"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    # error_rate | latency_p95_ms | cost_usd | runs | custom:<metric_id>
    metric: Mapped[str] = mapped_column(String(80))
    comparator: Mapped[str] = mapped_column(String(4), default=">", server_default=">")
    threshold: Mapped[float] = mapped_column()
    window_minutes: Mapped[int] = mapped_column(default=60, server_default="60")
    channels: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))  # email|slack
    # Scope and delivery options (migration 0013): {"environment", "channel", "workforce_name", "slack_channel"}
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    state: Mapped[str] = mapped_column(String(10), default="ok", server_default="ok")  # ok | firing
    last_value: Mapped[float | None] = mapped_column(nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("alarms", read="viewer", write="admin")


class CustomMetric(Base, IdMixin, OrgScoped, CreatedMixin):
    """Metric defined over traces: count/sum/avg of spans matching a filter."""

    __tablename__ = "custom_metrics"

    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    # {"aggregation": "count"|"sum"|"avg", "field": "cost_usd"|"duration_ms"|..., "filter": {"kind": "tool", "name": "x"}}
    definition: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("custom_metrics", read="viewer", write="admin")
