"""/api/v1/onboarding: guided onboarding answers and the activation checklist (contracts §6)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal, system_session

from ..deps import client_ip, get_db, require_role
from ..errors import ApiError
from ..services import onboarding as service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class StepOut(BaseModel):
    key: service.StepKey
    done: bool
    href: str


class ChecklistOut(BaseModel):
    steps: list[StepOut]
    complete: bool
    dismissed: bool


class ProjectRef(BaseModel):
    id: str
    name: str


class AgentRef(BaseModel):
    id: str
    name: str
    project_id: str


class OnboardingOut(ChecklistOut):
    goal: str | None
    use_case: service.UseCase | None
    skipped_steps: list[service.StepKey]
    completed_at: str | None
    updated_at: str | None
    project: ProjectRef | None
    agent: AgentRef | None


class OnboardingPatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    goal: str | None = Field(default=None, max_length=service.GOAL_MAX_LENGTH)
    use_case: service.UseCase | None = None
    skipped_steps: list[service.StepKey] | None = Field(default=None, max_length=len(service.STEP_KEYS))
    dismissed: bool | None = None
    completed: bool | None = None


@router.get("", response_model=OnboardingOut)
async def get_onboarding(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    return await service.onboarding_state(db, principal.org_id)


@router.patch("", response_model=OnboardingOut)
async def update_onboarding(
    body: OnboardingPatchIn,
    request: Request,
    principal: Principal = Depends(require_role("builder")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert principal.org_id is not None
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ApiError("No hay cambios que guardar", code="empty_patch")
    patch = service.build_patch(changes, actor_id=principal.user_id)
    # orgs is writable only by admins under RLS; onboarding progress is org-level state that builders also
    # complete, so the merge runs on the owner connection after the role check, filtered by the active org.
    async with system_session() as s:
        await service.apply_patch(s, org_id=principal.org_id, patch=patch, principal=principal, ip=client_ip(request))
    return await service.onboarding_state(db, principal.org_id)


@router.get("/checklist", response_model=ChecklistOut)
async def get_checklist(
    principal: Principal = Depends(require_role("viewer")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    state = await service.onboarding_state(db, principal.org_id)
    return {"steps": state["steps"], "complete": state["complete"], "dismissed": state["dismissed"]}
