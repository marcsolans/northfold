"""/api/v1/connections — connections CRUD, test, OAuth, actions, resources, schema, webhooks and the
engine-compatible credentials endpoint (``/api/v1/orgs/{org_id}/connections/{id}/credentials``)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, system_session
from messer_common.db.models import ApiKey, Connection
from messer_common.db.models.connectors import ConnectorEvent
from messer_common.events import publish
from messer_common.logging import get_logger
from messer_common.security import (
    TokenError,
    constant_time_equals,
    decrypt_json,
    encrypt_json,
    hash_token,
    random_token,
    verify_signed_payload,
)
from messer_common.settings import get_settings
from messer_connectors.adapters.webhooks import event_out, inbound_url, verify_request
from messer_connectors.base import ConnectorAuthError, ConnectorError
from messer_connectors.credentials import decrypt_credentials, load_context

from ..deps import client_ip, get_db, get_org_principal, require_role
from ..errors import ApiError, Forbidden, NotFound, Unauthorized
from ..ratelimit import rate_limit
from ..services import connections as svc
from ..services import connector_events
from ..services.connections import record_audit as svc_audit

log = get_logger("messer.api.connections")

router = APIRouter(tags=["connections"])

MAX_WEBHOOK_BYTES = 1024 * 1024
DROP_HEADERS = {"authorization", "cookie", "proxy-authorization", "x-messer-token", "x-forwarded-for"}


class ConnectionCreateIn(BaseModel):
    connector_key: str = Field(min_length=1, max_length=60)
    name: str | None = Field(default=None, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)
    agent_id: uuid.UUID | None = None
    demo: bool = False


class ConnectionUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class OAuthStartIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    return_to: str | None = Field(default=None, max_length=500)
    connection_id: uuid.UUID | None = None


class ActionIn(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


# ----------------------------------------------------------------------------- OAuth


@router.post("/connections/oauth/{key}/start")
async def oauth_start(
    key: str,
    body: OAuthStartIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await svc.oauth_start(
        db, principal, key, name=body.name, return_to=body.return_to, connection_id=body.connection_id
    )


@router.get("/connections/oauth/{key}/callback", include_in_schema=False)
async def oauth_callback(
    key: str, code: str = "", state: str = "", error: str = "", error_description: str = ""
) -> RedirectResponse:
    web = get_settings().messer_web_url.rstrip("/")
    if error or not code or not state:
        params = urlencode({"oauth_error": error or "missing_code", "connector": key})
        return RedirectResponse(f"{web}/app/connectors?{params}", status_code=302)
    try:
        conn, return_to = await svc.oauth_finish(key, code=code, state=state)
    except ApiError as exc:
        log.warning("oauth.callback_failed", connector=key, code=exc.code, message=exc.message)
        params = urlencode({"oauth_error": exc.code, "connector": key})
        return RedirectResponse(f"{web}/app/connectors?{params}", status_code=302)
    separator = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{web}{return_to}{separator}{urlencode({'connected': str(conn.id)})}", status_code=302)


# ----------------------------------------------------------------------------- CRUD


@router.get("/connections")
async def list_connections(
    connector_key: str | None = Query(default=None, max_length=60),
    principal: Principal = Depends(get_org_principal),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    q = select(Connection).where(Connection.org_id == principal.org_id, Connection.status != "revoked")
    if connector_key:
        q = q.where(Connection.connector_key == connector_key)
    rows = (await db.execute(q.order_by(Connection.created_at.desc()))).scalars().all()
    counts = await svc.sync_counts(db, [r.id for r in rows])
    return [svc.connection_out(r, sync_count=counts.get(r.id, 0)) for r in rows]


@router.post("/connections", status_code=201)
async def create_connection(
    body: ConnectionCreateIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conn = await svc.create_connection(
        db,
        principal,
        connector_key=body.connector_key,
        name=body.name,
        config=body.config,
        credentials=body.credentials,
        agent_id=body.agent_id,
        demo=body.demo,
    )
    return svc.connection_out(conn, sync_count=0)


@router.get("/connections/{connection_id}")
async def get_connection(
    connection_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    counts = await svc.sync_counts(db, [conn.id])
    return svc.connection_out(conn, sync_count=counts.get(conn.id, 0))


@router.patch("/connections/{connection_id}")
async def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdateIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    adapter = svc.adapter_for(conn.connector_key)
    changed: list[str] = []
    if body.name is not None:
        conn.name = body.name.strip()
        changed.append("name")
    if body.config is not None or body.credentials is not None:
        if adapter.spec.auth_type == "oauth2":
            raise ApiError("Las conexiones OAuth se reconfiguran volviendo a conectar la cuenta", code="oauth_required")
        current_creds = decrypt_credentials(conn) if conn.credentials else {}
        public = {k: v for k, v in (body.config or {}).items() if not k.startswith("_") and k != "demo_epoch"}
        config = {**(conn.config or {}), **public}
        credentials = {**current_creds, **{k: v for k, v in (body.credentials or {}).items() if v not in (None, "")}}
        config, credentials = svc.split_secrets(adapter.spec, config, credentials)
        with svc.connector_errors():
            adapter.validate_config(config, credentials)
            config, credentials = adapter.prepare(config, credentials)
        conn.config = config
        conn.credentials = encrypt_json(credentials) if credentials else None
        changed.extend(["config"] if body.config is not None else [])
        changed.extend(["credentials"] if body.credentials else [])
    await svc_audit(
        db,
        action="connection.updated",
        principal=principal,
        entity_type="connection",
        entity_id=conn.id,
        diff={"fields": changed},
    )
    await db.flush()
    await db.refresh(conn)
    return svc.connection_out(conn)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    conn = await svc.get_connection(db, principal, connection_id)
    await svc_audit(
        db,
        action="connection.deleted",
        principal=principal,
        entity_type="connection",
        entity_id=conn.id,
        diff={"connector": conn.connector_key, "name": conn.name},
    )
    await db.delete(conn)
    return Response(status_code=204)


@router.post("/connections/{connection_id}/test")
async def test_connection(
    connection_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    result = await svc.test_connection(db, principal, conn)
    return {"ok": result.ok, "message": result.message, "details": result.details, "status": conn.status}


# ----------------------------------------------------------------------------- actions, resources, schema


@router.get("/connections/{connection_id}/actions")
async def list_actions(
    connection_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    conn = await svc.get_connection(db, principal, connection_id)
    adapter = svc.adapter_for(conn.connector_key)
    from messer_connectors.credentials import context_for

    ctx = context_for(conn, credentials={})
    return [{**a.model_dump(), "requires_approval": a.side_effect} for a in svc.actions_for(adapter, ctx)]


@router.post("/connections/{connection_id}/actions/{action}")
async def run_action(
    connection_id: uuid.UUID,
    action: str,
    body: ActionIn,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    return await svc.run_action(db, principal, conn, action, body.args, confirm=body.confirm)


@router.get("/connections/{connection_id}/resources")
async def list_resources(
    connection_id: uuid.UUID,
    parent: str | None = Query(default=None, max_length=500),
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    conn = await svc.get_connection(db, principal, connection_id)
    adapter = svc.adapter_for(conn.connector_key)
    with svc.connector_errors():
        ctx = await load_context(db, conn.id)
        resources = await adapter.list_resources(ctx, parent)
    return [
        {"id": r.id, "name": r.name, "kind": r.kind, "has_children": r.has_children, "parent": r.parent, "meta": r.meta}
        for r in resources
    ]


@router.get("/connections/{connection_id}/schema")
async def introspect(
    connection_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    adapter = svc.adapter_for(conn.connector_key)
    if not adapter.spec.capabilities.introspection:
        raise ApiError(f"{adapter.spec.name} no admite introspección de esquema", code="not_supported")
    with svc.connector_errors():
        ctx = await load_context(db, conn.id)
        return await adapter.introspect(ctx)


# ----------------------------------------------------------------------------- webhooks


@router.get("/connections/{connection_id}/webhook")
async def webhook_info(
    connection_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    if conn.connector_key != "webhooks":
        raise ApiError("La conexión no es un webhook", code="not_webhook")
    creds = decrypt_credentials(conn)
    return {
        "url": inbound_url(conn.id),
        "secret": creds.get("secret"),
        "verification": (conn.config or {}).get("verification", "hmac"),
        "signature_header": "X-Messer-Signature",
        "timestamp_header": "X-Messer-Timestamp",
    }


@router.post("/connections/{connection_id}/webhook/rotate")
async def rotate_webhook_secret(
    connection_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    conn = await svc.get_connection(db, principal, connection_id)
    if conn.connector_key != "webhooks":
        raise ApiError("La conexión no es un webhook", code="not_webhook")
    creds = decrypt_credentials(conn)
    creds["secret"] = random_token(32)
    conn.credentials = encrypt_json(creds)
    await svc_audit(
        db, action="connection.webhook_secret_rotated", principal=principal, entity_type="connection", entity_id=conn.id
    )
    return {"url": inbound_url(conn.id), "secret": creds["secret"]}


@router.post(
    "/webhooks/connections/{connection_id}",
    status_code=202,
    dependencies=[Depends(rate_limit("connection_webhook", 600, 60))],
)
async def receive_webhook(connection_id: uuid.UUID, request: Request) -> dict[str, Any]:
    """Public inbound endpoint: verifies the HMAC signature and stores a ``received`` connector event."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise ApiError("El cuerpo supera 1 MB", code="payload_too_large", status_code=413)
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise ApiError("El cuerpo supera 1 MB", code="payload_too_large", status_code=413)
    async with system_session() as s:
        conn = (
            await s.execute(
                select(Connection).where(Connection.id == connection_id, Connection.connector_key == "webhooks")
            )
        ).scalar_one_or_none()
        if conn is None or conn.status == "revoked":
            raise NotFound("Webhook no encontrado", code="webhook_not_found")
        secret = str(decrypt_json(conn.credentials).get("secret") or "")
        try:
            verify_request(
                secret=secret,
                mode=str((conn.config or {}).get("verification", "hmac")),
                body=body,
                headers=dict(request.headers),
                query=dict(request.query_params),
            )
        except ConnectorAuthError as exc:
            raise Unauthorized(exc.message, code=exc.code) from exc
        payload: dict[str, Any]
        try:
            parsed = json.loads(body) if body else {}
            payload = parsed if isinstance(parsed, dict) else {"data": parsed}
        except ValueError:
            payload = {"raw": body.decode("utf-8", "replace")[:100_000]}
        event = ConnectorEvent(
            org_id=conn.org_id,
            connection_id=conn.id,
            event="received",
            payload=payload,
            headers={k: v[:1000] for k, v in request.headers.items() if k.lower() not in DROP_HEADERS},
            query={k: v for k, v in request.query_params.items() if k != "token"},
            source_ip=client_ip(request),
        )
        s.add(event)
        await s.flush()
        await s.refresh(event)
        event_id, org_id = event.id, conn.org_id
        await connector_events.emit_event(
            s,
            org_id=org_id,
            connector_key="webhooks",
            event="received",
            connection_id=conn.id,
            event_id=str(event_id),
            data=event_out(event)["data"],
            occurred_at=event.created_at.isoformat() if event.created_at else None,
        )
    try:
        await publish(
            "connector-events",
            {
                "type": "connector_event",
                "org_id": str(org_id),
                "connection_id": str(connection_id),
                "event": "received",
                "event_id": str(event_id),
            },
            replay=False,
        )
    except Exception as exc:  # triggers also poll; the event is stored either way
        log.warning("webhook.publish_failed", error=str(exc))
    return {"id": str(event_id), "received_at": datetime.now(UTC).isoformat()}


