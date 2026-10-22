"""Guided onboarding state (``orgs.onboarding``) and the activation checklist (contracts §6).

The checklist is computed from real data only:

* ``describe`` — the organization wrote what it wants to solve (onboarding step 1) or used the Composer.
* ``template`` — a project exists (cloned from a template or built by the Composer).
* ``data``     — a knowledge-base file was uploaded or a connection was created.
* ``test``     — at least one run was executed.
* ``deploy``   — a deployment went live.

The wizard's own keys are merged into ``orgs.onboarding`` atomically (``jsonb ||``) so other writers of the same
column (e.g. trial-email markers) are never overwritten.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast, get_args

from sqlalchemy import exists, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import (
    ComposerSession,
    Connection,
    Deployment,
    KbFile,
    Org,
    Project,
    Run,
    Workforce,
)

StepKey = Literal["describe", "template", "data", "test", "deploy"]
STEP_KEYS: tuple[StepKey, ...] = cast(tuple[StepKey, ...], get_args(StepKey))
# Steps of the 4-step guided onboarding (the checklist adds "deploy").
WIZARD_STEPS: tuple[StepKey, ...] = ("describe", "template", "data", "test")
UseCase = Literal[
    "customer_support",
    "lead_qualification",
    "document_extraction",
    "internal_assistant",
    "contract_analysis",
    "operations",
    "voice_reception",
    "reporting",
    "other",
]
USE_CASES: tuple[str, ...] = get_args(UseCase)
GOAL_MAX_LENGTH = 2000
LIVE_DEPLOYMENT_STATUSES = ("live", "superseded")


@dataclass(slots=True)
class LatestProject:
    id: uuid.UUID
    name: str


@dataclass(slots=True)
class LatestAgent:
    id: uuid.UUID
    name: str
    project_id: uuid.UUID


async def _exists(session: AsyncSession, stmt: Any) -> bool:
    return bool((await session.execute(select(exists(stmt)))).scalar())


async def latest_project(session: AsyncSession, org_id: uuid.UUID) -> LatestProject | None:
    row = (
        await session.execute(
            select(Project.id, Project.name)
            .where(Project.org_id == org_id, Project.archived_at.is_(None))
            .order_by(Project.created_at.desc())
            .limit(1)
        )
    ).first()
    return LatestProject(id=row[0], name=row[1]) if row else None


async def latest_agent(session: AsyncSession, org_id: uuid.UUID) -> LatestAgent | None:
    row = (
        await session.execute(
            select(Workforce.id, Workforce.name, Workforce.project_id)
            .join(Project, Project.id == Workforce.project_id)
            .where(Workforce.org_id == org_id, Workforce.kind == "agent", Project.archived_at.is_(None))
            .order_by(Workforce.created_at.desc())
            .limit(1)
        )
    ).first()
    return LatestAgent(id=row[0], name=row[1], project_id=row[2]) if row else None


def _goal(onboarding: dict[str, Any]) -> str | None:
    value = onboarding.get("goal")
    if not isinstance(value, str):
        return None
    return value.strip() or None


async def _checklist(
    session: AsyncSession,
    org_id: uuid.UUID,
    onboarding: dict[str, Any],
    project: LatestProject | None,
    agent: LatestAgent | None,
) -> dict[str, Any]:
    described = _goal(onboarding) is not None or await _exists(
        session, select(ComposerSession.id).where(ComposerSession.org_id == org_id)
    )
    has_project = project is not None
    has_data = await _exists(session, select(KbFile.id).where(KbFile.org_id == org_id)) or await _exists(
        session, select(Connection.id).where(Connection.org_id == org_id, Connection.status != "revoked")
    )
    tested = await _exists(session, select(Run.id).where(Run.org_id == org_id))
    deployed = await _exists(
        session,
        select(Deployment.id).where(Deployment.org_id == org_id, Deployment.status.in_(LIVE_DEPLOYMENT_STATUSES)),
    )

    if agent is not None:
        test_href = f"/app/projects/{agent.project_id}/agents/{agent.id}"
    elif project is not None:
        test_href = f"/app/projects/{project.id}"
    else:
        test_href = "/app/templates"
    deploy_href = f"/app/projects/{project.id}/deployments" if project is not None else "/app/projects"

    steps = [
        {"key": "describe", "done": described, "href": "/onboarding"},
        {"key": "template", "done": has_project, "href": "/app/templates"},
        {"key": "data", "done": has_data, "href": "/app/knowledge"},
        {"key": "test", "done": tested, "href": test_href},
        {"key": "deploy", "done": deployed, "href": deploy_href},
    ]
    return {
        "steps": steps,
        "complete": all(s["done"] for s in steps),
        "dismissed": bool(onboarding.get("dismissed_at")),
    }


async def compute_checklist(session: AsyncSession, org_id: uuid.UUID, onboarding: dict[str, Any]) -> dict[str, Any]:
    """Activation checklist for an organization (works on RLS and system sessions; always filters by org)."""
    project = await latest_project(session, org_id)
    agent = await latest_agent(session, org_id)
    return await _checklist(session, org_id, onboarding, project, agent)


async def onboarding_state(session: AsyncSession, org_id: uuid.UUID) -> dict[str, Any]:
    """Wizard answers + checklist + the latest project/agent the wizard links to."""
    org = await session.get(Org, org_id)
    onboarding: dict[str, Any] = dict(org.onboarding or {}) if org is not None else {}
    project = await latest_project(session, org_id)
    agent = await latest_agent(session, org_id)
    checklist = await _checklist(session, org_id, onboarding, project, agent)
    use_case = onboarding.get("use_case")
    skipped = [s for s in onboarding.get("skipped_steps") or [] if s in STEP_KEYS]
    return {
        "goal": _goal(onboarding),
        "use_case": use_case if use_case in USE_CASES else None,
        "skipped_steps": skipped,
        "dismissed": bool(onboarding.get("dismissed_at")),
        "completed_at": onboarding.get("wizard_completed_at"),
        "updated_at": onboarding.get("updated_at"),
        "project": {"id": str(project.id), "name": project.name} if project else None,
        "agent": {"id": str(agent.id), "name": agent.name, "project_id": str(agent.project_id)} if agent else None,
        **checklist,
    }


def build_patch(changes: dict[str, Any], *, actor_id: uuid.UUID | None, now: datetime | None = None) -> dict[str, Any]:
    """Translate validated API fields into the JSON keys stored in ``orgs.onboarding``."""
    now = now or datetime.now(UTC)
    patch: dict[str, Any] = {}
    if "goal" in changes:
        goal = (changes["goal"] or "").strip()
        patch["goal"] = goal[:GOAL_MAX_LENGTH] or None
    if "use_case" in changes:
        patch["use_case"] = changes["use_case"]
    if "skipped_steps" in changes:
        seen: list[str] = []
        for step in changes["skipped_steps"] or []:
            if step in STEP_KEYS and step not in seen:
                seen.append(step)
        patch["skipped_steps"] = seen
    if "dismissed" in changes and changes["dismissed"] is not None:
        patch["dismissed_at"] = now.isoformat() if changes["dismissed"] else None
    if "completed" in changes and changes["completed"] is not None:
        patch["wizard_completed_at"] = now.isoformat() if changes["completed"] else None
    if patch:
        patch["updated_at"] = now.isoformat()
        patch["updated_by"] = str(actor_id) if actor_id else None
    return patch


async def apply_patch(
    session: AsyncSession, *, org_id: uuid.UUID, patch: dict[str, Any], principal: Principal, ip: str | None
) -> None:
    """Merge ``patch`` into ``orgs.onboarding`` (owner connection, filtered by org) and audit it."""
    if not patch:
        return
    await session.execute(
        text(
            "UPDATE public.orgs SET onboarding = coalesce(onboarding, '{}'::jsonb) || CAST(:patch AS jsonb) WHERE id = :org_id"
        ),
        {"patch": json.dumps(patch), "org_id": org_id},
    )
    await audit.record(
        session,
        action="onboarding.updated",
        principal=principal,
        org_id=org_id,
        entity_type="org",
        entity_id=org_id,
        diff={k: v for k, v in patch.items() if k not in ("updated_at", "updated_by")},
        ip=ip,
    )
