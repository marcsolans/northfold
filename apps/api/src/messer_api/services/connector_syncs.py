"""Connector syncs into knowledge bases: validation, scheduling and execution (worker job ``run_sync``).

Files go through ``knowledge.ingest_bytes`` and rows through ``knowledge.upsert_table`` (contracts §3), one
owner transaction per file or batch so partial progress survives a failure. Stats and errors are persisted on
the ``syncs`` row; status moves ``idle → queued → running → success | error``.
"""

from __future__ import annotations

import asyncio
import importlib
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import delete, event, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import system_session
from messer_common.db.models import Connection, ConnectorAgent, KbFile, KnowledgeBase, Sync
from messer_common.events import publish
from messer_common.logging import get_logger
from messer_common.queue import Jobs, enqueue
from messer_connectors import registry
from messer_connectors.base import ColumnDef, ConnectorError, SyncFile, SyncRequest
from messer_connectors.credentials import load_context
from messer_connectors.sql import SqlError

from ..errors import ApiError
from . import connector_events

log = get_logger("messer.syncs")

MIN_INTERVAL = timedelta(minutes=5)
STALE_RUNNING = timedelta(hours=2)
STALE_QUEUED = timedelta(hours=1)
AGENT_OFFLINE_AFTER = timedelta(seconds=90)
EVENT_RETENTION = timedelta(days=30)
RESOURCE_PREFIXES = {"folder": "folder:", "table": "table:", "object": "object:", "path": "path:"}

IngestBytes = Callable[..., Awaitable[Any]]
UpsertTable = Callable[..., Awaitable[Any]]


def _knowledge() -> Any:
    return importlib.import_module("messer_api.services.knowledge")


# Indirection so tests can isolate the knowledge workstream; the real call path is the default.
def knowledge_errors() -> tuple[type[Exception], ...]:
    """Exception types raised by the knowledge helpers for bad input (empty tuple if not installed)."""
    try:
        module = importlib.import_module("messer_common.knowledge.errors")
    except ImportError:
        return ()
    error = getattr(module, "KnowledgeError", None)
    return (error,) if isinstance(error, type) and issubclass(error, Exception) else ()


def ingest_bytes_impl() -> IngestBytes:
    return _knowledge().ingest_bytes


def upsert_table_impl() -> UpsertTable:
    return _knowledge().upsert_table


# ----------------------------------------------------------------------------- schedule


def validate_schedule(schedule: str | None) -> str | None:
    if schedule is None or not schedule.strip():
        return None
    expr = " ".join(schedule.split())
    if not croniter.is_valid(expr):
        raise ApiError(
            "Expresión cron no válida", code="invalid_schedule", status_code=422, details={"field": "schedule"}
        )
    it = croniter(expr, datetime(2026, 1, 5, tzinfo=UTC))
    first: datetime = it.get_next(datetime)
    second: datetime = it.get_next(datetime)
    if second - first < MIN_INTERVAL:
        raise ApiError(
            "La sincronización no puede ejecutarse más de una vez cada 5 minutos",
            code="schedule_too_frequent",
            status_code=422,
            details={"field": "schedule"},
        )
    return expr


def next_run(schedule: str | None, after: datetime | None = None) -> datetime | None:
    if not schedule:
        return None
    base = after or datetime.now(UTC)
    result: datetime = croniter(schedule, base).get_next(datetime)
    return result if result.tzinfo else result.replace(tzinfo=UTC)


def validate_resource(connection: Connection, resource: str) -> str:
    adapter = registry.get_adapter(connection.connector_key)
    caps = adapter.spec.capabilities
    if not caps.sync:
        raise ApiError(f"{adapter.spec.name} no admite sincronización", code="sync_not_supported")
    resource = resource.strip()
    allowed = [RESOURCE_PREFIXES.get(kind, f"{kind}:") for kind in caps.sync_resources]
    if connection.connector_key == "notion":
        allowed = ["page:", "database:"]
        if resource == "all":
            return resource
    if not any(resource.startswith(prefix) and len(resource) > len(prefix) for prefix in allowed):
        raise ApiError(
            "Recurso de sincronización no válido",
            code="invalid_resource",
            status_code=422,
            details={"field": "resource", "expected": allowed},
        )
    return resource


