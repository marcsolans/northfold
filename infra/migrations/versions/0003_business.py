"""Phase 2 business (plans, billing, credits, onboarding, backoffice).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

Tables owned by the business workstream:

* ``simulated_checkouts`` — checkout sessions of the simulated billing provider (no Stripe key).
* ``billing_notices`` — idempotency markers for lifecycle messages (trial emails, payment failures, ...).

Both are written only on the owner connection ("system"); the application role reads them through RLS.
Budgets get one scope per organization (org-wide) and one per project.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role) — writes happen on the owner connection only.
POLICIES: list[tuple[str, str]] = [
    ("simulated_checkouts", "owner"),
    ("billing_notices", "admin"),
]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"

    op.create_table(
        "simulated_checkouts",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("plan_id", sa.String(length=40), nullable=True),
        sa.Column("interval", sa.String(length=10), nullable=True),
        sa.Column("pack_id", sa.String(length=40), nullable=True),
        sa.Column("amount_eur", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="open", nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_simulated_checkouts_org_id_orgs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_simulated_checkouts_plan_id_plans")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_simulated_checkouts_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_simulated_checkouts")),
    )
    op.create_index(op.f("ix_simulated_checkouts_org_id"), "simulated_checkouts", ["org_id"], unique=False)

    op.create_table(
        "billing_notices",
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("ref", sa.String(length=160), server_default="", nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["org_id"], ["orgs.id"], name=op.f("fk_billing_notices_org_id_orgs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_notices")),
        sa.UniqueConstraint("org_id", "kind", "ref", name="uq_billing_notices_org_kind_ref"),
    )
    op.create_index(op.f("ix_billing_notices_org_id"), "billing_notices", ["org_id"], unique=False)

    # One org-wide budget per organization and one budget per project.
    op.execute("CREATE UNIQUE INDEX uq_budgets_org_scope ON public.budgets (org_id) WHERE project_id IS NULL")
    op.execute(
        "CREATE UNIQUE INDEX uq_budgets_project_scope ON public.budgets (org_id, project_id) "
        "WHERE project_id IS NOT NULL"
    )
    # Usage aggregation for the backoffice and the credits page (ledger by kind and month).
    op.execute("CREATE INDEX ix_credit_ledger_org_kind_created ON public.credit_ledger (org_id, kind, created_at)")

    for table, read in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.ix_credit_ledger_org_kind_created")
    op.execute("DROP INDEX IF EXISTS public.uq_budgets_project_scope")
    op.execute("DROP INDEX IF EXISTS public.uq_budgets_org_scope")
    op.drop_table("billing_notices")
    op.drop_table("simulated_checkouts")
