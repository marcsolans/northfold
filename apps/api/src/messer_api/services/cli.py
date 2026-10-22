"""Support for the ``messer`` CLI and other developer tools: identity of a credential and CLI-created projects."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import ApiKey, Environment, Org, Project, User
from messer_common.db.models.developers import OAuthClient, OAuthGrant
from messer_common.projects_repo import ProjectRepo
from messer_common.settings import get_settings
from messer_common.studio.project_files import initial_project_files

from . import limits
from . import projects as projects_svc
from .git_push import SCAFFOLD_AUTHOR, SCAFFOLD_EMAIL, SCAFFOLD_MESSAGE


def api_base_url() -> str:
    """Base URL of the platform API for engine/CLI calls (``base_url`` in ``~/.messer/config``)."""
    return f"{get_settings().messer_api_url.rstrip('/')}/api/v1"


def git_url(org_id: uuid.UUID, project_id: uuid.UUID) -> str:
    return f"{api_base_url()}/orgs/{org_id}/projects/{project_id}/git"


async def whoami(principal: Principal) -> dict[str, Any]:
    assert principal.org_id is not None
    async with system_session() as s:
        org = await s.get(Org, principal.org_id)
        user = await s.get(User, principal.user_id) if principal.user_id else None
        key = await s.get(ApiKey, principal.api_key_id) if principal.api_key_id else None
        oauth: dict[str, Any] | None = None
        if key is not None and key.oauth_grant_id is not None:
            grant = await s.get(OAuthGrant, key.oauth_grant_id)
            client = await s.get(OAuthClient, grant.client_id) if grant else None
            oauth = {
                "grant_id": str(key.oauth_grant_id),
                "client_id": grant.client_id if grant else None,
                "client_name": client.client_name if client else None,
            }
    auth = "session" if key is None else ("oauth" if oauth else "api_key")
    settings = get_settings()
    return {
        "auth": auth,
        "role": principal.role,
        "user": {"id": str(user.id), "email": user.email, "name": user.name} if user else None,
        "org": {"id": str(org.id), "name": org.name, "slug": org.slug} if org else {"id": str(principal.org_id)},
        "api_key": (
            {
                "id": str(key.id),
                "name": key.name,
                "prefix": key.prefix,
                "project_id": str(key.project_id) if key.project_id else None,
                "scopes": list(key.scopes or []),
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
            }
            if key is not None
            else None
        ),
        "oauth": oauth,
        "api_url": settings.messer_api_url.rstrip("/"),
        "base_url": api_base_url(),
        "web_url": settings.messer_web_url.rstrip("/"),
        "mcp_url": f"{settings.messer_mcp_url.rstrip('/')}/mcp",
    }


async def create_scaffold_project(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str,
    description: str = "",
    default_model_tier: str = "standard",
    origin: dict[str, Any] | None = None,
) -> Project:
    """A new project whose only commit is the CLI scaffold, so the first ``messer push`` of a local repository
    replaces it with the local history (see :func:`messer_api.services.git_push.is_cli_scaffold`)."""
    assert principal.org_id is not None
    await limits.require_project_capacity(session, principal.org_id)
    project_id = uuid.uuid4()
    repo = ProjectRepo.for_project(str(project_id))
    project = Project(
        id=project_id,
        org_id=principal.org_id,
        name=name.strip(),
        slug=await projects_svc._unique_project_slug(session, principal.org_id, name),
        description=description,
        repo_path=str(repo.path),
        default_model_tier=default_model_tier,
        created_by=principal.user_id,
    )
    session.add(project)
    await session.flush()
    for env_name in projects_svc.ENVIRONMENTS:
        session.add(Environment(org_id=principal.org_id, project_id=project_id, name=env_name))
    files = initial_project_files(
        project_id=str(project_id), name=project.name, description=description, default_tier=default_model_tier
    )
    await repo.init(files, message=SCAFFOLD_MESSAGE, author=SCAFFOLD_AUTHOR, email=SCAFFOLD_EMAIL)
    await audit.record(
        session,
        action="project.created",
        principal=principal,
        entity_type="project",
        entity_id=project_id,
        diff={"name": project.name, "source": "cli", "origin": origin or {}},
    )
    return project