# ----------------------------------------------------------------------------- credentials (engine contract)


async def _authorize_credentials(request: Request, org_id: uuid.UUID) -> str:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    token = token or request.headers.get("x-messer-service-token", "")
    if not token:
        raise Unauthorized("Falta el token de servicio", code="not_authenticated")
    if constant_time_equals(token, get_settings().service_token):
        return "service"
    if token.startswith("msr_"):
        async with system_session() as s:
            key = (await s.execute(select(ApiKey).where(ApiKey.hashed_key == hash_token(token)))).scalar_one_or_none()
        if key is None or key.revoked_at is not None:
            raise Unauthorized("API key no válida o revocada", code="invalid_api_key")
        if key.org_id != org_id:
            raise Forbidden("La API key pertenece a otra organización", code="wrong_org")
        if "connections:read" not in (key.scopes or []):
            raise Forbidden("La API key necesita el permiso connections:read", code="missing_scope")
        return f"api_key:{key.id}"
    try:
        claims = verify_signed_payload(token)
    except TokenError as exc:
        raise Unauthorized("Token no válido", code="invalid_token") from exc
    if claims.get("typ") not in ("runtime", "run") or str(claims.get("org_id") or claims.get("org")) != str(org_id):
        raise Forbidden("El token no permite leer credenciales de esta organización", code="forbidden")
    return f"runtime:{claims.get('run_id') or claims.get('sub') or ''}"


