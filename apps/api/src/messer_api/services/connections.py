"""Connections: creation per auth type, demo mode, OAuth authorize/callback, tests and actions."""

from __future__ import annotations

import asyncio
import importlib
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, new_id, system_session
from messer_common.db.models import AuditLog, Connection, ConnectorAgent, Membership, Sync
from messer_common.logging import get_logger
from messer_common.security import encrypt_json
from messer_common.settings import get_settings
from messer_connectors import oauth, registry
from messer_connectors.base import (
    ActionSpec,
    ConnectionContext,
    ConnectorAdapter,
    ConnectorError,
    ConnectorSpec,
    TestResult,
)
from messer_connectors.credentials import context_for, load_context
from messer_connectors.sql import SqlError

from ..deps import ROLE_RANK
from ..errors import ApiError, Conflict, Forbidden, NotFound
from .auth import consume_one_time_token, create_one_time_token

log = get_logger("messer.connections")

OAUTH_PURPOSE = "connector_oauth"
OAUTH_TTL = timedelta(minutes=15)
ACTION_TIMEOUT_S = 120
TEST_TIMEOUT_S = 25


# ----------------------------------------------------------------------------- audit


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    principal: Principal,
    entity_type: str,
    entity_id: Any,
    diff: dict[str, Any] | None = None,
) -> None:
    """``audit.record`` for RLS sessions of non-admin roles.

    The ORM inserts audit rows with ``RETURNING created_at``; RLS applies the admin-only SELECT policy of
    ``audit_log`` to returned rows, so builders' audited mutations would fail. A Core insert has no RETURNING.
    """
    await session.execute(
        insert(AuditLog).values(
            id=new_id(),
            org_id=principal.org_id,
            actor_id=principal.user_id,
            impersonated_by=principal.impersonated_by,
            api_key_id=principal.api_key_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            diff=json.loads(json.dumps(diff or {}, default=str)),
        )
    )


# ----------------------------------------------------------------------------- errors


def api_error(exc: ConnectorError | SqlError) -> ApiError:
    if isinstance(exc, SqlError):
        return ApiError(exc.message, code=f"sql_{exc.code}", status_code=400)
    return ApiError(exc.message, code=exc.code, status_code=exc.status_code, details=exc.details)


@contextmanager
def connector_errors() -> Iterator[None]:
    """Translate connector errors into API errors (``{"error": {code, message, details}}``)."""
    try:
        yield
    except (ConnectorError, SqlError) as exc:
        raise api_error(exc) from exc


def adapter_for(key: str) -> ConnectorAdapter:
    with connector_errors():
        return registry.get_adapter(key)


# ----------------------------------------------------------------------------- helpers


