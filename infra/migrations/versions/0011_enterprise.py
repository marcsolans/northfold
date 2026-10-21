"""Phase 11 enterprise (SSO, SCIM, GDPR, residency).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-21

Reserved migration slot owned by the enterprise workstream. Add DDL here; new tables must enable RLS
with policies following the pattern in 0002 (messer.has_role(org_id, ...)).
"""

from collections.abc import Sequence

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
