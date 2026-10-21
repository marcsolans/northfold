"""Append-only audit trail helper."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import AuditLog
from .db.session import Principal


async def record(
    session: AsyncSession,
    *,
    action: str,
    principal: Principal | None = None,
    org_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    diff: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Insert an audit entry in the caller's transaction (so it commits atomically with the change)."""
    session.add(
        AuditLog(
            org_id=org_id or (principal.org_id if principal else None),
            actor_id=principal.user_id if principal else None,
            impersonated_by=principal.impersonated_by if principal else None,
            api_key_id=principal.api_key_id if principal else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            diff=_jsonable(diff or {}),
            ip=ip,
            user_agent=user_agent,
        )
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)
