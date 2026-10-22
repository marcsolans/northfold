"""Phase 7 governance (analytics, alarms, custom metrics, model policy).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-21

* ``alarm_events``: alarm state transitions (ok → firing → ok) with the value and what was delivered.
  Written on the owner connection only; members read them through RLS.
* ``alarms.config``: scope filters and delivery options of an alarm (environment, channel, agent, Slack channel).
* Indexes for the analytics queries: span windows per organization (custom metrics over traces), feedback by
  date, eval runs per workforce member, and one model policy per organization.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role) — writes happen on the owner connection only ("system").
POLICIES: list[tuple[str, str]] = [("alarm_events", "viewer")]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"

    op.add_column(
        "alarms",
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )

    op.create_table(
        "alarm_events",
        sa.Column("alarm_id", sa.UUID(), nullable=False),
        sa.Column("from_state", sa.String(length=10), nullable=False),
        sa.Column("to_state", sa.String(length=10), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("metric", sa.String(length=80), nullable=False),
        sa.Column("comparator", sa.String(length=4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column(
            "delivery", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["alarm_id"], ["alarms.id"], name=op.f("fk_alarm_events_alarm_id_alarms"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], name=op.f("fk_alarm_events_org_id_orgs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alarm_events")),
    )
    op.create_index(op.f("ix_alarm_events_org_id"), "alarm_events", ["org_id"], unique=False)
    op.create_index("ix_alarm_events_alarm_created", "alarm_events", ["alarm_id", "created_at"], unique=False)

    # Analytics: custom metrics over spans scan one organization's time window.
    op.execute("CREATE INDEX IF NOT EXISTS ix_spans_org_t0 ON public.spans (org_id, t0)")
    # Recent feedback comments per organization.
    op.execute("CREATE INDEX IF NOT EXISTS ix_feedback_org_created ON public.feedback (org_id, created_at)")
    # Eval comparison across versions of one workforce member.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_eval_runs_workforce_created ON public.eval_runs (workforce_id, created_at)"
    )
    # Scheduler sweep of enabled alarms.
    op.execute("CREATE INDEX IF NOT EXISTS ix_alarms_enabled ON public.alarms (enabled) WHERE enabled")
    # One model policy per organization (the API upserts it).
    op.execute(
        "DELETE FROM public.model_policies a USING public.model_policies b "
        "WHERE a.org_id = b.org_id AND a.updated_at < b.updated_at"
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_model_policies_org ON public.model_policies (org_id)")

    for table, read in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.uq_model_policies_org")
    op.execute("DROP INDEX IF EXISTS public.ix_alarms_enabled")
    op.execute("DROP INDEX IF EXISTS public.ix_eval_runs_workforce_created")
    op.execute("DROP INDEX IF EXISTS public.ix_feedback_org_created")
    op.execute("DROP INDEX IF EXISTS public.ix_spans_org_t0")
    op.drop_table("alarm_events")
    op.drop_column("alarms", "config")
