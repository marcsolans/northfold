"""Phase 4 knowledge bases.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

Reserved migration slot owned by the knowledge workstream. Add DDL here; new tables must enable RLS
with policies following the pattern in 0002 (messer.has_role(org_id, ...)).
"""

from collections.abc import Sequence

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
