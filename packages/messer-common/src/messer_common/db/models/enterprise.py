"""Enterprise identity: verified domains, SSO/SCIM identities and SCIM groups (phase 11, migration 0011).

* ``org_domains``      — email domains an organization proved it controls (DNS TXT). SSO login, SSO
                         enforcement and SCIM user creation are only honoured for verified domains, so an
                         organization can never assert identities for a domain it does not own.
* ``org_identities``   — one row per (organization, user) managed by the identity provider: the SSO subject
                         of the last login and/or the SCIM ``User`` resource (``id`` of the SCIM resource is the
                         Messer ``user_id``). Deprovisioned SCIM users keep their row with ``active = false``.
* ``scim_groups`` / ``scim_group_members`` — SCIM ``Group`` resources; roles derive from them through
                         ``sso_group_mappings``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, TimestampMixin, rls


class OrgDomain(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "org_domains"
    __table_args__ = (
        UniqueConstraint("org_id", "domain", name="uq_org_domains_org_domain"),
        # A domain can be verified by a single organization.
        Index(
            "uq_org_domains_verified_domain", "domain", unique=True, postgresql_where=text("verified_at IS NOT NULL")
        ),
    )

    domain: Mapped[str] = mapped_column(String(255), index=True)
    verification_token: Mapped[str] = mapped_column(String(80))
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    verification_method: Mapped[str | None] = mapped_column(String(20), nullable=True)  # dns | manual
    last_checked_at: Mapped[datetime | None] = mapped_column(nullable=True)


rls("org_domains", read="admin", write="admin")


class OrgIdentity(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "org_identities"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_identities_org_user"),
        Index(
            "uq_org_identities_connection_subject",
            "connection_id",
            "sso_subject",
            unique=True,
            postgresql_where=text("sso_subject IS NOT NULL"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # SSO
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sso_connections.id", ondelete="SET NULL"), nullable=True
    )
    sso_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sso_groups: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # SCIM
    scim_managed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    scim_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scim_user_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    given_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    family_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    attributes: Mapped[dict[str, Any]] = mapped_column(default=dict, server_default=text("'{}'::jsonb"))


rls("org_identities", read="admin", write="admin")


class ScimGroup(Base, IdMixin, OrgScoped, TimestampMixin):
    __tablename__ = "scim_groups"
    __table_args__ = (UniqueConstraint("org_id", "display_name", name="uq_scim_groups_org_display_name"),)

    display_name: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


rls("scim_groups", read="admin", write="admin")


class ScimGroupMember(Base, OrgScoped, CreatedMixin):
    __tablename__ = "scim_group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scim_groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)


rls("scim_group_members", read="admin", write="admin")
