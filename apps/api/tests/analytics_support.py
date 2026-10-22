"""Seed helpers for the governance tests (analytics, custom metrics, alarms): runs, spans and feedback rows."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from messer_common.db import system_session
from messer_common.db.models import Feedback, Project, Run, Span, Workforce

NOW = datetime.now(UTC).replace(microsecond=0)


def percentile(values: Sequence[float], p: float) -> float:
    """PostgreSQL percentile_cont (linear interpolation)."""
    data = sorted(values)
    pos = p * (len(data) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(data) - 1)
    return data[lo] + (data[hi] - data[lo]) * (pos - lo)


async def make_project(org_id: uuid.UUID, name: str, agents: tuple[str, ...] = ()) -> uuid.UUID:
    async with system_session() as s:
        project = Project(org_id=org_id, name=name, slug=f"p-{uuid.uuid4().hex[:8]}", repo_path="/tmp/analytics")
        s.add(project)
        await s.flush()
        for agent in agents:
            s.add(Workforce(org_id=org_id, project_id=project.id, kind="agent", name=agent, path=f"workforce/{agent}"))
        return project.id


async def add_run(
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    agent: str = "soporte",
    status: str = "success",
    cost: str = "0",
    credits: str = "0",
    duration_ms: int | None = 100,
    started_at: datetime | None = None,
    channel: str = "studio",
    environment: str = "production",
    user_id: uuid.UUID | None = None,
    external_user_id: str | None = None,
    models: list[str] | None = None,
    output: Any = None,
    spans: list[dict[str, Any]] | None = None,
) -> uuid.UUID:
    run_id = uuid.uuid4()
    started = started_at or NOW - timedelta(minutes=5)
    async with system_session() as s:
        s.add(
            Run(
                id=run_id,
                org_id=org_id,
                project_id=project_id,
                workforce_name=agent,
                status=status,
                cost_usd=Decimal(cost),
                credits=Decimal(credits),
                duration_ms=duration_ms,
                started_at=started,
                ended_at=started + timedelta(milliseconds=duration_ms or 0),
                channel=channel,
                environment=environment,
                user_id=user_id,
                external_user_id=external_user_id,
                models=[{"model": m, "providers": ["anthropic"]} for m in (models or [])],
                output=output,
                error={"type": "boom", "message": "fallo"} if status == "error" else None,
            )
        )
        await s.flush()
        t0 = int(started.timestamp() * 1000)
        for i, sp in enumerate(spans or []):
            s.add(
                Span(
                    org_id=org_id,
                    run_id=run_id,
                    call_id=f"c{i}",
                    kind=sp.get("kind", "llm"),
                    name=sp.get("name", "llm"),
                    path=sp.get("path", f"{agent}.llm"),
                    status=sp.get("status", "success"),
                    model=sp.get("model"),
                    input_tokens=sp.get("input_tokens", 0),
                    output_tokens=sp.get("output_tokens", 0),
                    cost_usd=Decimal(str(sp.get("cost", "0"))),
                    output=sp.get("output"),
                    error=sp.get("error"),
                    t0=t0 + sp.get("offset_ms", 0),
                    t1=t0 + sp.get("offset_ms", 0) + sp.get("duration_ms", 50),
                )
            )
    return run_id


async def add_feedback(
    org_id: uuid.UUID, run_id: uuid.UUID, value: str, comment: str | None = None, *, at: datetime | None = None
) -> None:
    async with system_session() as s:
        s.add(
            Feedback(
                org_id=org_id, run_id=run_id, value=value, comment=comment, created_at=at or NOW - timedelta(minutes=1)
            )
        )
