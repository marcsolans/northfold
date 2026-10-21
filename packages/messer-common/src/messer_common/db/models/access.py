"""Organizations, users, memberships, auth and SSO."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls

ROLES = ("owner", "admin", "builder", "viewer")


class Org(Base, IdMixin, TimestampMixin):
    __tablename__ = "orgs"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    region: Mapped[str] = mapped_column(String(40), default="eu-central-1", server_default="eu-central-1")
    data_residency: Mapped[str] = mapped_column(String(20), default="standard", server_default="standard")
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    trace_retention_days: Mapped[int] = mapped_column(default=90, server_default="90")
    conversation_retention_days: Mapped[int] = mapped_column(default=365, server_default="365")
    onboarding: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    last_active_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    # Equals the Supabase auth uid when Supabase Auth is used.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    locale: Mapped[str] = mapped_column(String(8), default="es", server_default="es")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AuthCredential(Base, TimestampMixin):
    """Local authentication data (used when Supabase Auth is not configured) and MFA."""

    __tablename__ = "auth_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    mfa_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    mfa_recovery_codes: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    failed_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(nullable=True)


class AuthSession(Base, IdMixin, CreatedMixin):
    """Refresh-token sessions for local auth. Only a hash of the refresh token is stored."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    impersonated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class OneTimeToken(Base, IdMixin, CreatedMixin):
    """Single-use tokens: email verification, password reset, signed approval links, OAuth state."""

    __tablename__ = "one_time_tokens"

    purpose: Mapped[str] = mapped_column(String(40), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    expires_at: Mapped[datetime] = mapped_column()
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Membership(Base, OrgScoped, CreatedMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("org_id", "user_id", name="uq_memberships_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20), default="manual", server_default="manual")  # manual|sso|scim


rls("memberships", read="viewer", write="admin")


class Invitation(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column()
    accepted_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("invitations", read="admin", write="admin")


class SsoConnection(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "sso_connections"

    type: Mapped[str] = mapped_column(String(10))  # saml | oidc
    name: Mapped[str] = mapped_column(String(200), default="SSO", server_default="SSO")
    config_encrypted: Mapped[str] = mapped_column(Text)
    default_role: Mapped[str] = mapped_column(String(20), default="viewer", server_default="viewer")
    domain: Mapped[str] = mapped_column(String(255), index=True)
    enforce: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


rls("sso_connections", read="admin", write="admin")


class SsoGroupMapping(Base, IdMixin, OrgScoped):
    __tablename__ = "sso_group_mappings"

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sso_connections.id", ondelete="CASCADE"))
    external_group: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))


rls("sso_group_mappings", read="admin", write="admin")


class ScimToken(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "scim_tokens"

    hashed_token: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(String(200), default="SCIM", server_default="SCIM")
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("scim_tokens", read="admin", write="admin")


class ApiKey(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "api_keys"

    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(24))
    hashed_key: Mapped[str] = mapped_column(String(128), unique=True)
    scopes: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("api_keys", read="builder", write="admin")


class AuditLog(Base, IdMixin, CreatedMixin):
    """Insert-only audit trail (UPDATE/DELETE revoked from the application role)."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_org_created", "org_id", "created_at"),)

    org_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    impersonated_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    diff: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class Notification(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "read_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    channel: Mapped[str] = mapped_column(String(20), default="in_app", server_default="in_app")
    read_at: Mapped[datetime | None] = mapped_column(nullable=True)


class DataRequest(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "data_requests"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    scope: Mapped[str] = mapped_column(String(10), default="user", server_default="user")  # user | org
    kind: Mapped[str] = mapped_column(String(10))  # export | delete
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("data_requests", read="admin", write="admin")
