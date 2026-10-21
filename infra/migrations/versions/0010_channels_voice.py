"""Phase 8 channels and voice.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21

Reserved migration slot owned by the channels_voice workstream. Add DDL here; new tables must enable RLS
with policies following the pattern in 0002 (messer.has_role(org_id, ...)).
"""

from collections.abc import Sequence

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
