"""Data retention (spec §9.3), hourly:

* runs and their spans older than each organization's ``trace_retention_days`` (runs still ``running`` or
  ``paused`` waiting for an approval are never touched);
* conversations idle for longer than ``conversation_retention_days``;
* expired GDPR export archives (``MESSER_DATA_EXPORT_TTL_DAYS``) and expired SSO state / SAML replay entries.

Deletes run in small batches (``MESSER_RETENTION_BATCH_SIZE``), one short transaction per batch, and each
organization with deletions gets one audited summary (``retention.purged``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, text

from messer_common import audit
from messer_common.db import system_session
from messer_common.logging import get_logger
from messer_common.settings import get_settings
from messer_common.storage import StorageError, get_storage
from messer_scheduler.core import PeriodicTask

log = get_logger("messer.scheduler.retention")

INTERVAL_S = 3600
PROTECTED_RUN_STATUSES = ["running", "paused"]
EPHEMERAL_TOKEN_PURPOSES = ["sso_state", "saml_assertion"]


@dataclass(slots=True)
class OrgPurge:
    org_id: uuid.UUID
    runs: int
    spans: int
    conversations: int
    trace_cutoff: datetime
    conversation_cutoff: datetime

    @property
    def total(self) -> int:
        return self.runs + self.spans + self.conversations


def _rows(result: Any) -> int:
    return int(cast("CursorResult[Any]", result).rowcount or 0)


async def purge_org(
    org_id: uuid.UUID, *, trace_days: int, conversation_days: int, now: datetime, batch_size: int
) -> OrgPurge:
    trace_cutoff = now - timedelta(days=max(trace_days, 1))
    conversation_cutoff = now - timedelta(days=max(conversation_days, 1))
    runs = spans = conversations = 0
    while True:
        async with system_session() as s:
            ids = [
                r[0]
                for r in await s.execute(
                    text(
                        "SELECT id FROM runs WHERE org_id = :org AND started_at < :cutoff "
                        "AND status <> ALL(:protected) ORDER BY started_at LIMIT :n FOR UPDATE SKIP LOCKED"
                    ),
                    {"org": org_id, "cutoff": trace_cutoff, "protected": PROTECTED_RUN_STATUSES, "n": batch_size},
                )
            ]
            if not ids:
                break
            spans += _rows(await s.execute(text("DELETE FROM spans WHERE run_id = ANY(:ids)"), {"ids": ids}))
            runs += _rows(await s.execute(text("DELETE FROM runs WHERE id = ANY(:ids)"), {"ids": ids}))
        if len(ids) < batch_size:
            break
    while True:
        async with system_session() as s:
            deleted = _rows(
                await s.execute(
                    text(
                        "DELETE FROM conversations WHERE id IN (SELECT id FROM conversations WHERE org_id = :org "
                        "AND updated_at < :cutoff ORDER BY updated_at LIMIT :n FOR UPDATE SKIP LOCKED)"
                    ),
                    {"org": org_id, "cutoff": conversation_cutoff, "n": batch_size},
                )
            )
        conversations += deleted
        if deleted < batch_size:
            break
    result = OrgPurge(org_id, runs, spans, conversations, trace_cutoff, conversation_cutoff)
    if result.total:
        async with system_session() as s:
            await audit.record(
                s,
                action="retention.purged",
                org_id=org_id,
                entity_type="org",
                entity_id=org_id,
                diff={
                    "runs": runs,
                    "spans": spans,
                    "conversations": conversations,
                    "trace_retention_days": trace_days,
                    "conversation_retention_days": conversation_days,
                    "trace_cutoff": trace_cutoff.isoformat(),
                    "conversation_cutoff": conversation_cutoff.isoformat(),
                },
            )
    return result


async def expire_exports(now: datetime) -> int:
    """Delete export archives older than the download window and mark their requests ``expired``."""
    ttl = timedelta(days=get_settings().messer_data_export_ttl_days)
    async with system_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, file_path FROM data_requests WHERE kind = 'export' AND status = 'completed' "
                    "AND file_path IS NOT NULL AND completed_at < :cutoff"
                ),
                {"cutoff": now - ttl},
            )
        ).all()
    storage = get_storage()
    expired = 0
    for request_id, path in rows:
        try:
            await storage.delete(str(path))
        except StorageError as exc:
            log.warning("retention.export_delete_failed", request_id=str(request_id), error=str(exc))
            continue
        async with system_session() as s:
            await s.execute(
                text("UPDATE data_requests SET status = 'expired', file_path = NULL WHERE id = :id"),
                {"id": request_id},
            )
        expired += 1
    return expired


async def purge_ephemeral_tokens(now: datetime) -> int:
    async with system_session() as s:
        return _rows(
            await s.execute(
                text("DELETE FROM one_time_tokens WHERE purpose = ANY(:purposes) AND expires_at < :cutoff"),
                {"purposes": EPHEMERAL_TOKEN_PURPOSES, "cutoff": now - timedelta(days=1)},
            )
        )


async def run_retention(now: datetime | None = None) -> list[OrgPurge]:
    now = now or datetime.now(UTC)
    batch_size = max(get_settings().messer_retention_batch_size, 1)
    async with system_session() as s:
        orgs = (
            await s.execute(text("SELECT id, trace_retention_days, conversation_retention_days FROM orgs ORDER BY id"))
        ).all()
    results: list[OrgPurge] = []
    for org_id, trace_days, conversation_days in orgs:
        try:
            result = await purge_org(
                org_id,
                trace_days=int(trace_days),
                conversation_days=int(conversation_days),
                now=now,
                batch_size=batch_size,
            )
        except Exception as exc:  # one organization never blocks the others
            log.error("retention.org_failed", org_id=str(org_id), error=repr(exc))
            continue
        if result.total:
            results.append(result)
    exports = await expire_exports(now)
    tokens = await purge_ephemeral_tokens(now)
    log.info(
        "retention.done",
        orgs=len(results),
        runs=sum(r.runs for r in results),
        conversations=sum(r.conversations for r in results),
        exports_expired=exports,
        tokens_purged=tokens,
    )
    return results


async def _tick() -> None:
    await run_retention()


TASKS = [PeriodicTask("retention", INTERVAL_S, _tick)]
