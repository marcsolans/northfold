"""Phase 10 developers: OAuth 2.1 for the MCP server and developer tools.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-22

Migration slot owned by the developers workstream (CLI, git push, MCP server, SDKs).

* ``oauth_clients``: dynamically registered OAuth clients (RFC 7591). Global table, RLS enabled without policies
  (only the OAuth endpoints use it, on the owner connection).
* ``oauth_grants``: a user's authorization of a client for one organization (rotating refresh token hash).
  Admins read them through RLS; writes happen on the owner connection only.
* ``api_keys.expires_at`` / ``api_keys.oauth_grant_id``: OAuth access tokens are API-key rows bound to a grant.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role) — writes happen on the owner connection only ("system").
POLICIES: list[tuple[str, str]] = [("oauth_grants", "admin")]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("redirect_uris", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("grant_types", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("token_endpoint_auth_method", sa.String(length=30), server_default="none", nullable=False),
        sa.Column("client_secret_hash", sa.String(length=128), nullable=True),
        sa.Column("scope", sa.Text(), server_default="", nullable=False),
        sa.Column("client_uri", sa.Text(), nullable=True),
        sa.Column("logo_uri", sa.Text(), nullable=True),
        sa.Column("software_id", sa.String(length=200), nullable=True),
        sa.Column("software_version", sa.String(length=80), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_clients")),
    )

    op.create_table(
        "oauth_grants",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("scopes", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"], ["oauth_clients.id"], name=op.f("fk_oauth_grants_client_id_oauth_clients"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_oauth_grants_org_id_orgs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_oauth_grants_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_grants")),
        sa.UniqueConstraint("refresh_token_hash", name=op.f("uq_oauth_grants_refresh_token_hash")),
    )
    op.create_index(op.f("ix_oauth_grants_org_id"), "oauth_grants", ["org_id"], unique=False)
    op.create_index("ix_oauth_grants_user", "oauth_grants", ["user_id", "org_id"], unique=False)

    op.add_column("api_keys", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("api_keys", sa.Column("oauth_grant_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_api_keys_oauth_grant_id_oauth_grants"),
        "api_keys",
        "oauth_grants",
        ["oauth_grant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_api_keys_oauth_grant_id"), "api_keys", ["oauth_grant_id"], unique=False)

    # Global, system-only table: RLS on, no policy for the application role.
    op.execute('ALTER TABLE public."oauth_clients" ENABLE ROW LEVEL SECURITY')
    for table, read in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_api_keys_oauth_grant_id"), table_name="api_keys")
    op.drop_constraint(op.f("fk_api_keys_oauth_grant_id_oauth_grants"), "api_keys", type_="foreignkey")
    op.drop_column("api_keys", "oauth_grant_id")
    op.drop_column("api_keys", "expires_at")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
