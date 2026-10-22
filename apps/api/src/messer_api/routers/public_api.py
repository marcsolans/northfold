"""Public REST API (``/v1``) for running agents and workflows from other systems (API key or session).

* ``POST /v1/projects/{project_id}/workforce/{name}/run``    — synchronous run, returns the output.
* ``POST /v1/projects/{project_id}/workforce/{name}/stream`` — Server-Sent Events with the engine events.
* ``GET  /v1/runs/{run_id}``                                  — status, output, cost.

``session_id`` keeps conversation memory across calls (one thread per session id).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import runtime_client
from messer_common.db import Principal, rls_session
from messer_common.db.models import Conversation, Run
from messer_common.execution import NotDeployed, resolve_target
from messer_common.runtime_client import RuntimeUnavailable

from ..deps import ensure_project_access, get_db, require_role, require_scope
from ..errors import ApiError, NotFound
from ..services import projects as svc
from .studio import relay_run, stream_response

public_router = APIRouter(prefix="/v1", tags=["public-api"])

API_CHANNEL = "api"


class RunIn(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict, description='Agent: {"prompt": "..."}; workflow: its params')
    session_id: str | None = Field(default=None, max_length=255, description="Conversation thread for memory")
    user: str | None = Field(default=None, max_length=255, description="Your end user's id (for analytics)")
    environment: Literal["production", "development"] = "production"


class RunOut(BaseModel):
    run_id: str
    status: str
    output: Any
    error: Any = None
    cost_usd: Decimal
    credits: Decimal
    duration_ms: int | None = None
    approvals: list[dict[str, Any]] = Field(default_factory=list)


async def _prepare(principal: Principal, project_id: uuid.UUID, name: str, body: RunIn) -> dict[str, Any]:
    ensure_project_access(principal, project_id)
    async with rls_session(principal) as session:
        project = await svc.get_project(session, project_id)
        member = await svc.get_member(session, project, name)
        try:
            target = await resolve_target(session, project.id, body.environment)
        except NotDeployed as exc:
            raise ApiError(
                str(exc),
                code="not_deployed",
                status_code=409,
                details={"hint": "Despliega el proyecto o usa environment=development"},
            ) from exc
        conversation_id: uuid.UUID | None = None
        parent: uuid.UUID | None = None
        if body.session_id:
            conv = (
                await session.execute(
                    select(Conversation).where(
                        Conversation.project_id == project.id,
                        Conversation.channel_key == f"{API_CHANNEL}:{member.name}",
                        Conversation.external_user_id == body.session_id,
                    )
                )
            ).scalar_one_or_none()
            if conv is None:
                conv = Conversation(
                    org_id=project.org_id,
                    project_id=project.id,
                    channel_key=f"{API_CHANNEL}:{member.name}",
                    provider=API_CHANNEL,
                    workforce_name=member.name,
                    external_user_id=body.session_id,
                    title=str(body.input.get("prompt") or "")[:80],
                )
                session.add(conv)
                await session.flush()
            conversation_id, parent = conv.id, conv.last_run_id
    return {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": member.name,
        "ref": target.ref,
        "input": body.input,
        "parent_run_id": parent.hex if parent else None,
        "environment": target.environment,
        "environment_id": str(target.environment_id) if target.environment_id else None,
        "version_id": str(target.version_id) if target.version_id else None,
        "channel": API_CHANNEL,
        "user_id": str(principal.user_id) if principal.user_id else None,
        "external_user_id": body.user,
        "conversation_id": str(conversation_id) if conversation_id else None,
    }


@public_router.post("/projects/{project_id}/workforce/{name}/run", response_model=RunOut)
async def run(
    project_id: uuid.UUID,
    name: str,
    body: RunIn,
    principal: Principal = Depends(require_role("builder")),
    _scope: Principal = Depends(require_scope("runs:write")),
) -> RunOut:
    request = await _prepare(principal, project_id, name, body)
    try:
        result = await runtime_client.run(request)
    except RuntimeUnavailable as exc:
        raise ApiError(
            "El entorno de ejecución no está disponible", code="runtime_unavailable", status_code=503
        ) from exc
    if not result.get("run_id"):
        raise ApiError(
            "No se pudo iniciar la ejecución",
            code="run_failed",
            status_code=502,
            details={"errors": result.get("errors")},
        )
    return RunOut(
        run_id=str(result["run_id"]),
        status=str(result.get("status") or "error"),
        output=result.get("output"),
        error=result.get("error") or (result.get("errors") or [None])[0],
        cost_usd=Decimal(str(result.get("cost_usd") or "0")),
        credits=Decimal(str(result.get("credits") or "0")),
        duration_ms=result.get("duration_ms"),
        approvals=result.get("approvals") or [],
    )


@public_router.post("/projects/{project_id}/workforce/{name}/stream")
async def stream(
    project_id: uuid.UUID,
    name: str,
    body: RunIn,
    principal: Principal = Depends(require_role("builder")),
    _scope: Principal = Depends(require_scope("runs:write")),
) -> StreamingResponse:
    request = await _prepare(principal, project_id, name, body)
    return stream_response(relay_run(request))


@public_router.get("/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    _scope: Principal = Depends(require_scope("runs:read")),
    session: AsyncSession = Depends(get_db),
) -> RunOut:
    row = await session.get(Run, run_id)
    if row is None or row.org_id != principal.org_id:
        raise NotFound("Ejecución no encontrada")
    ensure_project_access(principal, row.project_id)
    return RunOut(
        run_id=row.id.hex,
        status=row.status,
        output=row.output,
        error=row.error,
        cost_usd=row.cost_usd,
        credits=row.credits,
        duration_ms=row.duration_ms,
    )
