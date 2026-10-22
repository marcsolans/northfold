"""Phase 4 connectors, syncs, connector agents.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21

Owned by the connectors workstream:
* ``connector_events``: requests received by generic inbound webhooks (HMAC-verified), consumed by workflow
  triggers through the ``webhooks`` adapter. Written on the owner connection only; members read, admins delete.
* Index for the scheduler query that picks due syncs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role, write_role, delete_role) — "system" = no policy for the application role.
POLICIES: list[tuple[str, str, str, str]] = [
    ("connector_events", "viewer", "system", "admin"),
]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"

    op.create_table(
        "connector_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event", sa.String(60), nullable=False, server_default="received"),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("headers", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("query", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_connector_events_org_id", "connector_events", ["org_id"])
    op.create_index("ix_connector_events_connection", "connector_events", ["connection_id", "id"])
    op.create_index("ix_connector_events_created", "connector_events", ["connection_id", "created_at", "id"])

    op.add_column(
        "syncs", sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb"))
    )

    # Due syncs: WHERE schedule IS NOT NULL AND next_run_at <= now().
    op.create_index(
        "ix_syncs_due",
        "syncs",
        ["next_run_at"],
        postgresql_where=sa.text("schedule IS NOT NULL"),
    )
    op.create_index(
        "ix_connections_agent", "connections", ["agent_id"], postgresql_where=sa.text("agent_id IS NOT NULL")
    )

    for table, read, write, delete in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )
        if write != "system":
            op.execute(
                f'CREATE POLICY "{table}_insert" ON public."{table}" FOR INSERT TO "{app_user}" '
                f"WITH CHECK (messer.has_role(org_id, {_q(write)}))"
            )
            op.execute(
                f'CREATE POLICY "{table}_update" ON public."{table}" FOR UPDATE TO "{app_user}" '
                f"USING (messer.has_role(org_id, {_q(write)})) WITH CHECK (messer.has_role(org_id, {_q(write)}))"
            )
        if delete != "system":
            op.execute(
                f'CREATE POLICY "{table}_delete" ON public."{table}" FOR DELETE TO "{app_user}" '
                f"USING (messer.has_role(org_id, {_q(delete)}))"
            )


def downgrade() -> None:
    op.drop_index("ix_connections_agent", table_name="connections")
    op.drop_index("ix_syncs_due", table_name="syncs")
    op.drop_column("syncs", "options")
    op.drop_table("connector_events")