@router.get("/orgs/{org_id}/connections/{connection_id}/credentials", tags=["connections", "internal"])
async def connection_credentials(org_id: uuid.UUID, connection_id: uuid.UUID, request: Request) -> dict[str, Any]:
    """Decrypted, refreshed credentials for the engine (``Integration.resolve()``) and the runtime."""
    caller = await _authorize_credentials(request, org_id)
    async with system_session() as s:
        conn = (
            await s.execute(select(Connection).where(Connection.id == connection_id, Connection.org_id == org_id))
        ).scalar_one_or_none()
        if conn is None:
            raise NotFound("Conexión no encontrada", code="connection_not_found")
        try:
            ctx = await load_context(s, conn.id)
        except ConnectorError as exc:
            raise svc.api_error(exc) from exc
        await audit.record(
            s,
            action="connection.credentials_read",
            principal=Principal(user_id=None, org_id=org_id),
            entity_type="connection",
            entity_id=conn.id,
            diff={"caller": caller.split(":")[0]},
        )
    creds = ctx.credentials
    token = creds.get("access_token") or creds.get("auth_header_value") or creds.get("secret")
    return {
        "connection_id": str(conn.id),
        "provider": conn.connector_key,
        "type": conn.connector_key,
        "token": token,
        "token_type": creds.get("token_type"),
        "expires_at": creds.get("expires_at"),
        "scopes": conn.scopes or [],
        "demo": ctx.demo,
        "agent_id": str(ctx.agent_id) if ctx.agent_id else None,
        "config": {k: v for k, v in ctx.config.items() if k != "demo_epoch" and not k.startswith("_")},
        "credentials": {k: v for k, v in creds.items() if k != "obtained_at"},
    }
