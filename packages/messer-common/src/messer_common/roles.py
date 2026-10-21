"""Organization roles, lowest to highest."""

from __future__ import annotations

ROLES = ("viewer", "builder", "admin", "owner")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES, start=1)}


def at_least(role: str | None, minimum: str) -> bool:
    return ROLE_RANK.get(role or "", 0) >= ROLE_RANK.get(minimum, len(ROLES) + 1)
