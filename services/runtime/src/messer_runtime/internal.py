"""Internal API of the runtime (``/internal/v1``).

Two kinds of callers:

* **Sandboxes** (sandbox token, scoped to one org/project/commit): the engine's platform integration —
  tracing (GET/PATCH runs), the model gateway, the tool proxy, knowledge search/SQL and connector actions.
* **The control plane** (service token): start runs (streaming or synchronous), run evals, read workflow
  graphs, sandbox stats, and call the model gateway for platform features (Composer, Guard, judges).
"""

from __future__ import annotations

import html
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Connection, KnowledgeBase, Workforce
from messer_common.email import OutgoingEmail, get_email_adapter
from messer_common.logging import get_logger

from . import gateway
from .code_cache import ensure_checkout
from .persistence import load_trace, store_trace
from .runs import RunExecutor, RunRequest, _project_secrets, trace_stored
from .sandbox.manager import SandboxPool
from .tokens import SandboxClaims, check_scope, require_service, sandbox_claims

log = get_logger("messer.runtime.internal")

router = APIRouter(prefix="/internal/v1")


def _executor(request: Request) -> RunExecutor:
    return request.app.state.executor  # type: ignore[no-any-return]


def _pool(request: Request) -> SandboxPool:
    return request.app.state.pool  # type: ignore[no-any-return]


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str, ensure_ascii=False)}\n\n"


# ------------------------------------------------------------------------------------------ tracing


@router.get("/orgs/{org_id}/projects/{project_id}/runs/{run_id}")
async def get_run_trace(
    org_id: uuid.UUID, project_id: uuid.UUID, run_id: str, claims: SandboxClaims = Depends(sandbox_claims)
) -> JSONResponse:
    check_scope(claims, org_id, project_id)
    async with system_session() as s:
        trace = await load_trace(s, run_id=run_id, org_id=org_id)
    return JSONResponse({"trace": trace})


class TraceBody(BaseModel):
    parent_id: str | None = None
    trace: list[dict[str, Any]] | dict[str, Any] = Field(default_factory=list)  # list of span records
    rev: str | None = None


@router.patch("/orgs/{org_id}/projects/{project_id}/runs/{run_id}")
async def put_run_trace(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: str,
    body: TraceBody,
    claims: SandboxClaims = Depends(sandbox_claims),
) -> Response:
    check_scope(claims, org_id, project_id)
    async with system_session() as s:
        await store_trace(
            s, run_id=run_id, org_id=org_id, project_id=project_id, parent_id=body.parent_id, trace=body.trace
        )
    trace_stored(run_id)
    return Response(status_code=204)


# ------------------------------------------------------------------------------------- model gateway


@router.post("/orgs/{org_id}/proxies/anthropic/v1/messages")
async def anthropic_messages(org_id: uuid.UUID, request: Request) -> Response:
    """Anthropic Messages API compatible. Sandbox token (agents) or service token (platform features)."""
    project_id: uuid.UUID | None
    environment = "development"
    try:
        claims = sandbox_claims(request)
    except HTTPException:
        require_service(request)
        raw = request.headers.get("x-messer-project-id")
        project_id = uuid.UUID(raw) if raw else None
    else:
        check_scope(claims, org_id)
        project_id = claims.project_id
        environment = claims.environment
    ctx = gateway.context_from_headers(request, org_id, project_id, environment)
    return await gateway.handle(request, ctx)


