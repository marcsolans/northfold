"""/api/v1/api-keys — organization API keys (shown once, stored hashed, optional project scope and scopes)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import ApiKey, Project
from messer_common.security import generate_api_key, hash_token

from ..deps import get_db, require_role
from ..errors import ApiError, NotFound

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

SCOPES = (
    "runs:write",
    "runs:read",
    "projects:read",
    "projects:write",
    "knowledge:read",
    "knowledge:write",
    "deployments:write",
    "evals:run",
)


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    project_id: uuid.UUID | None = None
    scopes: list[str] = Field(default_factory=list, description="Empty = every scope of the builder role")


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str
    project_id: uuid.UUID | None
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


def _out(k: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=k.id,
        name=k.name,
        prefix=k.prefix,
        project_id=k.project_id,
        scopes=list(k.scopes or []),
        created_at=k.created_at,
        last_used_at=k.last_used_at,
        revoked_at=k.revoked_at,
    )


@router.get("/scopes")
async def list_scopes() -> list[str]:
    return list(SCOPES)


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    principal: Principal = Depends(require_role("builder")), session: AsyncSession = Depends(get_db)
) -> list[ApiKeyOut]:
    rows = (
        (
            await session.execute(
                select(ApiKey).where(ApiKey.org_id == principal.org_id).order_by(ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_out(k) for k in rows]


@router.post("", status_code=201)
async def create_key(
    body: ApiKeyIn, principal: Principal = Depends(require_role("admin")), session: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    unknown = sorted(set(body.scopes) - set(SCOPES))
    if unknown:
        raise ApiError(f"Permisos desconocidos: {', '.join(unknown)}", code="invalid_scopes")
    if body.project_id is not None:
        project = await session.get(Project, body.project_id)
        if project is None or project.org_id != principal.org_id:
            raise NotFound("Proyecto no encontrado")
    full, prefix = generate_api_key()
    key = ApiKey(
        org_id=principal.org_id,
        project_id=body.project_id,
        name=body.name.strip(),
        prefix=prefix,
        hashed_key=hash_token(full),
        scopes=sorted(set(body.scopes)),
        created_by=principal.user_id,
    )
    session.add(key)
    await session.flush()
    await audit.record(
        session,
        action="api_key.created",
        principal=principal,
        entity_type="api_key",
        entity_id=key.id,
        diff={"name": key.name, "scopes": key.scopes, "project_id": str(body.project_id) if body.project_id else None},
    )
    return {**_out(key).model_dump(mode="json"), "key": full}


@router.delete("/{key_id}", status_code=204)
async def revoke_key(
    key_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), session: AsyncSession = Depends(get_db)
) -> None:
    key = await session.get(ApiKey, key_id)
    if key is None or key.org_id != principal.org_id:
        raise NotFound("API key no encontrada")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await audit.record(
            session,
            action="api_key.revoked",
            principal=principal,
            entity_type="api_key",
            entity_id=key.id,
            diff={"name": key.name},
        )