def callback_url(key: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/connections/oauth/{key}/callback"


def safe_return_path(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/app/connectors"
    return value[:500]


def demo_credentials(spec: ConnectorSpec) -> dict[str, Any]:
    creds: dict[str, Any] = {"access_token": "demo", "token_type": "Bearer", "expires_at": None, "extra": {}}
    if spec.key == "salesforce":
        from messer_connectors.demo import fixture

        creds["extra"] = {"instance_url": fixture("salesforce")["org"]["instance_url"]}
    return creds


def split_secrets(
    spec: ConnectorSpec, config: dict[str, Any], credentials: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Secret fields of the connect form go to the encrypted credentials, never to the clear config."""
    config = dict(config)
    credentials = dict(credentials)
    for field in spec.config_fields:
        if field.secret and field.key in config:
            credentials[field.key] = config.pop(field.key)
    return config, credentials


async def require_connectors_feature(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Plan gate (contracts §2). The limits module belongs to the business workstream."""
    try:
        limits = importlib.import_module("messer_api.services.limits")
    except ModuleNotFoundError:
        return
    await limits.require_feature(session, org_id, "connectors")


async def get_connection(db: AsyncSession, principal: Principal, connection_id: uuid.UUID) -> Connection:
    conn = await db.get(Connection, connection_id)
    if conn is None or conn.org_id != principal.org_id:
        raise NotFound("Conexión no encontrada", code="connection_not_found")
    return conn


def actions_for(adapter: ConnectorAdapter, ctx: ConnectionContext | None) -> list[ActionSpec]:
    if ctx is not None and hasattr(adapter, "actions_for"):
        return list(adapter.actions_for(ctx))  # type: ignore[attr-defined]
    return adapter.actions()


def connection_out(conn: Connection, *, sync_count: int | None = None) -> dict[str, Any]:
    from messer_connectors.adapters.webhooks import inbound_url

    try:
        spec: ConnectorSpec | None = registry.get_adapter(conn.connector_key).spec
    except ConnectorError:
        spec = None
    config = {k: v for k, v in (conn.config or {}).items() if k != "demo_epoch" and not k.startswith("_")}
    out: dict[str, Any] = {
        "id": conn.id,
        "connector_key": conn.connector_key,
        "connector_name": spec.name if spec else conn.connector_key,
        "category": spec.category if spec else None,
        "auth_type": spec.auth_type if spec else None,
        "name": conn.name,
        "status": conn.status,
        "demo": conn.demo,
        "missing_env": oauth.missing_env(spec) if (spec and conn.demo) else [],
        "config": config,
        "scopes": conn.scopes or [],
        "agent_id": conn.agent_id,
        "error": conn.error,
        "has_credentials": bool(conn.credentials),
        "created_by": conn.created_by,
        "created_at": conn.created_at,
        "updated_at": conn.updated_at,
        "webhook_url": inbound_url(conn.id) if conn.connector_key == "webhooks" else None,
        "sync_count": sync_count,
    }
    return out


async def sync_counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(Sync.connection_id, func.count()).where(Sync.connection_id.in_(ids)).group_by(Sync.connection_id)
    )
    return {cid: int(n) for cid, n in rows.all()}


# ----------------------------------------------------------------------------- creation


async def _validate_agent(
    db: AsyncSession,
    principal: Principal,
    adapter: ConnectorAdapter,
    agent_id: uuid.UUID,
    config: dict[str, Any],
    credentials: dict[str, Any],
) -> None:
    spec = adapter.spec
    if not spec.capabilities.agent:
        raise ApiError(f"{spec.name} no se puede usar a través de un agente on-premise", code="agent_not_supported")
    agent = await db.get(ConnectorAgent, agent_id)
    if agent is None or agent.org_id != principal.org_id:
        raise NotFound("Agente on-premise no encontrado", code="agent_not_found")
    if credentials.get("connection_string"):
        raise ApiError(
            "Con un agente on-premise la cadena de conexión se configura en el propio agente y nunca sale de tu red.",
            code="agent_connection_string",
        )
    if spec.category == "database":
        source = str(config.get("agent_source") or "")
        if not source:
            raise ApiError(
                "Indica el origen de datos configurado en el agente",
                code="invalid_config",
                status_code=422,
                details={"field": "agent_source"},
            )
        sources = (agent.capabilities or {}).get("sources") or []
        if sources:
            match = next((s for s in sources if s.get("name") == source), None)
            if match is None:
                raise ApiError(
                    f"El agente no tiene un origen llamado «{source}»",
                    code="agent_source_unknown",
                    status_code=422,
                    details={"available": [s.get("name") for s in sources]},
                )
            if match.get("type") and match.get("type") != spec.key:
                raise ApiError(
                    f"El origen «{source}» es de tipo {match.get('type')}, no {spec.key}",
                    code="agent_source_type",
                    status_code=422,
                )


async def create_connection(
    db: AsyncSession,
    principal: Principal,
    *,
    connector_key: str,
    name: str | None,
    config: dict[str, Any],
    credentials: dict[str, Any],
    agent_id: uuid.UUID | None = None,
    demo: bool = False,
    test: bool = True,
) -> Connection:
    assert principal.org_id is not None
    adapter = adapter_for(connector_key)
    spec = adapter.spec
    await require_connectors_feature(db, principal.org_id)
    if spec.auth_type == "oauth2":
        if not demo:
            raise ApiError(
                f"{spec.name} se conecta con OAuth: usa «Conectar» para autorizar la cuenta",
                code="oauth_required",
                details={"start": f"/api/v1/connections/oauth/{spec.key}/start"},
            )
        return await create_demo_connection(db, principal, spec, name)
    if demo:
        raise ApiError(f"{spec.name} no tiene modo demo", code="demo_not_supported")
    if spec.auth_type == "agent" and agent_id is None:
        raise ApiError("Este conector necesita un agente on-premise", code="agent_required", status_code=422)
    config = {k: v for k, v in config.items() if not k.startswith("_") and k != "demo_epoch"}
    config, credentials = split_secrets(spec, config, credentials)
    if agent_id is not None:
        await _validate_agent(db, principal, adapter, agent_id, config, credentials)
    with connector_errors():
        adapter.validate_config(config, credentials)
        config, credentials = adapter.prepare(config, credentials)
    conn = Connection(
        org_id=principal.org_id,
        connector_key=spec.key,
        name=(name or spec.name).strip()[:200] or spec.name,
        credentials=encrypt_json(credentials) if credentials else None,
        config=config,
        scopes=[],
        status="active",
        demo=False,
        agent_id=agent_id,
        created_by=principal.user_id,
    )
    db.add(conn)
    await db.flush()
    if test:
        result = await run_test(conn, credentials)
        conn.status = "active" if result.ok else "error"
        conn.error = None if result.ok else result.message
    await record_audit(
        db,
        action="connection.created",
        principal=principal,
        entity_type="connection",
        entity_id=conn.id,
        diff={"connector": spec.key, "name": conn.name, "agent_id": agent_id, "config_keys": sorted(config)},
    )
    await db.flush()
    await db.refresh(conn)
    return conn


async def create_demo_connection(
    db: AsyncSession, principal: Principal, spec: ConnectorSpec, name: str | None
) -> Connection:
    assert principal.org_id is not None
    if not spec.capabilities.demo:
        raise ApiError(f"{spec.name} no tiene modo demo", code="demo_not_supported")
    conn = Connection(
        org_id=principal.org_id,
        connector_key=spec.key,
        name=(name or f"{spec.name} (demo)").strip()[:200],
        credentials=encrypt_json(demo_credentials(spec)),
        config={"demo_epoch": datetime.now(UTC).isoformat()},
        scopes=list(spec.oauth.scopes) if spec.oauth else [],
        status="demo",
        demo=True,
        created_by=principal.user_id,
    )
    db.add(conn)
    await db.flush()
    await record_audit(
        db,
        action="connection.created",
        principal=principal,
        entity_type="connection",
        entity_id=conn.id,
        diff={"connector": spec.key, "name": conn.name, "demo": True, "missing_env": oauth.missing_env(spec)},
    )
    await db.flush()
    await db.refresh(conn)
    return conn


# ----------------------------------------------------------------------------- OAuth


async def oauth_start(
    db: AsyncSession,
    principal: Principal,
    key: str,
    *,
    name: str | None,
    return_to: str | None,
    connection_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Authorize URL for the provider, or — when its OAuth app is not configured — a demo connection."""
    assert principal.org_id is not None
    adapter = adapter_for(key)
    spec = adapter.spec
    if spec.auth_type != "oauth2" or spec.oauth is None:
        raise ApiError(f"{spec.name} no usa OAuth", code="not_oauth")
    await require_connectors_feature(db, principal.org_id)
    if connection_id is not None:
        existing = await get_connection(db, principal, connection_id)
        if existing.connector_key != key:
            raise ApiError("La conexión es de otro conector", code="connector_mismatch")
    if oauth.oauth_app(spec) is None:
        if connection_id is not None:
            raise ApiError(
                f"Falta configurar la app OAuth de {spec.name}",
                code="oauth_not_configured",
                details={"missing_env": oauth.missing_env(spec)},
            )
        conn = await create_demo_connection(db, principal, spec, name)
        return {
            "mode": "demo",
            "connection": connection_out(conn, sync_count=0),
            "missing_env": oauth.missing_env(spec),
        }
    verifier, challenge = oauth.pkce_pair()
    async with system_session() as s:
        state = await create_one_time_token(
            s,
            purpose=OAUTH_PURPOSE,
            user_id=principal.user_id,
            ttl=OAUTH_TTL,
            payload={
                "org_id": str(principal.org_id),
                "connector": key,
                "name": (name or "").strip()[:200],
                "verifier": verifier,
                "return_to": safe_return_path(return_to),
                "connection_id": str(connection_id) if connection_id else None,
            },
        )
    with connector_errors():
        url = oauth.authorize_url(spec, redirect_uri=callback_url(key), state=state, code_challenge=challenge)
    return {"mode": "oauth", "url": url}


async def oauth_finish(key: str, *, code: str, state: str) -> tuple[Connection, str]:
    """Exchange the code, store encrypted tokens and return (connection, path to redirect to)."""
    adapter = adapter_for(key)
    spec = adapter.spec
    async with system_session() as s:
        row = await consume_one_time_token(s, purpose=OAUTH_PURPOSE, token=state)
        payload = dict(row.payload or {})
        user_id = row.user_id
    if payload.get("connector") != key or user_id is None:
        raise ApiError("Estado OAuth no válido", code="oauth_state")
    org_id = uuid.UUID(str(payload["org_id"]))
    principal = Principal(user_id=user_id, org_id=org_id)
    async with system_session() as s:
        role = (
            await s.execute(select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user_id))
        ).scalar_one_or_none()
    if role is None or ROLE_RANK.get(role, 0) < ROLE_RANK["builder"]:
        raise Forbidden("Ya no tienes permisos para conectar cuentas en esta organización", code="insufficient_role")
    with connector_errors():
        credentials = await oauth.exchange_code(
            spec, code=code, redirect_uri=callback_url(key), code_verifier=str(payload.get("verifier") or "")
        )
    scopes = [s for s in str(credentials.get("scope") or "").replace(",", " ").split() if s]
    async with system_session() as s:
        reconnect = payload.get("connection_id")
        if reconnect:
            conn = (
                await s.execute(
                    select(Connection).where(Connection.id == uuid.UUID(str(reconnect)), Connection.org_id == org_id)
                )
            ).scalar_one_or_none()
            if conn is None:
                raise NotFound("Conexión no encontrada", code="connection_not_found")
            conn.credentials = encrypt_json(credentials)
            conn.scopes = scopes
            conn.status = "active"
            conn.error = None
            conn.demo = False
            action = "connection.reconnected"
        else:
            conn = Connection(
                org_id=org_id,
                connector_key=key,
                name=str(payload.get("name") or "") or spec.name,
                credentials=encrypt_json(credentials),
                config={},
                scopes=scopes,
                status="active",
                demo=False,
                created_by=user_id,
            )
            s.add(conn)
            await s.flush()
            action = "connection.created"
        await audit.record(
            s,
            action=action,
            principal=principal,
            entity_type="connection",
            entity_id=conn.id,
            diff={"connector": key, "name": conn.name, "scopes": scopes},
        )
    return conn, str(payload.get("return_to") or "/app/connectors")


# ----------------------------------------------------------------------------- test & actions


async def run_test(conn: Connection, credentials: dict[str, Any] | None = None) -> TestResult:
    adapter = adapter_for(conn.connector_key)
    ctx = context_for(conn, credentials)
    try:
        return await asyncio.wait_for(adapter.test(ctx), timeout=TEST_TIMEOUT_S)
    except TimeoutError:
        return TestResult(ok=False, message=f"Sin respuesta en {TEST_TIMEOUT_S} s")
    except (ConnectorError, SqlError) as exc:
        return TestResult(ok=False, message=exc.message, details=getattr(exc, "details", {}) or {})


async def test_connection(db: AsyncSession, principal: Principal, conn: Connection) -> TestResult:
    with connector_errors():
        ctx = await load_context(db, conn.id)
    adapter = adapter_for(conn.connector_key)
    try:
        result = await asyncio.wait_for(adapter.test(ctx), timeout=TEST_TIMEOUT_S)
    except TimeoutError:
        result = TestResult(ok=False, message=f"Sin respuesta en {TEST_TIMEOUT_S} s")
    except (ConnectorError, SqlError) as exc:
        result = TestResult(ok=False, message=exc.message, details=getattr(exc, "details", {}) or {})
    await db.refresh(conn)
    if conn.demo:
        conn.status = "demo"
    else:
        conn.status = "active" if result.ok else "error"
        conn.error = None if result.ok else result.message[:2000]
    return result


async def run_action(
    db: AsyncSession,
    principal: Principal,
    conn: Connection,
    action: str,
    args: dict[str, Any],
    *,
    confirm: bool,
) -> dict[str, Any]:
    adapter = adapter_for(conn.connector_key)
    with connector_errors():
        ctx = await load_context(db, conn.id)
        spec = next((a for a in actions_for(adapter, ctx) if a.name == action), None)
        if spec is None:
            adapter.action(action)  # raises ActionNotFound with a clear message
            raise ApiError(f"La acción «{action}» no está disponible en esta conexión", code="action_unavailable")
    if spec.side_effect and not confirm:
        raise Conflict(
            f"«{spec.title}» tiene efectos externos: confirma la ejecución",
            code="confirmation_required",
            details={"action": action, "side_effect": True},
        )
    started = datetime.now(UTC)
    with connector_errors():
        try:
            result = await asyncio.wait_for(adapter.run_action(ctx, action, args), timeout=ACTION_TIMEOUT_S)
        except TimeoutError as exc:
            raise ApiError(
                f"La acción no ha terminado en {ACTION_TIMEOUT_S} s", code="action_timeout", status_code=504
            ) from exc
    elapsed_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    if spec.side_effect:
        await record_audit(
            db,
            action="connection.action",
            principal=principal,
            entity_type="connection",
            entity_id=conn.id,
            diff={"action": action, "connector": conn.connector_key, "arg_keys": sorted(args), "demo": conn.demo},
        )
    return {
        "action": action,
        "side_effect": spec.side_effect,
        "demo": conn.demo,
        "elapsed_ms": elapsed_ms,
        "result": result,
    }
