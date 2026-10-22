"""Facts of a conversation (``requires`` / ``provides``), kept per run in Redis and carried forward to child runs.

A run that continues a conversation (``parent_run_id``: memory or approval resume) starts with its parent's
facts — from Redis while they live (24 h), otherwise from the last Guard span persisted for the parent — plus
``approval:<tool>`` for every approval of the parent run that a human approved.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Approval, Run, Span
from messer_common.events import get_redis

TTL_S = 86400
FACTS_KEY = "guard:{run}:facts"
SEEDED_KEY = "guard:{run}:seeded"


def run_key(run_id: str) -> str:
    """Runs are addressed with or without dashes; facts are keyed by the canonical hex form."""
    try:
        return uuid.UUID(hex=run_id.replace("-", "")).hex
    except ValueError:
        return run_id


async def _seed(run: str, org_id: uuid.UUID) -> set[str]:
    try:
        run_uuid = uuid.UUID(hex=run)
    except ValueError:
        return set()
    async with system_session() as s:
        row = await s.get(Run, run_uuid)
        if row is None or row.org_id != org_id or row.parent_run_id is None:
            return set()
        parent = row.parent_run_id
        facts: set[str] = set(await get_redis().smembers(FACTS_KEY.format(run=parent.hex)) or [])  # type: ignore[misc]
        if not facts:
            spans = (
                (
                    await s.execute(
                        select(Span.meta)
                        .where(Span.run_id == parent, Span.org_id == org_id, Span.kind == "guard")
                        .order_by(Span.t0.desc())
                        .limit(1)
                    )
                )
                .scalars()
                .all()
            )
            for meta in spans:
                stored: Any = (meta or {}).get("facts")
                if isinstance(stored, list):
                    facts.update(str(f) for f in stored)
        approved = (
            (
                await s.execute(
                    select(Approval.tool_name).where(
                        Approval.run_id == parent, Approval.org_id == org_id, Approval.status == "approved"
                    )
                )
            )
            .scalars()
            .all()
        )
        facts.update(f"approval:{name}" for name in approved)
    return facts


async def load(run_id: str, org_id: uuid.UUID) -> set[str]:
    run = run_key(run_id)
    r = get_redis()
    key = FACTS_KEY.format(run=run)
    if await r.set(SEEDED_KEY.format(run=run), "1", nx=True, ex=TTL_S):
        seeded = await _seed(run, org_id)
        if seeded:
            await r.sadd(key, *sorted(seeded))  # type: ignore[misc]
            await r.expire(key, TTL_S)
    return set(await r.smembers(key) or [])  # type: ignore[misc]


async def add(run_id: str, facts: set[str]) -> None:
    if not facts:
        return
    run = run_key(run_id)
    r = get_redis()
    key = FACTS_KEY.format(run=run)
    await r.sadd(key, *sorted(facts))  # type: ignore[misc]
    await r.expire(key, TTL_S)
