"""/api/v1/projects/{id}/workforce/{name}/… — Studio playground: streaming chat with memory, evals, workflow graph."""

from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, runtime_client
from messer_common.db import Principal, rls_session
from messer_common.db.models import Conversation, EvalRun
from messer_common.runtime_client import RuntimeUnavailable
from messer_common.storage import StorageError, get_storage

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound
from ..services import projects as svc

router = APIRouter(prefix="/projects/{project_id}", tags=["studio"])

STUDIO_PROVIDER = "studio"


def sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"


async def relay_run(body: dict[str, Any], first: dict[str, Any] | None = None) -> AsyncIterator[str]:
    """Relay runtime events as SSE; runtime outages become a RUN_ERROR event instead of a broken stream."""
    if first is not None:
        yield sse(first)
    try:
        async for event in runtime_client.stream_run(body):
            yield sse(event)
    except RuntimeUnavailable as exc:
        yield sse(
            {
                "type": "RUN_ERROR",
                "error": {
                    "type": "runtime_unavailable",
                    "message": "El entorno de ejecución no está disponible. Inténtalo de nuevo en unos segundos.",
                    "detail": str(exc)[:300],
                },
            }
        )


def stream_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events, media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    conversation_id: uuid.UUID | None = None
    attachments: list[str] = Field(default_factory=list, max_length=10, description="ids from POST …/uploads")


class ConversationOut(BaseModel):
    id: uuid.UUID
    workforce_name: str
    title: str
    messages: list[dict[str, Any]]
    last_run_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    message_count: int
    last_run_id: uuid.UUID | None
    updated_at: datetime


