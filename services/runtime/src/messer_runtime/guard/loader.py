"""Which agent a model call belongs to, and its Guard playbook (read on every call: no stale cache)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import GuardPlaybook, Workforce
from messer_common.guard import Playbook, ToolInfo, tools_from_config
from messer_common.guard.evaluator import full_model
from messer_common.logging import get_logger
from messer_common.models_config import resolve_model

from .. import guard_bridge

log = get_logger("messer.runtime.guard")


@dataclass(slots=True)
class GuardTarget:
    org_id: uuid.UUID
    project_id: uuid.UUID
    member: str
    workforce_id: uuid.UUID
    playbook: Playbook
    tools: list[ToolInfo]
    agent_model: str | None

    def gated(self, tool_name: str) -> bool:
        return any(t.gated for t in self.tools if t.name == tool_name)


@dataclass(slots=True)
class InvalidPlaybook:
    """Guard is enabled but the stored playbook does not validate: calls pass through and the trace says why."""

    member: str
    error: str


def _agent_model(config: dict[str, Any] | None) -> str | None:
    if not config:
        return None
    try:
        return resolve_model(config.get("model") or config.get("model_tier") or "standard")
    except ValueError:
        return None


async def load_target(
    org_id: uuid.UUID, project_id: uuid.UUID | None, run_id: str
) -> GuardTarget | InvalidPlaybook | None:
    member = await guard_bridge.member_of(run_id)
    if member is None:
        return None
    raw_project, name = member
    try:
        member_project = uuid.UUID(raw_project)
    except ValueError:
        return None
    if project_id is not None and project_id != member_project:
        return None  # a sandbox token can only speak for its own project
    async with system_session() as s:
        row = (
            await s.execute(
                select(Workforce, GuardPlaybook)
                .join(GuardPlaybook, GuardPlaybook.workforce_id == Workforce.id)
                .where(
                    Workforce.org_id == org_id,
                    Workforce.project_id == member_project,
                    Workforce.name == name,
                    GuardPlaybook.org_id == org_id,
                )
            )
        ).first()
    if row is None:
        return None
    workforce, stored = row
    if not workforce.guard_enabled:
        return None
    try:
        playbook = Playbook.model_validate(stored.playbook or {})
    except ValidationError as exc:
        log.error("guard.invalid_playbook", member=name, project=str(member_project), error=str(exc)[:500])
        return InvalidPlaybook(member=name, error=str(exc)[:500])
    if not playbook.enabled:
        return None
    config = workforce.config_json or {}
    return GuardTarget(
        org_id=org_id,
        project_id=member_project,
        member=name,
        workforce_id=workforce.id,
        playbook=playbook,
        tools=tools_from_config(config),
        agent_model=_agent_model(config) if workforce.kind == "agent" else None,
    )


def is_auxiliary_call(body: dict[str, Any], target: GuardTarget) -> bool:
    """Engine-internal calls of the run (LLM-judge guardrails, memory summaries) use another model and no tools."""
    if target.agent_model is None or body.get("tools"):
        return False
    return full_model(str(body.get("model", ""))) != target.agent_model
