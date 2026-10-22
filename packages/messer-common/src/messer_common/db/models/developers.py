"""Developer access: OAuth 2.1 clients and grants for the MCP server and other developer tools (migration 0015).

* ``oauth_clients`` — clients registered dynamically (RFC 7591). Global (not organization-scoped) and invisible to
  the application role: only the OAuth endpoints read and write them on the owner connection.
* ``oauth_grants`` — one authorization of a client by a user for one organization. Its current access token is an
  ``api_keys`` row (``api_keys.oauth_grant_id``) so it authenticates everywhere an API key does; the refresh token
  is stored here as a keyed hash and rotates on every use.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, CreatedMixin, IdMixin, OrgScoped, rls


class OAuthClient(Base, CreatedMixin):
    __tablename__ = "oauth_clients"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # the public client_id
    client_name: Mapped[str] = mapped_column(String(200))
    redirect_uris: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    grant_types: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    token_endpoint_auth_method: Mapped[str] = mapped_column(String(30), default="none", server_default="none")
    client_secret_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    scope: Mapped[str] = mapped_column(Text, default="", server_default="")
    client_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    software_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)


class OAuthGrant(Base, IdMixin, OrgScoped, CreatedMixin):
    __tablename__ = "oauth_grants"
    __table_args__ = (Index("ix_oauth_grants_user", "user_id", "org_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id", ondelete="CASCADE"))
    scopes: Mapped[list[Any]] = mapped_column(default=list, server_default=text("'[]'::jsonb"))
    resource: Mapped[str | None] = mapped_column(Text, nullable=True)  # RFC 8707 resource indicator
    refresh_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


# Admins see every connected application of the organization; writes happen on the owner connection only.
rls("oauth_grants", read="admin", write="system")