def _conversation_out(c: Conversation) -> ConversationOut:
    return ConversationOut(
        id=c.id,
        workforce_name=c.workforce_name,
        title=c.title,
        messages=list(c.messages or []),
        last_run_id=c.last_run_id,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


async def _studio_conversation(
    session: AsyncSession, principal: Principal, project_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if (
        conv is None
        or conv.project_id != project_id
        or conv.provider != STUDIO_PROVIDER
        or conv.external_user_id != str(principal.user_id)
    ):
        raise NotFound("Conversación no encontrada")
    return conv


@router.post("/workforce/{name}/chat")
async def chat(
    project_id: uuid.UUID, name: str, body: ChatIn, principal: Principal = Depends(require_role("builder"))
) -> StreamingResponse:
    """Send a message to a member of the workforce and stream the run (engine events as SSE)."""
    ensure_project_access(principal, project_id)
    async with rls_session(principal) as session:
        project = await svc.get_project(session, project_id)
        member = await svc.get_member(session, project, name)
        if body.conversation_id is not None:
            conv = await _studio_conversation(session, principal, project_id, body.conversation_id)
            if conv.workforce_name != member.name:
                raise ApiError("La conversación pertenece a otro miembro", code="conversation_mismatch")
        else:
            conv = Conversation(
                org_id=project.org_id,
                project_id=project.id,
                channel_key=f"studio:{uuid.uuid4()}",
                provider=STUDIO_PROVIDER,
                workforce_name=member.name,
                external_user_id=str(principal.user_id),
                title=body.message.strip()[:80],
            )
            session.add(conv)
            await session.flush()
        conversation_id, parent = conv.id, conv.last_run_id
    run_body = {
        "org_id": str(project.org_id),
        "project_id": str(project.id),
        "workforce": member.name,
        "ref": "HEAD",
        "input": {"prompt": await _prompt_with_attachments(project.org_id, project.id, body)},
        "parent_run_id": parent.hex if parent else None,
        "environment": "development",
        "channel": "studio",
        "user_id": str(principal.user_id) if principal.user_id else None,
        "conversation_id": str(conversation_id),
    }
    return stream_response(relay_run(run_body, {"type": "CONVERSATION", "conversation_id": str(conversation_id)}))


@router.get("/workforce/{name}/conversations", response_model=list[ConversationSummary])
async def list_conversations(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> list[ConversationSummary]:
    ensure_project_access(principal, project_id)
    rows = (
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.project_id == project_id,
                    Conversation.workforce_name == name,
                    Conversation.provider == STUDIO_PROVIDER,
                    Conversation.external_user_id == str(principal.user_id),
                )
                .order_by(Conversation.updated_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            message_count=len(c.messages or []),
            last_run_id=c.last_run_id,
            updated_at=c.updated_at,
        )
        for c in rows
    ]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> ConversationOut:
    ensure_project_access(principal, project_id)
    return _conversation_out(await _studio_conversation(session, principal, project_id, conversation_id))


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    ensure_project_access(principal, project_id)
    conv = await _studio_conversation(session, principal, project_id, conversation_id)
    await session.delete(conv)


# ------------------------------------------------------------------------------------------------- evals


class EvalIn(BaseModel):
    tags: list[str] | None = None


class EvalRunOut(BaseModel):
    id: uuid.UUID
    status: str
    trigger: str
    passed: int
    failed: int
    results: list[dict[str, Any]]
    created_at: datetime
    finished_at: datetime | None


def _eval_out(e: EvalRun) -> EvalRunOut:
    return EvalRunOut(
        id=e.id,
        status=e.status,
        trigger=e.trigger,
        passed=e.passed,
        failed=e.failed,
        results=list(e.results or []),
        created_at=e.created_at,
        finished_at=e.finished_at,
    )


@router.post("/workforce/{name}/evals", response_model=EvalRunOut, status_code=201)
async def run_evals(
    project_id: uuid.UUID, name: str, body: EvalIn, principal: Principal = Depends(require_role("builder"))
) -> EvalRunOut:
    """Run the member's YAML evals in its sandbox against the latest code."""
    ensure_project_access(principal, project_id)
    async with rls_session(principal) as session:
        project = await svc.get_project(session, project_id)
        member = await svc.get_member(session, project, name)
        eval_run = EvalRun(org_id=project.org_id, project_id=project.id, workforce_id=member.id, trigger="manual")
        session.add(eval_run)
        await session.flush()
        eval_id = eval_run.id
    try:
        result = await runtime_client.evals(project_id, name, tags=body.tags)
        status = "error" if result.get("error") else ("passed" if result.get("failed", 0) == 0 else "failed")
    except RuntimeUnavailable as exc:
        result = {
            "results": [],
            "passed": 0,
            "failed": 0,
            "error": {"type": "runtime_unavailable", "message": str(exc)[:500]},
        }
        status = "error"
    async with rls_session(principal) as session:
        row = await session.get(EvalRun, eval_id)
        assert row is not None
        row.status = status
        row.passed = int(result.get("passed") or 0)
        row.failed = int(result.get("failed") or 0)
        row.results = list(result.get("results") or []) + ([{"error": result["error"]}] if result.get("error") else [])
        row.finished_at = datetime.now(UTC)
        await audit.record(
            session,
            action="evals.run",
            principal=principal,
            entity_type="workforce",
            entity_id=row.workforce_id,
            diff={"passed": row.passed, "failed": row.failed},
        )
        return _eval_out(row)


@router.get("/workforce/{name}/evals", response_model=list[EvalRunOut])
async def list_evals(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[EvalRunOut]:
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    member = await svc.get_member(session, project, name)
    rows = (
        (
            await session.execute(
                select(EvalRun)
                .where(EvalRun.workforce_id == member.id)
                .order_by(EvalRun.created_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [_eval_out(e) for e in rows]


@router.get("/workforce/{name}/flow")
async def workflow_graph(
    project_id: uuid.UUID,
    name: str,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Static graph of a workflow (nodes, edges) introspected from its code."""
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    await svc.get_member(session, project, name)
    try:
        return await runtime_client.flow(project_id, name)
    except RuntimeUnavailable as exc:
        raise ApiError(
            "No se pudo leer el flujo desde el entorno de ejecución",
            code="runtime_unavailable",
            status_code=503,
            details={"detail": str(exc)[:300]},
        ) from exc


# ------------------------------------------------------------------------------------- uploads & context

UPLOAD_MAX_BYTES = 20 * 1024 * 1024


def _upload_prefix(org_id: uuid.UUID, project_id: uuid.UUID) -> str:
    return f"orgs/{org_id}/projects/{project_id}/uploads/"


class UploadOut(BaseModel):
    id: str
    name: str
    mime: str
    size: int


async def _read_upload(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(f"El archivo supera {limit // (1024 * 1024)} MB", code="file_too_large", status_code=413)
    if not data:
        raise ApiError("El archivo está vacío", code="empty_file")
    return data


@router.post("/uploads", response_model=UploadOut, status_code=201)
async def upload_attachment(
    project_id: uuid.UUID,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> UploadOut:
    """Store a chat attachment (images, PDFs, documents) for the next message."""
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    data = await _read_upload(file, UPLOAD_MAX_BYTES)
    name = svc.safe_filename(file.filename or "archivo")
    mime = file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    key = f"{_upload_prefix(project.org_id, project.id)}{uuid.uuid4().hex}/{name}"
    await get_storage().put(key, data, mime)
    return UploadOut(id=key, name=name, mime=mime, size=len(data))


async def _prompt_with_attachments(org_id: uuid.UUID, project_id: uuid.UUID, body: ChatIn) -> Any:
    if not body.attachments:
        return body.message
    prefix = _upload_prefix(org_id, project_id)
    content: list[dict[str, Any]] = [{"type": "text", "text": body.message}]
    for key in body.attachments:
        if not key.startswith(prefix) or ".." in key:
            raise ApiError("Adjunto no válido", code="invalid_attachment")
        try:
            data = await get_storage().get(key)
        except StorageError as exc:
            raise NotFound("Adjunto no encontrado") from exc
        name = key.rsplit("/", 1)[-1]
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        content.append({"type": "file", "name": name, "file": f"data:{mime};base64,{base64.b64encode(data).decode()}"})
    return {"role": "user", "content": content}


@router.post("/workforce/{name}/context-files", status_code=201)
async def add_context_file(
    project_id: uuid.UUID,
    name: str,
    file: UploadFile = File(...),
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Attach a reference document whose text is appended to the agent's system prompt."""
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    member = await svc.get_member(session, project, name)
    data = await _read_upload(file, svc.CONTEXT_FILE_MAX_BYTES)
    entry = await svc.add_context_file(
        session,
        principal,
        project,
        member,
        filename=file.filename or "archivo",
        data=data,
        mime=file.content_type or "application/octet-stream",
    )
    return entry.model_dump()


@router.delete("/workforce/{name}/context-files/{filename}", status_code=204)
async def remove_context_file(
    project_id: uuid.UUID,
    name: str,
    filename: str,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    member = await svc.get_member(session, project, name)
    await svc.remove_context_file(session, principal, project, member, filename)
