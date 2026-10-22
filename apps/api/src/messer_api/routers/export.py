"""``GET /api/v1/projects/{id}/export.zip?ref=`` — self-contained export that starts with ``docker compose up``."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal

from ..deps import ensure_project_access, get_db, require_role
from ..errors import RateLimited
from ..ratelimit import hit
from ..services import export as svc
from ..services import projects as projects_svc

router = APIRouter(prefix="/projects", tags=["export"])


@router.get(
    "/{project_id}/export.zip",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/zip": {}}, "description": "Project export (.zip)"}},
)
async def export_zip(
    project_id: uuid.UUID,
    ref: str = "HEAD",
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    allowed, retry_after = await hit(f"export:{principal.user_id or principal.api_key_id}", limit=10, window_s=60)
    if not allowed:
        raise RateLimited("Demasiadas exportaciones seguidas", details={"retry_after": retry_after})
    ensure_project_access(principal, project_id)
    project = await projects_svc.get_project(db, project_id)
    result = await svc.build_export(db, principal, project, ref)
    return StreamingResponse(
        svc.stream_file(result.path),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "Content-Length": str(result.size),
            "X-Messer-Commit": result.commit,
            "Cache-Control": "no-store",
        },
    )
