"""GitHub sync: ``/api/v1/projects/{id}/github`` (status, connect, sync, disconnect) and the public webhook
``POST /api/github/webhook`` (``X-Hub-Signature-256``: the GitHub App secret, or the project's own secret in
personal-token mode)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal
from messer_common.projects_repo import ProjectRepo, register_commit_hook

from ..deps import client_ip, ensure_project_access, get_db, require_role
from ..errors import ApiError, RateLimited
from ..ratelimit import hit
from ..services import github as svc
from ..services import projects as projects_svc

router = APIRouter(prefix="/projects/{project_id}/github", tags=["github"])
public_router = APIRouter(tags=["github"])

# Every Messer commit (Studio, Composer, API) of a connected project enqueues a debounced push.
register_commit_hook(svc.on_commit)

MAX_WEBHOOK_BYTES = 10 * 1024 * 1024


class ConnectIn(BaseModel):
    repo: str = Field(min_length=3, max_length=200, description="owner/name")
    branch: str | None = Field(default=None, max_length=200)
    mode: Literal["app", "pat"] = "pat"
    token: str | None = Field(default=None, max_length=500, description="Fine-grained personal access token")
    installation_id: int | None = Field(default=None, ge=1)


async def _project(db: AsyncSession, principal: Principal, project_id: uuid.UUID) -> Any:
    ensure_project_access(principal, project_id)
    return await projects_svc.get_project(db, project_id)


async def _status(project: Any) -> dict[str, Any]:
    repo = ProjectRepo.for_project(str(project.id))
    return svc.status(project, head=await svc.repo_head(repo))


@router.get("")
async def get_status(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return await _status(await _project(db, principal, project_id))


@router.put("")
async def connect(
    project_id: uuid.UUID,
    body: ConnectIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Connect or reconfigure. In personal-token mode, when the webhook cannot be created automatically, the
    response carries ``webhook_secret`` once, to paste in the repository's webhook settings."""
    project = await _project(db, principal, project_id)
    return await svc.connect(
        db,
        principal,
        project,
        repo=body.repo,
        branch=body.branch,
        mode=body.mode,
        token=body.token,
        installation_id=body.installation_id,
    )


@router.post("/sync", status_code=202)
async def sync_now(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project = await _project(db, principal, project_id)
    if not svc.is_connected(project):
        raise ApiError("El proyecto no está conectado a GitHub", code="github_not_connected")
    job = await svc.enqueue_sync(project.id, reason="manual")
    return {"queued": True, "job_id": job}


@router.post("/webhook-secret")
async def rotate_secret(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    project = await _project(db, principal, project_id)
    secret = await svc.rotate_webhook_secret(db, principal, project)
    return {"webhook_secret": secret, "webhook_url": svc.webhook_url()}


@router.delete("", status_code=204)
async def disconnect(
    project_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    project = await _project(db, principal, project_id)
    await svc.disconnect(db, principal, project)
    return Response(status_code=204)


@public_router.post("/api/github/webhook")
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
) -> JSONResponse:
    allowed, retry_after = await hit(f"github-webhook:{client_ip(request) or 'unknown'}", limit=600, window_s=60)
    if not allowed:
        raise RateLimited("Demasiadas entregas de webhook", details={"retry_after": retry_after})
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise ApiError("El cuerpo supera 10 MB", code="payload_too_large", status_code=413)
    status_code, payload = await svc.handle_webhook(body, event=x_github_event, signature=x_hub_signature_256)
    return JSONResponse(payload, status_code=status_code)
