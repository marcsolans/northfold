"""Phase 11 enterprise (SSO, SCIM, GDPR, residency).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21

* New tables: org_domains (verified email domains), org_identities (SSO subjects / SCIM users),
  scim_groups, scim_group_members — all with row level security for the application role.
* data_requests.org_id becomes nullable with ON DELETE SET NULL, so the verifiable report of an
  organization deletion outlives the organization (visible to superadmins only).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role, write_role, delete_role) — same semantics as 0002.
POLICIES: list[tuple[str, str, str, str]] = [
    ("org_domains", "admin", "admin", "admin"),
    ("org_identities", "admin", "admin", "admin"),
    ("scim_groups", "admin", "admin", "admin"),
    ("scim_group_members", "admin", "admin", "admin"),
]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _app_user() -> str:
    parsed = make_url(get_settings().database_app_url)
    if not parsed.username:
        raise RuntimeError("DATABASE_APP_URL must include a username")
    return parsed.username


def upgrade() -> None:
    op.create_table(
        "org_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("verification_token", sa.String(length=80), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_by", sa.UUID(), nullable=True),
        sa.Column("verification_method", sa.String(length=20), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name="fk_org_domains_org_id_orgs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["verified_by"], ["users.id"], name="fk_org_domains_verified_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_domains"),
        sa.UniqueConstraint("org_id", "domain", name="uq_org_domains_org_domain"),
    )
    op.create_index("ix_org_domains_org_id", "org_domains", ["org_id"])
    op.create_index("ix_org_domains_domain", "org_domains", ["domain"])
    op.create_index(
        "uq_org_domains_verified_domain",
        "org_domains",
        ["domain"],
        unique=True,
        postgresql_where=sa.text("verified_at IS NOT NULL"),
    )

    op.create_table(
        "org_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connection_id", sa.UUID(), nullable=True),
        sa.Column("sso_subject", sa.String(length=255), nullable=True),
        sa.Column(
            "sso_groups", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scim_managed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("scim_external_id", sa.String(length=255), nullable=True),
        sa.Column("scim_user_name", sa.String(length=320), nullable=True),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("given_name", sa.String(length=200), nullable=True),
        sa.Column("family_name", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column(
            "attributes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name="fk_org_identities_org_id_orgs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_org_identities_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["sso_connections.id"],
            name="fk_org_identities_connection_id_sso_connections",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_org_identities"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_org_identities_org_user"),
    )
    op.create_index("ix_org_identities_org_id", "org_identities", ["org_id"])
    op.create_index("ix_org_identities_user_id", "org_identities", ["user_id"])
    op.create_index(
        "uq_org_identities_connection_subject",
        "org_identities",
        ["connection_id", "sso_subject"],
        unique=True,
        postgresql_where=sa.text("sso_subject IS NOT NULL"),
    )

    op.create_table(
        "scim_groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name="fk_scim_groups_org_id_orgs", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_scim_groups"),
        sa.UniqueConstraint("org_id", "display_name", name="uq_scim_groups_org_display_name"),
    )
    op.create_index("ix_scim_groups_org_id", "scim_groups", ["org_id"])

    op.create_table(
        "scim_group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name="fk_scim_group_members_org_id_orgs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["group_id"], ["scim_groups.id"], name="fk_scim_group_members_group_id_scim_groups", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_scim_group_members_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "user_id", name="pk_scim_group_members"),
    )
    op.create_index("ix_scim_group_members_org_id", "scim_group_members", ["org_id"])
    op.create_index("ix_scim_group_members_user_id", "scim_group_members", ["user_id"])

    # Discovery looks connections up by domain.
    op.create_index("ix_sso_connections_domain_lower", "sso_connections", [sa.text("lower(domain)")])

    # data_requests survive the deletion of their organization (verifiable deletion report).
    op.drop_constraint("fk_data_requests_org_id_orgs", "data_requests", type_="foreignkey")
    op.alter_column("data_requests", "org_id", existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        "fk_data_requests_org_id_orgs", "data_requests", "orgs", ["org_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_data_requests_subject_user_id", "data_requests", ["subject_user_id"])

    # ------------------------------------------------------------------ row level security
    app_user = _app_user()
    for table, read, write, delete in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_insert" ON public."{table}" FOR INSERT TO "{app_user}" '
            f"WITH CHECK (messer.has_role(org_id, {_q(write)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_update" ON public."{table}" FOR UPDATE TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(write)})) WITH CHECK (messer.has_role(org_id, {_q(write)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_delete" ON public."{table}" FOR DELETE TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(delete)}))"
        )


def downgrade() -> None:
    op.drop_index("ix_data_requests_subject_user_id", table_name="data_requests")
    op.drop_constraint("fk_data_requests_org_id_orgs", "data_requests", type_="foreignkey")
    op.execute("DELETE FROM data_requests WHERE org_id IS NULL")
    op.alter_column("data_requests", "org_id", existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        "fk_data_requests_org_id_orgs", "data_requests", "orgs", ["org_id"], ["id"], ondelete="CASCADE"
    )
    op.drop_index("ix_sso_connections_domain_lower", table_name="sso_connections")
    for table in ("scim_group_members", "scim_groups", "org_identities", "org_domains"):
        op.drop_table(table)