@router.post("/orgs/{org_id}/proxies/anthropic/v1/messages/count_tokens")
async def anthropic_count_tokens(org_id: uuid.UUID, request: Request) -> JSONResponse:
    """Approximate token count (4 chars per token); used only for context-window bookkeeping."""
    try:
        check_scope(sandbox_claims(request), org_id)
    except HTTPException:
        require_service(request)
    body = await request.json()
    raw = json.dumps(
        {"system": body.get("system"), "messages": body.get("messages"), "tools": body.get("tools")}, default=str
    )
    return JSONResponse({"input_tokens": max(1, len(raw) // 4)})


# ------------------------------------------------------------------------------------------ tool proxy


class _ToolProxyError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


async def _tool_send_email(claims: SandboxClaims, params: dict[str, Any]) -> dict[str, Any]:
    to = str(params.get("to") or "").strip()
    subject = str(params.get("subject") or "").strip()
    body = str(params.get("body") or "")
    if "@" not in to or not subject:
        raise _ToolProxyError(422, "Faltan el destinatario o el asunto del email")
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in body.split("\n\n") if p.strip())
    message_id = await get_email_adapter().send(
        OutgoingEmail(
            to=to,
            subject=subject,
            html=f"<!doctype html><html><body>{paragraphs}</body></html>",
            text=body,
            tags=["agent_email"],
            headers={"X-Messer-Org": str(claims.org_id), "X-Messer-Project": str(claims.project_id)},
        )
    )
    return {"sent": True, "to": to, "message_id": message_id}


TOOL_HANDLERS = {"send_email": _tool_send_email}


@router.post("/orgs/{org_id}/proxies/v1/tools/{tool_name}")
async def tool_proxy(
    org_id: uuid.UUID, tool_name: str, request: Request, claims: SandboxClaims = Depends(sandbox_claims)
) -> JSONResponse:
    check_scope(claims, org_id)
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return JSONResponse(
            {"error": {"type": "not_found", "message": f"Herramienta desconocida: {tool_name}"}}, status_code=404
        )
    params = await request.json()
    try:
        output = await handler(claims, params if isinstance(params, dict) else {})
    except _ToolProxyError as exc:
        return JSONResponse({"error": {"type": "invalid_request", "message": exc.message}}, status_code=exc.status)
    return JSONResponse({"tool": tool_name, "provider": "messer", "version": "1", "output": output})


# ------------------------------------------------------------------------------------------- knowledge


async def _kb_for(claims: SandboxClaims, org_id: uuid.UUID, kb_id: uuid.UUID) -> KnowledgeBase:
    check_scope(claims, org_id)
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
    if kb is None or kb.org_id != org_id:
        raise HTTPException(status_code=404, detail="knowledge base not found")
    if kb.project_id is not None and kb.project_id != claims.project_id:
        raise HTTPException(status_code=403, detail="knowledge base belongs to another project")
    return kb


class SearchBody(BaseModel):
    query: str
    mode: str = "hybrid"
    k: int = Field(default=8, ge=1, le=50)


@router.post("/orgs/{org_id}/knowledge-bases/{kb_id}/search")
async def kb_search(
    org_id: uuid.UUID, kb_id: uuid.UUID, body: SearchBody, claims: SandboxClaims = Depends(sandbox_claims)
) -> JSONResponse:
    from messer_common.knowledge import search as kb_search_mod
    from messer_common.knowledge.errors import KnowledgeError

    await _kb_for(claims, org_id, kb_id)
    mode = body.mode if body.mode in ("vector", "keyword", "hybrid") else "hybrid"
    try:
        async with system_session() as s:
            hits = await kb_search_mod.search(s, kb_id=kb_id, query=body.query, mode=mode, k=body.k)  # type: ignore[arg-type]
    except KnowledgeError as exc:
        return JSONResponse({"error": {"type": exc.code, "message": exc.message}}, status_code=exc.status)
    return JSONResponse({"hits": [_jsonable(h) for h in hits]})


class QueryBody(BaseModel):
    sql: str
    params: list[Any] = Field(default_factory=list)


@router.post("/orgs/{org_id}/knowledge-bases/{kb_id}/query")
async def kb_query(
    org_id: uuid.UUID, kb_id: uuid.UUID, body: QueryBody, claims: SandboxClaims = Depends(sandbox_claims)
) -> JSONResponse:
    from messer_common.knowledge import sql as kb_sql
    from messer_common.knowledge.errors import KnowledgeError

    await _kb_for(claims, org_id, kb_id)
    try:
        result = await kb_sql.run_readonly(kb_id=kb_id, sql=body.sql, params=body.params, role="agent")
    except KnowledgeError as exc:
        return JSONResponse({"error": {"type": exc.code, "message": exc.message}}, status_code=exc.status)
    return JSONResponse(_jsonable(result))


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return json.loads(json.dumps(value, default=str))
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return json.loads(json.dumps(asdict(value), default=str))
    return json.loads(json.dumps(value, default=str))


# ------------------------------------------------------------------------------------------ connectors


class ActionBody(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/orgs/{org_id}/connections/{connection_id}/actions/{action}")
async def connector_action(
    org_id: uuid.UUID,
    connection_id: uuid.UUID,
    action: str,
    body: ActionBody,
    claims: SandboxClaims = Depends(sandbox_claims),
) -> JSONResponse:
    from messer_connectors import credentials, registry
    from messer_connectors.base import ConnectorError

    check_scope(claims, org_id)
    async with system_session() as s:
        conn = await s.get(Connection, connection_id)
        if conn is None or conn.org_id != org_id:
            raise HTTPException(status_code=404, detail="connection not found")
        try:
            ctx = await credentials.load_context(s, connection_id)
        except ConnectorError as exc:
            return JSONResponse({"error": {"type": exc.code, "message": str(exc)}}, status_code=exc.status_code)
    try:
        adapter = registry.get_adapter(conn.connector_key)
        result = await adapter.run_action(ctx, action, body.args)
    except ConnectorError as exc:
        log.info("connector.action_failed", connector=conn.connector_key, action=action, code=exc.code)
        return JSONResponse({"error": {"type": exc.code, "message": str(exc)}}, status_code=exc.status_code)
    return JSONResponse({"result": _jsonable(result), "demo": conn.demo})


# ------------------------------------------------------------------------------------- control plane


@router.post("/runs/stream", dependencies=[Depends(require_service)])
async def run_stream(req: RunRequest, request: Request) -> StreamingResponse:
    executor = _executor(request)

    async def events() -> AsyncIterator[str]:
        async for event in executor.execute(req):
            yield _sse(event)

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@router.post("/runs", dependencies=[Depends(require_service)])
async def run_sync(req: RunRequest, request: Request) -> JSONResponse:
    executor = _executor(request)
    summary: dict[str, Any] = {}
    output: Any = None
    errors: list[Any] = []
    async for event in executor.execute(req):
        kind = event.get("type")
        if kind == "OUTPUT" and event.get("parent_call_id") is None:
            output = event.get("output")
        elif kind == "RUN_ERROR":
            errors.append(event.get("error"))
        elif kind == "RUN_FINISHED":
            summary = event
    return JSONResponse({**summary, "output": output, "errors": errors})


async def _member_sandbox(request: Request, project_id: uuid.UUID, name: str, ref: str) -> tuple[Any, Workforce]:
    async with system_session() as s:
        member = (
            await s.execute(select(Workforce).where(Workforce.project_id == project_id, Workforce.name == name))
        ).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="workforce member not found")
    commit, project_dir = await ensure_checkout(project_id, ref)
    pool = _pool(request)
    sbx = await pool.get(
        org_id=member.org_id,
        project_id=project_id,
        commit=commit,
        project_dir=project_dir,
        secrets=await _project_secrets(project_id),
        environment="development",
    )
    return sbx, member


class EvalBody(BaseModel):
    ref: str = "HEAD"
    tags: list[str] | None = None


@router.post("/projects/{project_id}/workforce/{name}/evals", dependencies=[Depends(require_service)])
async def member_evals(project_id: uuid.UUID, name: str, body: EvalBody, request: Request) -> JSONResponse:
    sbx, _ = await _member_sandbox(request, project_id, name, body.ref)
    async with _pool(request).lease(sbx), sbx.client(timeout=900) as c:
        res = await c.post(f"/members/{name}/evals", json={"tags": body.tags})
    if res.status_code != 200:
        return JSONResponse({"error": {"type": "sandbox", "message": res.text[:2000]}}, status_code=502)
    return JSONResponse({**res.json(), "commit": sbx.commit})


@router.get("/projects/{project_id}/workforce/{name}/flow", dependencies=[Depends(require_service)])
async def member_flow(project_id: uuid.UUID, name: str, request: Request, ref: str = "HEAD") -> JSONResponse:
    sbx, _ = await _member_sandbox(request, project_id, name, ref)
    async with _pool(request).lease(sbx), sbx.client(timeout=60) as c:
        res = await c.post(f"/members/{name}/flow")
    if res.status_code != 200:
        return JSONResponse({"error": {"type": "sandbox", "message": res.text[:2000]}}, status_code=502)
    return JSONResponse(res.json())


@router.get("/projects/{project_id}/workforce/{name}/schema", dependencies=[Depends(require_service)])
async def member_schema(project_id: uuid.UUID, name: str, request: Request, ref: str = "HEAD") -> JSONResponse:
    sbx, _ = await _member_sandbox(request, project_id, name, ref)
    async with _pool(request).lease(sbx), sbx.client(timeout=60) as c:
        res = await c.get(f"/members/{name}/schema")
    if res.status_code != 200:
        return JSONResponse({"error": {"type": "sandbox", "message": res.text[:2000]}}, status_code=502)
    return JSONResponse(res.json())


@router.get("/sandboxes", dependencies=[Depends(require_service)])
async def sandboxes(request: Request) -> JSONResponse:
    return JSONResponse({"sandboxes": _pool(request).stats()})


@router.post("/caches/invalidate", dependencies=[Depends(require_service)])
async def invalidate() -> JSONResponse:
    """Called by the control plane after a model-policy, residency or price change."""
    gateway.invalidate_caches()
    return JSONResponse({"ok": True})
