"""/api/v1/projects/{id}/secrets — project secrets (encrypted at rest; values are write-only).

Secrets are injected as environment variables into the project's sandbox (never into other projects), and are
referenced from code or MCP headers as ``$NAME``.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import Secret
from messer_common.security import encrypt

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound
from ..services import projects as project_svc

router = APIRouter(prefix="/projects/{project_id}/secrets", tags=["secrets"])

_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,119}$")
RESERVED_PREFIXES = ("MESSER_", "ANTHROPIC_", "AWS_")


class SecretOut(BaseModel):
    name: str
    created_at: datetime
    updated_at: datetime


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


@router.get("", response_model=list[SecretOut])
async def list_secrets(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> list[SecretOut]:
    ensure_project_access(principal, project_id)
    rows = (
        (await session.execute(select(Secret).where(Secret.project_id == project_id).order_by(Secret.name)))
        .scalars()
        .all()
    )
    return [SecretOut(name=s.name, created_at=s.created_at, updated_at=s.updated_at) for s in rows]


@router.put("/{name}", response_model=SecretOut)
async def put_secret(
    project_id: uuid.UUID,
    name: str,
    body: SecretIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> SecretOut:
    ensure_project_access(principal, project_id)
    if not _NAME.match(name):
        raise ApiError("Usa MAYÚSCULAS, números y guiones bajos (p. ej. CRM_TOKEN)", code="invalid_name")
    if name.startswith(RESERVED_PREFIXES):
        raise ApiError("Ese prefijo está reservado por la plataforma", code="reserved_name")
    project = await project_svc.get_project(session, project_id)
    row = (
        await session.execute(select(Secret).where(Secret.project_id == project_id, Secret.name == name))
    ).scalar_one_or_none()
    if row is None:
        row = Secret(
            org_id=project.org_id,
            project_id=project_id,
            name=name,
            encrypted_value=encrypt(body.value),
            created_by=principal.user_id,
        )
        session.add(row)
        action = "secret.created"
    else:
        row.encrypted_value = encrypt(body.value)
        action = "secret.updated"
    await session.flush()
    await session.refresh(row)
    await audit.record(
        session,
        action=action,
        principal=principal,
        entity_type="secret",
        entity_id=row.id,
        diff={"name": name, "project_id": str(project_id)},
    )
    return SecretOut(name=row.name, created_at=row.created_at, updated_at=row.updated_at)


@router.delete("/{name}", status_code=204)
async def delete_secret(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    ensure_project_access(principal, project_id)
    row = (
        await session.execute(select(Secret).where(Secret.project_id == project_id, Secret.name == name))
    ).scalar_one_or_none()
    if row is None:
        raise NotFound("Secreto no encontrado")
    await audit.record(
        session,
        action="secret.deleted",
        principal=principal,
        entity_type="secret",
        entity_id=row.id,
        diff={"name": name},
    )
    await session.delete(row)
