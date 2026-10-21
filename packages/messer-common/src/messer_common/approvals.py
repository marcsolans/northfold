"""Human approvals: decisions and the resume request that continues a paused run.

Used by the API (inbox, Studio chat), the worker (resume job, email links) and the scheduler (expiry).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.base import new_id
from .db.models import Approval, Run
from .roles import at_least

Decision = Literal["approve", "deny", "approve_with_changes"]


class ApprovalStateError(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def can_decide(approval: Approval, role: str | None, *, is_superadmin: bool = False) -> bool:
    return is_superadmin or at_least(role, approval.assigned_role)


def missing_required(approval: Approval, payload: dict[str, Any]) -> list[str]:
    schema = approval.input_schema or {}
    merged = {**(approval.payload or {}), **payload}
    return [k for k in schema.get("required", []) or [] if merged.get(k) in (None, "")]


async def decide(
    session: AsyncSession,
    approval: Approval,
    *,
    decision: Decision,
    user_id: uuid.UUID | None,
    via: str,
    comment: str | None = None,
    corrected_payload: dict[str, Any] | None = None,
) -> Approval:
    if approval.status != "pending":
        raise ApprovalStateError("Esta aprobación ya se decidió", "already_decided")
    now = datetime.now(UTC)
    if approval.expires_at is not None and approval.expires_at <= now and via != "expiry":
        raise ApprovalStateError("Esta aprobación ha caducado", "expired")
    if decision == "approve_with_changes":
        if not corrected_payload:
            raise ApprovalStateError("Indica los cambios a aplicar", "missing_changes")
        missing = missing_required(approval, corrected_payload)
        if missing:
            raise ApprovalStateError(f"Faltan campos obligatorios: {', '.join(missing)}", "invalid_changes")
    approval.status = "denied" if decision == "deny" else "approved"
    approval.decided_by = user_id
    approval.decided_at = now
    approval.decision_via = via
    approval.comment = comment
    approval.corrected_payload = corrected_payload if decision == "approve_with_changes" else None
    await session.flush()
    return approval


async def resume_request(session: AsyncSession, run_id: uuid.UUID) -> dict[str, Any] | None:
    """Runtime request that resumes ``run_id`` with every decided, not yet resumed approval of that run.

    Returns None when nothing is left to resume (another decision already resumed the run) or when other
    approvals of the same run are still pending (the run resumes once all of them are decided).
    """
    run = await session.get(Run, run_id)
    if run is None:
        return None
    rows = (await session.execute(select(Approval).where(Approval.run_id == run_id))).scalars().all()
    if any(a.status == "pending" for a in rows):
        return None
    ready = [a for a in rows if a.status in ("approved", "denied", "expired") and a.resume_run_id is None]
    if not ready:
        return None
    resume_run_id = new_id()
    resume: dict[str, Any] = {}
    for a in ready:
        a.resume_run_id = resume_run_id
        resolution: dict[str, Any] = {
            "approved": a.status == "approved",
            "reason": a.comment or ("Caducada sin respuesta" if a.status == "expired" else None),
            "approver_id": str(a.decided_by) if a.decided_by else None,
            "comment": a.comment,
            "decided_at": int(a.decided_at.timestamp() * 1000) if a.decided_at else None,
            "metadata": {"via": a.decision_via, "approval_id": str(a.id)},
        }
        if a.status == "approved" and a.corrected_payload:
            resolution["override_input"] = a.corrected_payload
        resume[a.engine_approval_id] = resolution
    ctx = ready[0].channel_context or {}
    await session.flush()
    return {
        "org_id": str(run.org_id),
        "project_id": str(run.project_id),
        "workforce": run.workforce_name,
        "ref": run.git_commit or "HEAD",
        "input": ctx.get("input") or run.input or {},
        "run_id": resume_run_id.hex,
        "parent_run_id": run.id.hex,
        "resume": resume,
        "environment": run.environment,
        "environment_id": str(run.environment_id) if run.environment_id else None,
        "version_id": str(run.version_id) if run.version_id else None,
        "channel": run.channel,
        "user_id": str(run.user_id) if run.user_id else None,
        "external_user_id": run.external_user_id,
        "conversation_id": str(run.conversation_id) if run.conversation_id else None,
        "trigger_id": str(run.trigger_id) if run.trigger_id else None,
    }


# ------------------------------------------------------------------------------------- email decision links

EMAIL_LINK_PURPOSE = "approval_link"


def email_link_token(approval: Approval, user_id: uuid.UUID, decision: Decision, ttl_s: int) -> str:
    """Signed per-recipient link. It is effectively single use: an approval can only be decided once."""
    from .security import sign_payload

    return sign_payload(
        {"purpose": EMAIL_LINK_PURPOSE, "approval": str(approval.id), "user": str(user_id), "decision": decision},
        ttl_s=max(ttl_s, 60),
    )


def read_email_link(token: str) -> tuple[uuid.UUID, uuid.UUID, Decision]:
    from .security import TokenError, verify_signed_payload

    try:
        claims = verify_signed_payload(token)
    except TokenError as exc:
        raise ApprovalStateError("El enlace no es válido o ha caducado", "invalid_link") from exc
    raw = claims.get("decision")
    if claims.get("purpose") != EMAIL_LINK_PURPOSE or raw not in ("approve", "deny"):
        raise ApprovalStateError("El enlace no es válido o ha caducado", "invalid_link")
    decision: Decision = "approve" if raw == "approve" else "deny"
    return uuid.UUID(str(claims["approval"])), uuid.UUID(str(claims["user"])), decision
