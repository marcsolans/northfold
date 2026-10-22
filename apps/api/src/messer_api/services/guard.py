"""Guard (behaviour control, spec 7.13) for the control plane: playbooks per agent, generation, enablement,
metrics and recent decisions. Enforcement happens in the runtime model gateway (``messer_runtime.guard``)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Integer, Numeric, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import GuardPlaybook, Project, Run, Span, Workforce
from messer_common.guard import (
    Playbook,
    ToolInfo,
    empty_playbook,
    known_models,
    tools_from_config,
    validate_playbook,
)
from messer_common.guard.generate import GenerationResult, generate_playbook
from messer_common.llm import LlmRefused
from messer_common.plans import plan_has_feature

from ..errors import ApiError, Conflict, PaymentRequired
from . import limits
from . import projects as projects_svc

FEATURE = "guard"
MAX_DECISIONS = 200


class InvalidPlaybook(ApiError):
    status_code = 422
    code = "invalid_playbook"


@dataclass(slots=True)
class GuardState:
    member: Workforce
    row: GuardPlaybook | None
    playbook: Playbook | None
    tools: list[ToolInfo]

    @property
    def enabled(self) -> bool:
        return bool(self.member.guard_enabled and self.playbook is not None and self.playbook.enabled)


async def agent(session: AsyncSession, project: Project, name: str) -> Workforce:
    member = await projects_svc.get_member(session, project, name)
    if member.kind != "agent":
        raise ApiError("Guard se configura en los agentes", code="not_an_agent")
    return member


async def _row(session: AsyncSession, member: Workforce) -> GuardPlaybook | None:
    return (
        await session.execute(select(GuardPlaybook).where(GuardPlaybook.workforce_id == member.id))
    ).scalar_one_or_none()


async def state(session: AsyncSession, project: Project, name: str) -> GuardState:
    member = await agent(session, project, name)
    row = await _row(session, member)
    playbook: Playbook | None = None
    if row is not None and row.playbook:
        result = validate_playbook(row.playbook)
        playbook = result.playbook
    return GuardState(member=member, row=row, playbook=playbook, tools=tools_from_config(member.config_json))


def known_facts(playbook: Playbook | None, tools: list[ToolInfo]) -> list[str]:
    facts = {f"tool:{t.name}" for t in tools} | {f"approval:{t.name}" for t in tools if t.gated or t.side_effect}
    if playbook is not None:
        for p in playbook.policies:
            facts.update(p.provides)
            facts.update(p.requires)
    return sorted(facts)


async def plan_allows(session: AsyncSession, org_id: uuid.UUID) -> bool:
    plan = await limits.org_plan(session, org_id)
    return plan is None or plan_has_feature(plan.limits, FEATURE)


async def describe(session: AsyncSession, project: Project, st: GuardState) -> dict[str, Any]:
    issues = []
    if st.row is not None and st.row.playbook:
        issues = [i.as_dict() for i in validate_playbook(st.row.playbook, tools=st.tools).issues]
    defaults = empty_playbook()
    return {
        "member": st.member.name,
        "workforce_id": st.member.id,
        "enabled": st.enabled,
        "playbook": st.row.playbook if st.row is not None and st.row.playbook else None,
        "generated_by": st.row.generated_by if st.row is not None else None,
        "meta": st.row.meta if st.row is not None else {},
        "updated_at": st.row.updated_at if st.row is not None else None,
        "updated_by": st.row.updated_by if st.row is not None else None,
        "issues": issues,
        "tools": [t.as_dict() for t in st.tools],
        "models": known_models(),
        "defaults": {"small_model": defaults.small_model, "large_model": defaults.large_model},
        "facts": known_facts(st.playbook, st.tools),
        "plan_allows": await plan_allows(session, project.org_id),
    }


async def _store(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    st: GuardState,
    playbook: Playbook,
    *,
    generated_by: str,
    meta: dict[str, Any] | None,
) -> GuardPlaybook:
    data = playbook.model_copy(update={"enabled": st.enabled}).model_dump(mode="json")
    row = st.row
    if row is None:
        row = GuardPlaybook(org_id=project.org_id, project_id=project.id, workforce_id=st.member.id)
        session.add(row)
    row.playbook = data
    row.generated_by = generated_by
    if meta is not None:
        row.meta = meta
    row.updated_by = principal.user_id
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def save(
    session: AsyncSession, principal: Principal, project: Project, name: str, data: dict[str, Any]
) -> GuardState:
    st = await state(session, project, name)
    result = validate_playbook(data, tools=st.tools)
    if not result.ok or result.playbook is None:
        raise InvalidPlaybook(
            "El playbook tiene errores",
            details={"issues": [i.as_dict() for i in result.issues]},
        )
    meta = dict(st.row.meta) if st.row is not None else {}
    meta["edited_at"] = datetime.now(UTC).isoformat()
    await _store(session, principal, project, st, result.playbook, generated_by="manual", meta=meta)
    await audit.record(
        session,
        action="guard.playbook_updated",
        principal=principal,
        entity_type="workforce",
        entity_id=st.member.id,
        diff={"member": name, "policies": [p.id for p in result.playbook.policies]},
    )
    return await state(session, project, name)


async def _agent_code(project: Project, member: Workforce) -> str:
    repo = projects_svc.repo_for(project)
    parts: list[str] = []
    for rel in (f"{member.path}/agent.py", f"{member.path}/tools.py"):
        content = await repo.read(rel)
        if content:
            parts.append(f"# --- {rel}\n{content}")
    return "\n\n".join(parts)


async def regenerate(session: AsyncSession, principal: Principal, project: Project, name: str) -> GuardState:
    st = await state(session, project, name)
    current = st.playbook
    try:
        result: GenerationResult = await generate_playbook(
            org_id=project.org_id,
            project_id=project.id,
            config=st.member.config_json,
            code=await _agent_code(project, st.member),
            tools=st.tools,
            small_model=current.small_model if current else None,
            large_model=current.large_model if current else None,
        )
    except LlmRefused as exc:
        raise PaymentRequired(exc.message, code=exc.error_type) from exc
    meta = {**result.meta, "generated_at": datetime.now(UTC).isoformat()}
    await _store(session, principal, project, st, result.playbook, generated_by=result.generated_by, meta=meta)
    await audit.record(
        session,
        action="guard.playbook_generated",
        principal=principal,
        entity_type="workforce",
        entity_id=st.member.id,
        diff={"member": name, "generated_by": result.generated_by, "policies": len(result.playbook.policies)},
    )
    return await state(session, project, name)


async def set_enabled(
    session: AsyncSession, principal: Principal, project: Project, name: str, enabled: bool
) -> GuardState:
    st = await state(session, project, name)
    if enabled:
        await limits.require_feature(session, project.org_id, FEATURE)
        if st.row is None or not st.row.playbook:
            raise Conflict("Genera o escribe el playbook antes de activar Guard", code="no_playbook")
        if st.playbook is None:
            raise InvalidPlaybook("Corrige los errores del playbook antes de activar Guard")
    if st.row is not None and st.row.playbook:
        st.row.playbook = {**st.row.playbook, "enabled": enabled}
        st.row.updated_by = principal.user_id
        st.row.updated_at = datetime.now(UTC)
    st.member.guard_enabled = enabled
    await audit.record(
        session,
        action="guard.enabled" if enabled else "guard.disabled",
        principal=principal,
        entity_type="workforce",
        entity_id=st.member.id,
        diff={"member": name},
    )
    await session.flush()
    return await state(session, project, name)


async def overview(session: AsyncSession, project: Project) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Workforce, GuardPlaybook)
            .outerjoin(GuardPlaybook, GuardPlaybook.workforce_id == Workforce.id)
            .where(Workforce.project_id == project.id, Workforce.kind == "agent")
            .order_by(Workforce.name)
        )
    ).all()
    agents = []
    for member, row in rows:
        stored = row.playbook if row is not None else {}
        policies = stored.get("policies") if isinstance(stored, dict) else None
        agents.append(
            {
                "member": member.name,
                "enabled": bool(member.guard_enabled and isinstance(stored, dict) and stored.get("enabled")),
                "has_playbook": bool(stored),
                "generated_by": row.generated_by if row is not None else None,
                "policies": len(policies) if isinstance(policies, list) else 0,
                "updated_at": row.updated_at if row is not None else None,
            }
        )
    return {"agents": agents, "plan_allows": await plan_allows(session, project.org_id)}


# ---------------------------------------------------------------------------------------------- metrics


def _since_ms(days: int) -> int:
    return int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)


def _guard_filter(project: Project, member: Workforce, days: int) -> list[Any]:
    return [
        Span.kind == "guard",
        Run.project_id == project.id,
        Run.workforce_id == member.id,
        Span.t0 >= _since_ms(days),
    ]


def _usd(value: Any) -> str:
    return str(Decimal(str(value or 0)).quantize(Decimal("0.000001")))


async def metrics(session: AsyncSession, project: Project, name: str, days: int) -> dict[str, Any]:
    member = await agent(session, project, name)
    spans = (
        select(
            Span.run_id.label("run_id"),
            Span.name.label("name"),
            Span.status.label("status"),
            Span.t0.label("t0"),
            Span.meta.label("meta"),
        )
        .join(Run, Run.id == Span.run_id)
        .where(*_guard_filter(project, member, days))
        .subquery()
    )
    turn = spans.c.meta["kind"].astext == "turn"

    def num(key: str) -> Any:
        return func.coalesce(
            func.sum(case((turn, cast(func.nullif(spans.c.meta[key].astext, ""), Numeric(18, 6))), else_=0)), 0
        )

    totals = (
        await session.execute(
            select(
                func.count().filter(turn).label("turns"),
                func.count().filter(turn, spans.c.meta["on_path"].astext == "true").label("on_path"),
                func.coalesce(
                    func.sum(cast(func.coalesce(spans.c.meta["blocked_count"].astext, "0"), Integer)), 0
                ).label("blocked"),
                func.count(func.distinct(spans.c.run_id)).label("runs"),
                func.count().filter(spans.c.status == "error").label("errors"),
                func.count().filter(spans.c.status == "invalid_output").label("invalid_output"),
                num("guarded_cost_usd").label("guarded"),
                num("baseline_cost_usd").label("baseline"),
                num("overhead_cost_usd").label("overhead"),
                func.bool_and(spans.c.meta["demo"].astext == "true").label("demo"),
            )
        )
    ).one()
    route = spans.c.meta["route"].astext.label("route")
    routes = {
        str(r or "default"): int(n)
        for r, n in (await session.execute(select(route, func.count()).where(turn).group_by(route))).all()
    }
    day = func.date_trunc("day", func.to_timestamp(spans.c.t0 / 1000.0)).label("day")
    daily = [
        {"day": d.date().isoformat(), "turns": int(t), "on_path": int(p), "blocked": int(b)}
        for d, t, p, b in (
            await session.execute(
                select(
                    day,
                    func.count().filter(turn),
                    func.count().filter(turn, spans.c.meta["on_path"].astext == "true"),
                    func.coalesce(func.sum(cast(func.coalesce(spans.c.meta["blocked_count"].astext, "0"), Integer)), 0),
                )
                .group_by(day)
                .order_by(day)
            )
        ).all()
    ]
    policies = [
        {"policy": str(policy), "turns": int(n), "blocked": int(b)}
        for policy, n, b in (
            await session.execute(
                select(
                    spans.c.name,
                    func.count(),
                    func.coalesce(func.sum(cast(func.coalesce(spans.c.meta["blocked_count"].astext, "0"), Integer)), 0),
                )
                .group_by(spans.c.name)
                .order_by(func.count().desc())
                .limit(20)
            )
        ).all()
    ]
    turns, runs = int(totals.turns or 0), int(totals.runs or 0)
    guarded, baseline = Decimal(str(totals.guarded or 0)), Decimal(str(totals.baseline or 0))
    savings = float((baseline - guarded) / baseline * 100) if baseline > 0 else None
    return {
        "days": days,
        "runs": runs,
        "turns": turns,
        "on_path_turns": int(totals.on_path or 0),
        "on_path_share": (int(totals.on_path or 0) / turns) if turns else None,
        "blocked_actions": int(totals.blocked or 0),
        "errors": int(totals.errors or 0),
        "invalid_outputs": int(totals.invalid_output or 0),
        "routes": routes,
        "cost": {
            "guarded_usd": _usd(guarded),
            "baseline_usd": _usd(baseline),
            "overhead_usd": _usd(totals.overhead),
            "per_run_guarded_usd": _usd(guarded / runs) if runs else None,
            "per_run_baseline_usd": _usd(baseline / runs) if runs else None,
            "savings_pct": round(savings, 1) if savings is not None else None,
        },
        "demo": bool(totals.demo) if turns else False,
        "daily": daily,
        "policies": policies,
    }


async def decisions(
    session: AsyncSession, project: Project, name: str, limit: int, days: int = 30
) -> list[dict[str, Any]]:
    member = await agent(session, project, name)
    rows = (
        await session.execute(
            select(Span, Run.channel)
            .join(Run, Run.id == Span.run_id)
            .where(*_guard_filter(project, member, days))
            .order_by(Span.t0.desc())
            .limit(min(limit, MAX_DECISIONS))
        )
    ).all()
    out: list[dict[str, Any]] = []
    for span, channel in rows:
        meta = span.meta or {}
        output = span.output if isinstance(span.output, dict) else {}
        inp = span.input if isinstance(span.input, dict) else {}
        out.append(
            {
                "span_id": span.id,
                "run_id": span.run_id,
                "at": datetime.fromtimestamp(span.t0 / 1000, UTC),
                "channel": channel,
                "policy": span.name,
                "action": meta.get("action"),
                "status": span.status,
                "route": meta.get("route"),
                "model": span.model,
                "requested_model": meta.get("requested_model"),
                "on_path": bool(meta.get("on_path")),
                "text": inp.get("text") or "",
                "turn": inp.get("turn"),
                "tool_calls": output.get("tool_calls") or [],
                "blocked": meta.get("blocked") or [],
                "votes": meta.get("votes") or [],
                "facts": meta.get("facts") or [],
                "latency_ms": (span.t1 - span.t0) if span.t1 else None,
                "overhead_cost_usd": str(span.cost_usd),
                "priced_cost_usd": meta.get("priced_cost_usd"),
                "baseline_cost_usd": meta.get("baseline_cost_usd"),
                "demo": bool(meta.get("demo")),
                "errors": meta.get("errors") or [],
            }
        )
    return out