# ----------------------------------------------------------------------------- sink


class KnowledgeSink:
    """Writes synced files and rows into a knowledge base through the knowledge helpers."""

    def __init__(
        self,
        sync: Sync,
        connection: Connection,
        *,
        ingest: IngestBytes | None = None,
        upsert: UpsertTable | None = None,
    ) -> None:
        self.sync_id = sync.id
        self.org_id = sync.org_id
        self.kb_id = sync.kb_id
        self.connection_id = connection.id
        self.connector_key = connection.connector_key
        self._ingest = ingest
        self._upsert = upsert
        self.seen: set[str] = set()
        self.stats: dict[str, Any] = {
            "files_ingested": 0,
            "files_failed": 0,
            "file_errors": [],
            "bytes": 0,
            "rows_upserted": 0,
            "tables": [],
        }

    async def should_skip(self, external_id: str, version: str | None) -> bool:
        self.seen.add(external_id)
        if not version:
            return False
        async with system_session() as s:
            row = (
                await s.execute(
                    select(KbFile.meta, KbFile.status).where(
                        KbFile.org_id == self.org_id, KbFile.kb_id == self.kb_id, KbFile.external_id == external_id
                    )
                )
            ).first()
        if row is None:
            return False
        meta, status = row
        return status != "error" and (meta or {}).get("source_version") == version

    async def file(self, item: SyncFile) -> None:
        self.seen.add(item.external_id)
        ingest = self._ingest or ingest_bytes_impl()
        try:
            async with system_session() as s:
                kb_file = await ingest(
                    s,
                    org_id=self.org_id,
                    kb_id=self.kb_id,
                    filename=item.filename,
                    data=item.data,
                    mime=item.mime,
                    source="connector",
                    connection_id=self.connection_id,
                    external_id=item.external_id,
                    uploaded_by=None,
                )
                if isinstance(kb_file, KbFile):
                    kb_file.meta = {
                        **(kb_file.meta or {}),
                        "sync_id": str(self.sync_id),
                        "connector": self.connector_key,
                        "source_version": item.version,
                        "source_url": item.url,
                        "source_path": item.path,
                        "source_modified_at": item.modified_at,
                    }
        except knowledge_errors() as exc:  # unsupported format, empty or too large: skip this file only
            self.stats["files_failed"] += 1
            if len(self.stats["file_errors"]) < 20:
                self.stats["file_errors"].append(
                    {
                        "external_id": item.external_id,
                        "filename": item.filename,
                        "error": getattr(exc, "message", str(exc)),
                    }
                )
            return
        self.stats["files_ingested"] += 1
        self.stats["bytes"] += len(item.data)

    async def rows(
        self, table: str, columns: list[ColumnDef], rows: list[dict[str, Any]], primary_key: list[str]
    ) -> None:
        upsert = self._upsert or upsert_table_impl()
        async with system_session() as s:
            await upsert(
                s,
                org_id=self.org_id,
                kb_id=self.kb_id,
                table=table,
                columns=[c.as_dict() for c in columns],
                rows=rows,
                primary_key=primary_key,
                source="sync",
                sync_id=self.sync_id,
            )
        self.stats["rows_upserted"] += len(rows)
        if table not in self.stats["tables"]:
            self.stats["tables"].append(table)

    async def prune(self) -> int:
        """After a full file sync, remove files of this sync that no longer exist at the source."""
        knowledge = _knowledge()
        paths: list[str] = []
        async with system_session() as s:
            kb = await s.get(KnowledgeBase, self.kb_id)
            if kb is None:
                return 0
            stale = (
                (
                    await s.execute(
                        select(KbFile).where(
                            KbFile.org_id == self.org_id,
                            KbFile.kb_id == self.kb_id,
                            KbFile.connection_id == self.connection_id,
                            KbFile.meta["sync_id"].astext == str(self.sync_id),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for f in stale:
                if f.external_id and f.external_id not in self.seen:
                    paths.append(await knowledge.delete_file(s, kb, f))
        if paths:
            await knowledge.delete_blobs(paths)
        return len(paths)


# ----------------------------------------------------------------------------- execution


async def _publish(org_id: uuid.UUID, sync: Sync) -> None:
    try:
        await publish(
            f"org:{org_id}",
            {"type": "sync.status", "sync_id": str(sync.id), "status": sync.status, "error": sync.last_error},
            replay=False,
        )
    except Exception as exc:  # real-time fan-out is best effort
        log.warning("sync.publish_failed", error=str(exc))


async def execute_sync(
    sync_id: uuid.UUID, *, ingest: IngestBytes | None = None, upsert: UpsertTable | None = None
) -> dict[str, Any]:
    """Run one sync now (worker job). Never raises for connector failures: they are stored on the row."""
    now = datetime.now(UTC)
    async with system_session() as s:
        sync = (await s.execute(select(Sync).where(Sync.id == sync_id).with_for_update())).scalar_one_or_none()
        if sync is None:
            return {"status": "missing"}
        if sync.status == "running" and sync.updated_at and sync.updated_at > now - STALE_RUNNING:
            return {"status": "already_running"}
        sync.status = "running"
        sync.last_error = None
        sync.updated_at = now
        conn = (
            await s.execute(
                select(Connection).where(Connection.id == sync.connection_id, Connection.org_id == sync.org_id)
            )
        ).scalar_one_or_none()
        kb = (
            await s.execute(
                select(KnowledgeBase).where(KnowledgeBase.id == sync.kb_id, KnowledgeBase.org_id == sync.org_id)
            )
        ).scalar_one_or_none()
        request = SyncRequest(
            resource=sync.resource,
            mode="incremental" if sync.mode == "incremental" else "full",
            cursor_field=sync.cursor_field,
            cursor=sync.cursor if sync.mode == "incremental" else None,
            primary_key=[str(k) for k in sync.primary_key or []],
            options=dict(sync.options or {}),
        )
        org_id = sync.org_id
        previous_stats = dict(sync.stats or {})
    await _publish(org_id, sync)

    started = time.monotonic()
    status = "success"
    error: str | None = None
    next_cursor = request.cursor
    outcome_stats: dict[str, Any] = {}
    sink: KnowledgeSink | None = None
    try:
        if conn is None or conn.status == "revoked":
            raise ConnectorError("La conexión de esta sincronización ya no existe", code="connection_missing")
        if kb is None:
            raise ConnectorError("La base de conocimiento de esta sincronización ya no existe", code="kb_missing")
        adapter = registry.get_adapter(conn.connector_key)
        async with system_session() as s:
            ctx = await load_context(s, conn.id)
        sink = KnowledgeSink(sync, conn, ingest=ingest, upsert=upsert)
        outcome = await adapter.sync(ctx, request, sink)
        outcome_stats = dict(outcome.stats)
        if request.mode == "incremental":
            next_cursor = outcome.next_cursor or request.cursor
        else:
            next_cursor = outcome.next_cursor
        file_sync = not request.resource.startswith(("table:", "object:"))
        if request.mode == "full" and file_sync and request.options.get("prune", True) is not False:
            outcome_stats["pruned"] = await sink.prune()
    except (ConnectorError, SqlError, *knowledge_errors()) as exc:
        status = "error"
        error = str(getattr(exc, "message", exc))
        log.warning("sync.failed", sync_id=str(sync_id), error=error)
    except Exception as exc:
        status = "error"
        error = f"Error interno durante la sincronización: {type(exc).__name__}"
        log.exception("sync.crashed", sync_id=str(sync_id), error=str(exc))

    duration_ms = int((time.monotonic() - started) * 1000)
    finished = datetime.now(UTC)
    run_stats = {
        **outcome_stats,
        **(sink.stats if sink else {}),
        "status": status,
        "mode": request.mode,
        "duration_ms": duration_ms,
        "finished_at": finished.isoformat(),
    }
    totals = dict(previous_stats.get("totals") or {})
    totals["runs"] = int(totals.get("runs", 0)) + 1
    totals["errors"] = int(totals.get("errors", 0)) + (1 if status == "error" else 0)
    totals["files"] = int(totals.get("files", 0)) + int(run_stats.get("files_ingested", 0))
    totals["rows"] = int(totals.get("rows", 0)) + int(run_stats.get("rows_upserted", 0))
    history = [run_stats, *list(previous_stats.get("history") or [])][:10]

    async with system_session() as s:
        row = (await s.execute(select(Sync).where(Sync.id == sync_id).with_for_update())).scalar_one_or_none()
        if row is None:
            return {"status": "missing"}
        row.status = status
        row.last_error = error
        row.last_run_at = finished
        row.cursor = next_cursor
        row.stats = {"last_run": run_stats, "totals": totals, "history": history}
        row.next_run_at = next_run(row.schedule, finished)
        row.updated_at = finished
        await s.flush()
        snapshot = row
        if conn is not None:
            await connector_events.emit_event(
                s,
                org_id=org_id,
                connector_key=conn.connector_key,
                event="sync_completed",
                connection_id=conn.id,
                event_id=f"{sync_id}:{finished.isoformat()}",
                data={
                    "sync_id": str(sync_id),
                    "kb_id": str(row.kb_id),
                    "resource": row.resource,
                    "status": status,
                    "error": error,
                    "stats": run_stats,
                },
                occurred_at=finished.isoformat(),
            )
    await _publish(org_id, snapshot)
    return {"status": status, "error": error, "stats": run_stats, "cursor": next_cursor}


async def enqueue_sync(sync_id: uuid.UUID) -> None:
    try:
        await enqueue(Jobs.RUN_SYNC, str(sync_id))
    except Exception as exc:  # the scheduler re-queues syncs stuck in "queued"
        log.error("sync.enqueue_failed", sync_id=str(sync_id), error=str(exc))


_background: set[asyncio.Task[None]] = set()


def enqueue_after_commit(db: AsyncSession, sync_id: uuid.UUID) -> None:
    """Queue the job only once the request transaction has committed (the worker must see the row)."""
    loop = asyncio.get_running_loop()

    def after_commit(_session: Any) -> None:
        task = loop.create_task(enqueue_sync(sync_id))
        _background.add(task)
        task.add_done_callback(_background.discard)

    event.listen(db.sync_session, "after_commit", after_commit, once=True)


# ----------------------------------------------------------------------------- scheduler tasks


async def enqueue_due_syncs(
    now: datetime | None = None, *, send: Callable[[uuid.UUID], Awaitable[Any]] | None = None
) -> list[uuid.UUID]:
    """Queue every scheduled sync whose ``next_run_at`` has passed (and re-queue syncs lost while queued)."""
    now = now or datetime.now(UTC)
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(Sync)
                    .where(
                        Sync.schedule.is_not(None),
                        or_(
                            Sync.next_run_at <= now,
                            Sync.next_run_at.is_(None),
                        ),
                        Sync.status.not_in(("running", "queued")),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        stuck = (
            (
                await s.execute(
                    select(Sync)
                    .where(Sync.status == "queued", Sync.updated_at < now - STALE_QUEUED)
                    .with_for_update(skip_locked=True)
                    .limit(50)
                )
            )
            .scalars()
            .all()
        )
        ids: list[uuid.UUID] = []
        for sync in [*rows, *stuck]:
            sync.status = "queued"
            sync.updated_at = now
            sync.next_run_at = next_run(sync.schedule, now)
            ids.append(sync.id)
    sender = send or (lambda sid: enqueue(Jobs.RUN_SYNC, str(sid)))
    for sid in ids:
        await sender(sid)
    if ids:
        log.info("syncs.enqueued", count=len(ids))
    return ids


async def mark_stale_agents_offline(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(ConnectorAgent).where(
                        ConnectorAgent.status == "online",
                        or_(
                            ConnectorAgent.last_seen_at.is_(None),
                            ConnectorAgent.last_seen_at < now - AGENT_OFFLINE_AFTER,
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for agent in rows:
            agent.status = "offline"
    return len(rows)


async def purge_old_connector_events(now: datetime | None = None) -> int:
    from messer_common.db.models.connectors import ConnectorEvent

    now = now or datetime.now(UTC)
    async with system_session() as s:
        res = await s.execute(delete(ConnectorEvent).where(ConnectorEvent.created_at < now - EVENT_RETENTION))
    return int(getattr(res, "rowcount", 0) or 0)


async def sync_for_api(db: AsyncSession, org_id: uuid.UUID, sync_id: uuid.UUID) -> Sync | None:
    sync = await db.get(Sync, sync_id)
    return sync if sync is not None and sync.org_id == org_id else None
