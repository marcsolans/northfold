"""Connector events → workflow triggers (spec 7.5 "Connector event").

Push events (``webhooks.received``, ``<connector>.sync_completed``) are emitted when they happen. Provider
events (``gmail.new_email``, ``hubspot.new_contact``…) are polled by the scheduler, but only for connections
referenced by an enabled ``connector_event`` trigger; one poll per (connection, event) serves every trigger.
Cursors live in ``connections.config["_event_cursors"]`` (hidden from the API). The first poll establishes a
baseline (no backfill). Every event goes through ``messer_common.triggers.emit`` (idempotent per event id).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import system_session
from messer_common.db.models import Connection, Trigger
from messer_common.logging import get_logger
from messer_connectors import registry
from messer_connectors.base import PUSH_EVENTS, ConnectorError
from messer_connectors.credentials import load_context
from messer_connectors.sql import SqlError

log = get_logger("messer.connector_events")

EVENT_CURSORS_KEY = "_event_cursors"
POLL_TIMEOUT_S = 60
MAX_CONNECTIONS_PER_TICK = 500


def event_name(connector_key: str, event: str) -> str:
    return f"{connector_key}.{event}"


async def emit_event(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    connector_key: str,
    event: str,
    connection_id: uuid.UUID,
    event_id: str,
    data: dict[str, Any],
    occurred_at: str | None = None,
) -> int:
    """Fire the triggers listening to ``<connector_key>.<event>`` on this connection (owner session)."""
    from messer_common import triggers

    payload: dict[str, Any] = {
        "connector": connector_key,
        "connection_id": str(connection_id),
        "event": event,
        "event_id": event_id,
        "occurred_at": occurred_at,
        "data": data,
    }
    for key in ("from", "subject", "snippet", "email"):
        if isinstance(data.get(key), str):
            payload[key] = data[key]
    return await triggers.emit(
        session,
        org_id=org_id,
        event=event_name(connector_key, event),
        connection_id=connection_id,
        event_id=event_id,
        payload=payload,
    )


async def _wanted() -> dict[uuid.UUID, tuple[uuid.UUID, set[str]]]:
    async with system_session() as s:
        rows = (
            await s.execute(
                select(Trigger.org_id, Trigger.config).where(
                    Trigger.kind == "connector_event", Trigger.enabled.is_(True)
                )
            )
        ).all()
    wanted: dict[uuid.UUID, tuple[uuid.UUID, set[str]]] = {}
    for org_id, config in rows:
        cfg = config or {}
        try:
            connection_id = uuid.UUID(str(cfg.get("connection_id")))
        except ValueError:
            continue
        entry = wanted.setdefault(connection_id, (org_id, set()))
        if entry[0] == org_id:
            entry[1].add(str(cfg.get("event") or ""))
    return wanted


async def poll_connector_events() -> dict[str, int]:
    """Scheduler task: poll provider events for connections used by enabled triggers and emit them."""
    stats = {"connections": 0, "events": 0, "fired": 0, "errors": 0}
    wanted = await _wanted()
    for connection_id, (org_id, names) in list(wanted.items())[:MAX_CONNECTIONS_PER_TICK]:
        try:
            await poll_connection(connection_id, org_id, names, stats)
        except Exception as exc:  # one broken connection must not stop the others
            stats["errors"] += 1
            log.exception("connector_events.poll_crashed", connection_id=str(connection_id), error=str(exc))
    return stats


async def poll_connection(
    connection_id: uuid.UUID, org_id: uuid.UUID, names: set[str], stats: dict[str, int] | None = None
) -> list[dict[str, Any]]:
    """Poll the events of one connection that ``names`` (trigger event names or ``*``) ask for."""
    stats = stats if stats is not None else {"connections": 0, "events": 0, "fired": 0, "errors": 0}
    async with system_session() as s:
        conn = (
            await s.execute(select(Connection).where(Connection.id == connection_id, Connection.org_id == org_id))
        ).scalar_one_or_none()
        if conn is None or conn.status in ("revoked", "error"):
            return []
        try:
            adapter = registry.get_adapter(conn.connector_key)
        except ConnectorError:
            return []
        key = conn.connector_key
        polled = [
            e
            for e in adapter.spec.capabilities.events
            if e not in PUSH_EVENTS and ("*" in names or event_name(key, e) in names)
        ]
        if not polled:
            return []
        try:
            ctx = await load_context(s, conn.id)
        except ConnectorError as exc:
            stats["errors"] += 1
            log.warning("connector_events.credentials_failed", connection_id=str(connection_id), error=exc.message)
            return []
        cursors = dict((conn.config or {}).get(EVENT_CURSORS_KEY) or {})
    stats["connections"] += 1
    emitted: list[dict[str, Any]] = []
    for event in polled:
        try:
            events, next_cursor = await asyncio.wait_for(
                adapter.poll_events(ctx, event, cursors.get(event)), timeout=POLL_TIMEOUT_S
            )
        except (ConnectorError, SqlError) as exc:
            stats["errors"] += 1
            log.warning("connector_events.poll_failed", connection_id=str(connection_id), event_name=event,
                        error=exc.message)  # fmt: skip
            continue
        except TimeoutError:
            stats["errors"] += 1
            log.warning("connector_events.poll_timeout", connection_id=str(connection_id), event_name=event)
            continue
        async with system_session() as s:
            for item in events:
                stats["events"] += 1
                stats["fired"] += await emit_event(
                    s,
                    org_id=org_id,
                    connector_key=key,
                    event=event,
                    connection_id=connection_id,
                    event_id=str(item.get("id")),
                    data=dict(item.get("data") or {}),
                    occurred_at=item.get("occurred_at"),
                )
                emitted.append(item)
            row = (
                await s.execute(select(Connection).where(Connection.id == connection_id).with_for_update())
            ).scalar_one_or_none()
            if row is not None and next_cursor != cursors.get(event):
                config = dict(row.config or {})
                config[EVENT_CURSORS_KEY] = {**dict(config.get(EVENT_CURSORS_KEY) or {}), event: next_cursor}
                row.config = config
        cursors[event] = next_cursor
    return emitted
