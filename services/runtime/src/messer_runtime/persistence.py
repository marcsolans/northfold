"""Run and span persistence (our own tracing backend for the engine's platform tracing provider)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import ModelPrice, Run, Span
from messer_common.events import get_redis
from messer_common.pricing import MTOK

MAX_JSON_CHARS = 200_000


def to_uuid(run_id: str) -> uuid.UUID:
    return uuid.UUID(hex=run_id.replace("-", ""))


def _clip(value: Any) -> Any:
    """Keep span payloads bounded (huge tool outputs are already offloaded by the engine)."""
    try:
        raw = json.dumps(value, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return {"repr": str(value)[:2000]}
    if len(raw) <= MAX_JSON_CHARS:
        return json.loads(raw)
    return {"truncated": True, "preview": raw[:20_000], "size": len(raw)}


def _status_code(status: Any) -> tuple[str, str | None]:
    if isinstance(status, dict):
        return str(status.get("code") or "success"), status.get("reason")
    return "success", None


def span_kind(path: str, root_path: str, root_kind: str, record: dict[str, Any]) -> str:
    meta = record.get("metadata") or {}
    if path == root_path:
        return root_kind
    leaf = path.rsplit(".", 1)[-1]
    if leaf == "llm" or meta.get("type") == "llm":
        return "llm"
    if meta.get("guard"):
        return "guard"
    if "guardrail" in leaf or meta.get("guardrail"):
        return "guardrail"
    parent_depth = root_path.count(".") + 1
    if root_kind == "workflow" and path.count(".") == parent_depth:
        return "step"
    return "tool"


def _usage_tokens(usage: dict[str, Any]) -> tuple[str | None, int, int, int]:
    model = None
    inp = out = cache = 0
    for key, value in (usage or {}).items():
        if ":" not in key or not isinstance(value, int | float):
            continue
        m, unit = key.rsplit(":", 1)
        if "/" not in m:
            continue
        model = model or m
        if unit.startswith("output"):
            out += int(value)
        elif "cache_read" in unit or unit.startswith("input_cached"):
            cache += int(value)
        elif unit.startswith("input") or "cache_creation" in unit or unit.startswith("ephemeral"):
            inp += int(value)
    return model, inp, out, cache


def _span_cost(model: str | None, inp: int, out: int, cache: int, prices: dict[str, ModelPrice], demo: bool) -> Decimal:
    if demo or model is None or model not in prices:
        return Decimal("0")
    p = prices[model]
    return (
        Decimal(inp) * p.input_per_mtok_usd
        + Decimal(out) * p.output_per_mtok_usd
        + Decimal(cache) * p.cache_read_per_mtok_usd
    ) / MTOK


def trace_records(trace: Any) -> list[dict[str, Any]]:
    """The engine serializes a trace as a list of span records (older dumps used a dict keyed by call id)."""
    if isinstance(trace, dict):
        return [r for r in trace.values() if isinstance(r, dict)]
    if isinstance(trace, list):
        return [r for r in trace if isinstance(r, dict)]
    return []


async def store_trace(
    session: AsyncSession, *, run_id: str, org_id: uuid.UUID, project_id: uuid.UUID, parent_id: str | None, trace: Any
) -> None:
    """PATCH target of the engine's tracing provider: keep the full trace for memory/resume."""
    stmt = (
        insert(Run)
        .values(
            id=to_uuid(run_id),
            org_id=org_id,
            project_id=project_id,
            status="running",
            parent_run_id=to_uuid(parent_id) if parent_id else None,
            trace=trace,
        )
        .on_conflict_do_update(index_elements=[Run.id], set_={"trace": trace})
    )
    await session.execute(stmt)


async def load_trace(session: AsyncSession, *, run_id: str, org_id: uuid.UUID) -> Any:
    run = await session.get(Run, to_uuid(run_id))
    if run is None or run.org_id != org_id:
        return None
    return run.trace


async def persist_spans(
    session: AsyncSession, *, run: Run, trace: Any, root_kind: str, demo: bool
) -> tuple[Decimal, list[str]]:
    """Flatten the engine trace into ``spans`` rows. Returns (sum of LLM span costs, models used)."""
    prices = {p.model: p for p in (await session.execute(select(ModelPrice))).scalars()}
    await session.execute(delete(Span).where(Span.run_id == run.id))
    records = trace_records(trace)
    root = next((r for r in records if r.get("parent_call_id") is None), records[0] if records else None)
    if root is None:
        return Decimal("0"), []
    root_path = str(root.get("path", ""))
    total = Decimal("0")
    models: list[str] = []
    call_to_span: dict[str, uuid.UUID] = {}
    for record in records:
        call_to_span[str(record["call_id"])] = uuid.uuid4()
    for record in records:
        path = str(record.get("path", ""))
        kind = span_kind(path, root_path, root_kind, record)
        model, inp, out, cache = _usage_tokens(record.get("usage") or {}) if kind == "llm" else (None, 0, 0, 0)
        if kind == "llm":
            llm_input = record.get("input") or {}
            if isinstance(llm_input, dict) and llm_input.get("model"):
                model = str(llm_input["model"])
        cost = _span_cost(model, inp, out, cache, prices, demo) if kind == "llm" else Decimal("0")
        if kind == "llm":
            total += cost
            if model and model not in models:
                models.append(model)
        code, reason = _status_code(record.get("status"))
        parent_call = record.get("parent_call_id")
        meta = dict(record.get("metadata") or {})
        if reason:
            meta["status_reason"] = reason
        session.add(
            Span(
                id=call_to_span[str(record["call_id"])],
                org_id=run.org_id,
                run_id=run.id,
                call_id=str(record["call_id"]),
                parent_call_id=str(parent_call) if parent_call else None,
                parent_span_id=call_to_span.get(str(parent_call)) if parent_call else None,
                kind=kind,
                name=path.rsplit(".", 1)[-1] if kind != root_kind else path,
                path=path,
                status=code,
                input=_clip(record.get("input")),
                output=_clip(record.get("output")),
                error=_clip(record.get("error")) if record.get("error") else None,
                model=model,
                input_tokens=inp,
                output_tokens=out,
                cache_read_tokens=cache,
                cost_usd=cost,
                t0=int(record.get("t0") or 0),
                t1=int(record["t1"]) if record.get("t1") else None,
                meta=_clip(meta),
            )
        )
    return total, models


async def gateway_totals(run_id: str) -> tuple[Decimal, set[str], list[dict[str, Any]], str | None]:
    r = get_redis()
    cost = await r.get(f"run:{run_id}:cost_usd")
    providers = await r.smembers(f"run:{run_id}:providers")  # type: ignore[misc]
    calls = [json.loads(c) for c in await r.lrange(f"run:{run_id}:calls", 0, -1)]  # type: ignore[misc]
    budget = await r.get(f"run:{run_id}:budget_exceeded")
    return Decimal(str(cost or "0")), set(providers or []), calls, budget


def now() -> datetime:
    return datetime.now(UTC)
