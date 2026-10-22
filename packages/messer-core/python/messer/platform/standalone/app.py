# Added by Messer: standalone platform for exported projects (see NOTICE).
"""HTTP app of the standalone platform: the subset of the Messer platform API that the engine calls
(``MESSER_API_HOST``), implemented locally for an exported project.

=========================================================  =====================================================
``GET|PATCH /orgs/{org}/projects/{p}/runs/{run_id}``       run traces (JSONL files) — conversation memory
``POST /orgs/{org}/proxies/anthropic/v1/messages``         Anthropic with ``ANTHROPIC_API_KEY``, else offline echo
``POST /orgs/{org}/proxies/v1/tools/send_email``           SMTP (``SMTP_HOST``) or ``state/outbox.jsonl``
``POST /orgs/{org}/knowledge-bases/{kb}/search``           BM25 keyword search over the exported chunks
``POST /orgs/{org}/knowledge-bases/{kb}/query``            read-only SQL over the exported tables (SQLite)
``POST /orgs/{org}/connections/{id}/actions/{action}``     not available in an exported project (clear error)
``POST /files``, ``GET /files/{key}``                      files on local disk
=========================================================  =====================================================

Every endpoint except ``/healthcheck`` and file downloads (unguessable keys) requires the bearer token
``MESSER_STANDALONE_TOKEN`` (members send it as ``MESSER_API_KEY``).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import mimetypes
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .config import StandaloneConfig
from .knowledge import KnowledgeError, KnowledgeStore
from .models import forward_headers, offline_reply, offline_stream
from .store import FILE_MAX_BYTES, FileStore, Mailer, TraceStore

logger = structlog.get_logger("messer.platform.standalone")

NOT_IN_EXPORT = (
    "Las acciones de conectores no están disponibles en el proyecto exportado: las credenciales de las conexiones "
    "se quedan en Messer. Sustituye la herramienta por código propio o vuelve a ejecutar el proyecto en Messer. "
    "(Connector actions are not available in the exported project.)"
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"type": code, "message": message}}, status_code=status)


class _Denied(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def create_app(
    config: StandaloneConfig | None = None, *, anthropic_transport: httpx.AsyncBaseTransport | None = None
) -> FastAPI:
    cfg = config or StandaloneConfig.from_env()
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    knowledge = KnowledgeStore(cfg.data_dir, cfg.state_dir, row_limit=cfg.sql_row_limit, timeout_ms=cfg.sql_timeout_ms)
    traces = TraceStore(cfg.state_dir)
    files = FileStore(cfg.state_dir, cfg.public_url)
    mailer = Mailer(cfg)

    app = FastAPI(title="Messer standalone platform", version="1.0.0", docs_url=None, redoc_url=None)
    app.state.config = cfg

    @app.exception_handler(_Denied)
    async def _denied(_: Request, exc: _Denied) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(KnowledgeError)
    async def _knowledge(_: Request, exc: KnowledgeError) -> JSONResponse:
        return _error(exc.status, exc.code, exc.message)

    def authorize(request: Request) -> None:
        if not cfg.token:
            return
        raw = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
        token = raw.removeprefix("Bearer ").strip()
        if not token or not hmac.compare_digest(token.encode(), cfg.token.encode()):
            raise _Denied(401, "unauthorized", "Token no válido (MESSER_API_KEY / MESSER_STANDALONE_TOKEN)")

    def scope(org_id: str, project_id: str | None = None) -> None:
        if cfg.org_id and org_id != cfg.org_id:
            raise _Denied(404, "not_found", "Organización desconocida en esta exportación")
        if project_id is not None and cfg.project_id and project_id != cfg.project_id:
            raise _Denied(404, "not_found", "Proyecto desconocido en esta exportación")

    auth = [Depends(authorize)]

    async def body_json(request: Request) -> dict[str, Any]:
        try:
            data = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _Denied(400, "invalid_json", "Cuerpo JSON no válido") from exc
        if not isinstance(data, dict):
            raise _Denied(400, "invalid_json", "Se esperaba un objeto JSON")
        return data

    # ------------------------------------------------------------------------------------- info
    @app.get("/healthcheck")
    async def healthcheck() -> dict[str, Any]:
        return {"ok": True}

    @app.get("/", dependencies=auth)
    async def info() -> dict[str, Any]:
        manifest: dict[str, Any] = {}
        if cfg.manifest_path and cfg.manifest_path.is_file():
            manifest = json.loads(cfg.manifest_path.read_text(encoding="utf-8"))
        return {
            "service": "messer-standalone-platform",
            "project": manifest.get("project"),
            "members": manifest.get("members", []),
            "knowledge_bases": knowledge.list(),
            "model": cfg.model_mode,
            "email": "smtp" if cfg.smtp_host else "outbox",
        }

    # ------------------------------------------------------------------------------------- tracing
    @app.get("/orgs/{org_id}/projects/{project_id}/runs/{run_id}", dependencies=auth)
    async def get_trace(org_id: str, project_id: str, run_id: str) -> dict[str, Any]:
        scope(org_id, project_id)
        return {"trace": await asyncio.to_thread(traces.get, run_id)}

    @app.patch("/orgs/{org_id}/projects/{project_id}/runs/{run_id}", dependencies=auth)
    async def put_trace(org_id: str, project_id: str, run_id: str, request: Request) -> Response:
        scope(org_id, project_id)
        if not traces.valid_run_id(run_id):
            raise _Denied(400, "invalid_run_id", "Identificador de ejecución no válido")
        body = await body_json(request)
        await asyncio.to_thread(
            traces.put, run_id, project_id=project_id, parent_id=body.get("parent_id"), trace=body.get("trace")
        )
        return Response(status_code=204)

    @app.get("/traces", dependencies=auth)
    async def recent_traces(limit: int = 50) -> dict[str, Any]:
        return {"runs": await asyncio.to_thread(traces.recent, max(1, min(limit, 500)))}

    @app.get("/traces/{run_id}", dependencies=auth)
    async def trace_detail(run_id: str) -> dict[str, Any]:
        trace = await asyncio.to_thread(traces.get, run_id)
        if trace is None:
            raise _Denied(404, "not_found", "Ejecución no encontrada")
        return {"run_id": run_id, "trace": trace}

    # -------------------------------------------------------------------------------- model proxy
    @app.post("/orgs/{org_id}/proxies/anthropic/v1/messages", dependencies=auth)
    async def anthropic_messages(org_id: str, request: Request) -> Response:
        scope(org_id)
        raw = await request.body()
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return _error(400, "invalid_request_error", "Cuerpo JSON no válido")
        stream = bool(body.get("stream"))
        if not cfg.anthropic_api_key:
            if stream:
                return StreamingResponse(offline_stream(body), media_type="text/event-stream")
            return JSONResponse(offline_reply(body))
        client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=600.0), transport=anthropic_transport)
        upstream = client.build_request(
            "POST",
            f"{cfg.anthropic_base_url}/v1/messages",
            headers=forward_headers(dict(request.headers), cfg.anthropic_api_key),
            content=raw,
        )
        try:
            res = await client.send(upstream, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            logger.warning("standalone.anthropic_unreachable", error=str(exc))
            return _error(502, "api_error", "No se ha podido contactar con Anthropic")
        media_type = res.headers.get("content-type", "application/json")
        if stream and res.status_code == 200:

            async def relay() -> AsyncIterator[bytes]:
                try:
                    async for chunk in res.aiter_bytes():
                        yield chunk
                finally:
                    await res.aclose()
                    await client.aclose()

            return StreamingResponse(relay(), status_code=res.status_code, media_type=media_type)
        try:
            data = await res.aread()
        finally:
            await res.aclose()
            await client.aclose()
        return Response(content=data, status_code=res.status_code, media_type=media_type)

    @app.post("/orgs/{org_id}/proxies/anthropic/v1/messages/count_tokens", dependencies=auth)
    async def count_tokens(org_id: str, request: Request) -> dict[str, int]:
        scope(org_id)
        body = await body_json(request)
        raw = json.dumps({k: body.get(k) for k in ("system", "messages", "tools")}, default=str)
        return {"input_tokens": max(1, len(raw) // 4)}

    # ---------------------------------------------------------------------------------- tool proxy
    @app.post("/orgs/{org_id}/proxies/v1/tools/{tool_name}", dependencies=auth)
    async def tool_proxy(org_id: str, tool_name: str, request: Request) -> JSONResponse:
        scope(org_id)
        if tool_name != "send_email":
            return _error(404, "not_found", f"Herramienta desconocida: {tool_name}")
        params = await body_json(request)
        to = str(params.get("to") or "").strip()
        subject = str(params.get("subject") or "").strip()
        if "@" not in to or not subject:
            return _error(422, "invalid_request", "Faltan el destinatario o el asunto del email")
        try:
            output = await asyncio.to_thread(mailer.send, to=to, subject=subject, body=str(params.get("body") or ""))
        except Exception as exc:  # smtplib raises OSError subclasses and SMTPException
            logger.warning("standalone.smtp_failed", error=str(exc))
            return _error(502, "smtp_error", f"No se ha podido enviar el email: {exc}")
        return JSONResponse({"tool": tool_name, "provider": "messer-standalone", "version": "1", "output": output})

    # ----------------------------------------------------------------------------------- knowledge
    @app.get("/orgs/{org_id}/knowledge-bases", dependencies=auth)
    async def list_kbs(org_id: str) -> dict[str, Any]:
        scope(org_id)
        return {"knowledge_bases": knowledge.list()}

    @app.post("/orgs/{org_id}/knowledge-bases/{kb_id}/search", dependencies=auth)
    async def kb_search(org_id: str, kb_id: str, request: Request) -> dict[str, Any]:
        scope(org_id)
        body = await body_json(request)
        query = str(body.get("query") or "")
        k = int(body.get("k") or 8)
        hits = await asyncio.to_thread(knowledge.search, kb_id, query, k)
        return {"hits": hits, "mode": "keyword"}

    @app.post("/orgs/{org_id}/knowledge-bases/{kb_id}/query", dependencies=auth)
    async def kb_query(org_id: str, kb_id: str, request: Request) -> dict[str, Any]:
        scope(org_id)
        body = await body_json(request)
        params = body.get("params") or []
        if not isinstance(params, list):
            raise _Denied(400, "invalid_params", "params debe ser una lista")
        return await asyncio.to_thread(knowledge.query, kb_id, str(body.get("sql") or ""), params)

    # ---------------------------------------------------------------------------------- connectors
    @app.post("/orgs/{org_id}/connections/{connection_id}/actions/{action}", dependencies=auth)
    async def connector_action(org_id: str, connection_id: str, action: str) -> JSONResponse:
        scope(org_id)
        logger.info("standalone.connector_action_unavailable", connection_id=connection_id, action=action)
        return _error(422, "not_available_in_export", NOT_IN_EXPORT)

    @app.get("/orgs/{org_id}/connections/{connection_id}/credentials", dependencies=auth)
    async def connector_credentials(org_id: str, connection_id: str) -> JSONResponse:
        scope(org_id)
        logger.info("standalone.connector_credentials_unavailable", connection_id=connection_id)
        return _error(422, "not_available_in_export", NOT_IN_EXPORT)

    # --------------------------------------------------------------------------------------- files
    @app.post("/files", dependencies=auth)
    async def upload(request: Request) -> JSONResponse:
        try:
            form = await request.form(max_files=1)
        except AssertionError:  # python-multipart missing
            return _error(500, "multipart_unavailable", "Instala python-multipart para subir archivos")
        upload_file = form.get("file")
        if upload_file is None or isinstance(upload_file, str):
            return _error(400, "invalid_request", "Falta el archivo (campo «file»)")
        data = await upload_file.read(FILE_MAX_BYTES + 1)
        if len(data) > FILE_MAX_BYTES:
            return _error(413, "file_too_large", "El archivo supera 50 MB")
        stored = await asyncio.to_thread(files.put, upload_file.filename or "file", data, upload_file.content_type)
        return JSONResponse(stored)

    @app.get("/files/{key:path}")
    async def download(key: str) -> Response:
        path: Path | None = files.path(key)
        if path is None:
            return _error(404, "not_found", "Archivo no encontrado")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=mime)

    # Registered last: it must not shadow the Anthropic and tool proxies above.
    @app.post("/orgs/{org_id}/proxies/{proxy}/{rest:path}", dependencies=auth)
    async def other_proxies(org_id: str, proxy: str, rest: str) -> JSONResponse:
        scope(org_id)
        logger.info("standalone.proxy_unavailable", proxy=proxy, path=rest)
        return _error(
            422,
            "not_available_in_export",
            f"El proxy «{proxy}» no está disponible en el proyecto exportado: usa modelos de Anthropic o define la "
            "clave del proveedor (p. ej. OPENAI_API_KEY) en el servicio del agente.",
        )

    return app
