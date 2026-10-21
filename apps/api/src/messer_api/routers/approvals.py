"""/api/v1/approvals — human-in-the-loop decisions that resume paused runs."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.approvals import ApprovalStateError, Decision, can_decide, decide, read_email_link, resume_request
from messer_common.db import Principal, rls_session, system_session
from messer_common.db.models import Approval, Membership, Project, User
from messer_common.queue import Jobs, enqueue

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, Forbidden, NotFound
from .studio import relay_run, sse, stream_response

router = APIRouter(prefix="/approvals", tags=["approvals"])


class ApprovalOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str | None
    run_id: uuid.UUID
    workforce_name: str
    tool_name: str
    title: str
    payload: dict[str, Any]
    input_schema: dict[str, Any] | None
    context_summary: str
    assigned_role: str
    status: str
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    decision_via: str | None
    comment: str | None
    corrected_payload: dict[str, Any] | None
    expires_at: datetime | None
    expiry_action: str
    resume_run_id: uuid.UUID | None
    environment: str
    channel: str | None
    created_at: datetime
    can_decide: bool


def _out(a: Approval, principal: Principal, names: dict[uuid.UUID, str]) -> ApprovalOut:
    return ApprovalOut(
        id=a.id,
        project_id=a.project_id,
        project_name=names.get(a.project_id),
        run_id=a.run_id,
        workforce_name=a.workforce_name,
        tool_name=a.tool_name,
        title=a.title,
        payload=a.payload or {},
        input_schema=a.input_schema,
        context_summary=a.context_summary,
        assigned_role=a.assigned_role,
        status=a.status,
        decided_by=a.decided_by,
        decided_at=a.decided_at,
        decision_via=a.decision_via,
        comment=a.comment,
        corrected_payload=a.corrected_payload,
        expires_at=a.expires_at,
        expiry_action=a.expiry_action,
        resume_run_id=a.resume_run_id,
        environment=a.environment,
        channel=(a.channel_context or {}).get("channel"),
        created_at=a.created_at,
        can_decide=a.status == "pending" and can_decide(a, principal.role, is_superadmin=principal.is_superadmin),
    )


async def _names(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {p.id: p.name for p in (await session.execute(select(Project).where(Project.id.in_(ids)))).scalars()}


class ApprovalPage(BaseModel):
    items: list[ApprovalOut]
    pending: int


@router.get("", response_model=ApprovalPage)
async def list_approvals(
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
    status: str | None = Query(default="pending", description="pending|approved|denied|expired|all"),
    project_id: uuid.UUID | None = None,
    mine: bool = Query(default=False, description="only approvals the caller can decide"),
    limit: int = Query(default=100, ge=1, le=500),
) -> ApprovalPage:
    q = select(Approval).where(Approval.org_id == principal.org_id)
    if principal.project_id is not None:
        q = q.where(Approval.project_id == principal.project_id)
    if project_id is not None:
        q = q.where(Approval.project_id == project_id)
    if status and status != "all":
        q = q.where(Approval.status.in_(status.split(",")))
    rows = (await session.execute(q.order_by(Approval.created_at.desc()).limit(limit))).scalars().all()
    names = await _names(session, {a.project_id for a in rows})
    items = [_out(a, principal, names) for a in rows]
    if mine:
        items = [i for i in items if i.can_decide]
    pending = (
        await session.execute(
            select(func.count())
            .select_from(Approval)
            .where(Approval.org_id == principal.org_id, Approval.status == "pending")
        )
    ).scalar_one()
    return ApprovalPage(items=items, pending=int(pending))


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(
    approval_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> ApprovalOut:
    a = await session.get(Approval, approval_id)
    if a is None or a.org_id != principal.org_id:
        raise NotFound("Aprobación no encontrada")
    ensure_project_access(principal, a.project_id)
    return _out(a, principal, await _names(session, {a.project_id}))


class DecisionIn(BaseModel):
    decision: Literal["approve", "deny", "approve_with_changes"]
    comment: str | None = Field(default=None, max_length=4000)
    payload: dict[str, Any] | None = None


@router.post("/{approval_id}/decision", response_model=None)
async def decide_approval(
    approval_id: uuid.UUID,
    body: DecisionIn,
    principal: Principal = Depends(require_role("viewer")),
    stream: bool = Query(default=False, description="stream the resumed run as SSE (Studio chat)"),
) -> ApprovalOut | StreamingResponse:
    """Approve, deny or approve with changes. The paused run resumes once every approval of it is decided."""
    async with rls_session(principal) as session:
        visible = await session.get(Approval, approval_id)
        if visible is None or visible.org_id != principal.org_id:
            raise NotFound("Aprobación no encontrada")
        ensure_project_access(principal, visible.project_id)
        if not can_decide(visible, principal.role, is_superadmin=principal.is_superadmin):
            raise Forbidden(
                f"Esta aprobación requiere el rol {visible.assigned_role} o superior",
                code="insufficient_role",
                details={"required": visible.assigned_role},
            )
    # Approvers may hold any role the approval asks for (even viewer), so the write uses the owner connection
    # after the RLS-scoped read and role check above.
    async with system_session() as session:
        a = await session.get(Approval, approval_id, with_for_update=True)
        assert a is not None
        try:
            await decide(
                session,
                a,
                decision=body.decision,
                user_id=principal.user_id,
                via="app",
                comment=body.comment,
                corrected_payload=body.payload,
            )
        except ApprovalStateError as exc:
            raise ApiError(exc.message, code=exc.code, status_code=409) from exc
        await audit.record(
            session,
            action=f"approval.{a.status}",
            principal=principal,
            entity_type="approval",
            entity_id=a.id,
            diff={"tool": a.tool_name, "decision": body.decision, "changes": body.payload, "comment": body.comment},
        )
        resume = await resume_request(session, a.run_id)
        out = _out(a, principal, await _names(session, {a.project_id}))
    if resume is None:
        if stream:
            return stream_response(
                _single(
                    {
                        "type": "APPROVAL_RECORDED",
                        "approval": out.model_dump(mode="json"),
                        "waiting_for_other_approvals": True,
                    }
                )
            )
        return out
    if stream:
        return stream_response(
            relay_run(
                resume,
                {
                    "type": "APPROVAL_RECORDED",
                    "approval": out.model_dump(mode="json"),
                    "resume_run_id": resume["run_id"],
                },
            )
        )
    await enqueue(Jobs.RESUME_RUN, resume, _job_id=f"resume:{resume['run_id']}")
    return out


async def _single(event: dict[str, Any]) -> AsyncIterator[str]:
    yield sse(event)


# ------------------------------------------------------------------------- email links (no session needed)

public_router = APIRouter(prefix="/api/v1/approval-links", tags=["approvals"])


class LinkOut(BaseModel):
    approval_id: uuid.UUID
    decision: str
    title: str
    workforce_name: str
    tool_name: str
    payload: dict[str, Any]
    project_name: str | None
    status: str
    expires_at: datetime | None


async def _link_target(session: AsyncSession, token: str) -> tuple[Approval, User, Membership, Decision]:
    try:
        approval_id, user_id, decision = read_email_link(token)
    except ApprovalStateError as exc:
        raise ApiError(exc.message, code=exc.code, status_code=400) from exc
    approval = await session.get(Approval, approval_id)
    user = await session.get(User, user_id)
    if approval is None or user is None:
        raise NotFound("Aprobación no encontrada")
    membership = (
        await session.execute(
            select(Membership).where(Membership.org_id == approval.org_id, Membership.user_id == user_id)
        )
    ).scalar_one_or_none()
    if membership is None or not can_decide(approval, membership.role):
        raise Forbidden("Ya no tienes permiso para decidir esta aprobación", code="insufficient_role")
    return approval, user, membership, decision


@public_router.get("", response_model=LinkOut)
async def read_link(token: str) -> LinkOut:
    """What an email link would decide. Opening the link never decides: the page asks to confirm (POST)."""
    async with system_session() as session:
        approval, _, _, decision = await _link_target(session, token)
        names = await _names(session, {approval.project_id})
        return LinkOut(
            approval_id=approval.id,
            decision=decision,
            title=approval.title,
            workforce_name=approval.workforce_name,
            tool_name=approval.tool_name,
            payload=approval.payload or {},
            project_name=names.get(approval.project_id),
            status=approval.status,
            expires_at=approval.expires_at,
        )


class LinkDecisionIn(BaseModel):
    token: str
    comment: str | None = Field(default=None, max_length=4000)


@public_router.post("")
async def decide_by_link(body: LinkDecisionIn) -> dict[str, Any]:
    async with system_session() as session:
        approval, user, membership, decision = await _link_target(session, body.token)
        locked = await session.get(Approval, approval.id, with_for_update=True)
        assert locked is not None
        try:
            await decide(
                session,
                locked,
                decision=decision,
                user_id=user.id,
                via="email",
                comment=body.comment,
            )
        except ApprovalStateError as exc:
            raise ApiError(exc.message, code=exc.code, status_code=409) from exc
        actor = Principal(user_id=user.id, org_id=locked.org_id, role=membership.role, email=user.email)
        await audit.record(
            session,
            action=f"approval.{locked.status}",
            principal=actor,
            entity_type="approval",
            entity_id=locked.id,
            diff={"tool": locked.tool_name, "via": "email"},
        )
        resume = await resume_request(session, locked.run_id)
        status = locked.status
    if resume is not None:
        await enqueue(Jobs.RESUME_RUN, resume, _job_id=f"resume:{resume['run_id']}")
    return {"approval_id": str(approval.id), "status": status, "resumed": resume is not None}
