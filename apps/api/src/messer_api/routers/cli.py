"""Endpoints for the ``messer`` CLI, the MCP server and the SDKs.

* ``GET  /api/v1/cli/whoami`` — who a credential is (user, organization, role, key or OAuth grant, scopes) and the
  URLs to use (``base_url`` for ``~/.messer/config``, the MCP endpoint). Used by ``messer configure`` and by the MCP
  server to verify bearer tokens.
* ``POST /api/v1/orgs/{org_id}/projects`` — create a project for ``messer push`` (the protocol of the inherited
  CLI): the repository starts with a replaceable scaffold commit and the response carries its git remote URL.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal

from ..deps import get_db, get_org_principal, require_role, require_scope
from ..errors import Forbidden, NotFound
from ..services import cli as svc

router = APIRouter(tags=["cli"])


class WhoAmIOut(BaseModel):
    auth: Literal["api_key", "oauth", "session"]
    role: str | None
    user: dict[str, Any] | None
    org: dict[str, Any]
    api_key: dict[str, Any] | None
    oauth: dict[str, Any] | None
    api_url: str
    base_url: str
    web_url: str
    mcp_url: str


class CliProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_model_tier: Literal["fast", "standard", "powerful"] = "standard"
    origin: dict[str, Any] | None = Field(default=None, description="Where the local project comes from (informative)")


class CliProjectOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    slug: str
    description: str
    git_url: str
    default_branch: str = "main"
    created_at: datetime


@router.get("/cli/whoami", response_model=WhoAmIOut)
async def whoami(principal: Principal = Depends(get_org_principal)) -> WhoAmIOut:
    return WhoAmIOut.model_validate(await svc.whoami(principal))


@router.post("/orgs/{org_id}/projects", response_model=CliProjectOut, status_code=201)
async def create_cli_project(
    org_id: uuid.UUID,
    body: CliProjectIn,
    principal: Principal = Depends(require_role("builder")),
    _scope: Principal = Depends(require_scope("projects:write")),
    db: AsyncSession = Depends(get_db),
) -> CliProjectOut:
    """Create an empty project to push a local repository into (``messer push``)."""
    if principal.org_id != org_id:
        raise NotFound("Organización no encontrada")
    if principal.project_id is not None:
        raise Forbidden("Las API keys de un proyecto no pueden crear proyectos", code="project_scope")
    project = await svc.create_scaffold_project(
        db,
        principal,
        name=body.name,
        description=body.description,
        default_model_tier=body.default_model_tier,
        origin=body.origin,
    )
    return CliProjectOut(
        id=project.id,
        org_id=project.org_id,
        name=project.name,
        slug=project.slug,
        description=project.description,
        git_url=svc.git_url(project.org_id, project.id),
        created_at=project.created_at,
    )
