"""Connection credentials: decrypt, build the :class:`ConnectionContext`, refresh OAuth tokens.

``load_context(session, connection_id)`` reads the row through the caller's session (RLS applies for user
requests). Token refreshes are written back in their own owner transaction with a row lock, so a rotated
refresh token is never lost when the caller's transaction rolls back, and two workers never refresh the
same connection at once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import system_session
from messer_common.db.models import Connection
from messer_common.logging import get_logger
from messer_common.security import DecryptionError, decrypt_json, encrypt_json

from . import oauth
from .base import ConnectionContext, ConnectorAuthError, ConnectorError
from .registry import get_adapter

log = get_logger("messer.connectors.credentials")


class ConnectionNotFound(ConnectorError):
    code = "connection_not_found"
    status_code = 404


def decrypt_credentials(connection: Connection) -> dict[str, Any]:
    try:
        return decrypt_json(connection.credentials)
    except DecryptionError as exc:
        raise ConnectorAuthError(
            "No se pueden descifrar las credenciales de la conexión (¿ha cambiado MESSER_SECRETS_KEY?)",
            code="credentials_undecryptable",
        ) from exc


def context_for(connection: Connection, credentials: dict[str, Any] | None = None) -> ConnectionContext:
    creds = credentials if credentials is not None else decrypt_credentials(connection)
    ctx = ConnectionContext(
        connection_id=connection.id,
        org_id=connection.org_id,
        credentials=creds,
        config=dict(connection.config or {}),
        demo=bool(connection.demo),
        connector_key=connection.connector_key,
        agent_id=connection.agent_id,
    )
    ctx.on_credentials_update = _persist_callback(connection.id, connection.org_id, ctx)
    return ctx


def _persist_callback(connection_id: uuid.UUID, org_id: uuid.UUID, ctx: ConnectionContext):  # type: ignore[no-untyped-def]
    async def persist(new_credentials: dict[str, Any]) -> None:
        ctx.credentials = new_credentials
        await save_credentials(connection_id, org_id, new_credentials)

    return persist


async def save_credentials(connection_id: uuid.UUID, org_id: uuid.UUID, credentials: dict[str, Any]) -> None:
    async with system_session() as s:
        row = (
            await s.execute(
                select(Connection).where(Connection.id == connection_id, Connection.org_id == org_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return
        row.credentials = encrypt_json(credentials)
        if row.status == "error":
            row.status = "active"
            row.error = None


async def load_context(session: AsyncSession, connection_id: uuid.UUID) -> ConnectionContext:
    """Contracts §4: decrypted context for a connection, with OAuth tokens refreshed when close to expiry."""
    connection = await session.get(Connection, connection_id)
    if connection is None:
        raise ConnectionNotFound("Conexión no encontrada")
    if connection.status == "revoked":
        raise ConnectorAuthError("La conexión está desconectada", code="connection_revoked")
    ctx = context_for(connection)
    if connection.demo:
        return ctx
    adapter = get_adapter(connection.connector_key)
    if adapter.spec.auth_type == "oauth2" and oauth.needs_refresh(ctx.credentials):
        ctx.credentials = await refresh_connection(connection.id, connection.org_id)
    return ctx


async def refresh_connection(connection_id: uuid.UUID, org_id: uuid.UUID, *, force: bool = False) -> dict[str, Any]:
    """Refresh the OAuth token under a row lock; returns the current (possibly refreshed) credentials."""
    try:
        async with system_session() as s:
            row = (
                await s.execute(
                    select(Connection)
                    .where(Connection.id == connection_id, Connection.org_id == org_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if row is None:
                raise ConnectionNotFound("Conexión no encontrada")
            credentials = decrypt_credentials(row)
            if not force and not oauth.needs_refresh(credentials):
                return credentials  # another worker refreshed it while we waited for the lock
            spec = get_adapter(row.connector_key).spec
            fresh = await oauth.refresh(spec, credentials)
            row.credentials = encrypt_json(fresh)
            row.status = "active"
            row.error = None
            row.updated_at = datetime.now(UTC)
            log.info("connection.refreshed", connection_id=str(connection_id), connector=row.connector_key)
            return fresh
    except ConnectorAuthError as exc:
        log.warning("connection.refresh_failed", connection_id=str(connection_id), error=exc.message)
        await mark_error(connection_id, org_id, exc.message)
        raise


async def mark_error(connection_id: uuid.UUID, org_id: uuid.UUID, message: str) -> None:
    async with system_session() as s:
        row = (
            await s.execute(select(Connection).where(Connection.id == connection_id, Connection.org_id == org_id))
        ).scalar_one_or_none()
        if row is not None and row.status != "revoked":
            row.status = "error"
            row.error = message[:2000]
