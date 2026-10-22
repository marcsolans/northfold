"""Phase 12 guard.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-21

Guard playbooks keep how they were produced (``meta``: model, cost, warnings of the generation) and who changed
them last (``updated_by``). The table and its RLS policies already exist (0001/0002). An index on guard spans
serves the Guard metrics (share of turns on the declared path, cost versus no Guard, blocked actions).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "guard_playbooks",
        sa.Column(
            "meta", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
    )
    op.add_column("guard_playbooks", sa.Column("updated_by", sa.UUID(), nullable=True))
    op.execute("CREATE INDEX IF NOT EXISTS ix_spans_guard_run ON spans (run_id) WHERE kind = 'guard'")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_spans_guard_run")
    op.drop_column("guard_playbooks", "updated_by")
    op.drop_column("guard_playbooks", "meta")
