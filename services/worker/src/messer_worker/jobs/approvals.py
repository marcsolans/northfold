"""Approval notifications (email with decision links) and resuming runs after a decision."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from messer_common import runtime_client
from messer_common.approvals import email_link_token
from messer_common.channels.processing import deliver_resumed_run
from messer_common.db import system_session
from messer_common.db.models import Approval, Membership, Project, User
from messer_common.email import send_template
from messer_common.logging import get_logger
from messer_common.roles import at_least
from messer_common.runtime_client import RuntimeUnavailable
from messer_common.settings import get_settings

log = get_logger("messer.worker.approvals")


async def notify_approval(_ctx: dict[str, Any], approval_id: str) -> int:
    """Email every member allowed to decide. Returns the number of emails sent."""
    web = get_settings().messer_web_url.rstrip("/")
    async with system_session() as s:
        approval = await s.get(Approval, uuid.UUID(approval_id))
        if approval is None or approval.status != "pending":
            return 0
        project = await s.get(Project, approval.project_id)
        rows = (
            await s.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.org_id == approval.org_id)
            )
        ).all()
        ttl = int((approval.expires_at - datetime.now(UTC)).total_seconds()) if approval.expires_at else 72 * 3600
        expires = approval.expires_at.strftime("%d/%m/%Y %H:%M UTC") if approval.expires_at else "—"
        recipients: list[tuple[str, str, dict[str, Any]]] = []
        for membership, user in rows:
            if not at_least(membership.role, approval.assigned_role) or user.status != "active":
                continue
            approve = email_link_token(approval, user.id, "approve", ttl)
            deny = email_link_token(approval, user.id, "deny", ttl)
            recipients.append(
                (
                    user.email,
                    user.locale or "es",
                    {
                        "title": approval.title,
                        "workforce": approval.workforce_name,
                        "project": project.name if project else "",
                        "tool": approval.tool_name,
                        "summary": approval.context_summary[:500],
                        "approve_url": f"{web}/approvals/email?token={approve}",
                        "deny_url": f"{web}/approvals/email?token={deny}",
                        "url": f"{web}/app/approvals?id={approval.id}",
                        "expires": expires,
                    },
                )
            )
    sent = 0
    for email, locale, context in recipients:
        await send_template(email, "approval_request", context, locale)
        sent += 1
    slack = await _notify_slack(uuid.UUID(approval_id), web)
    log.info("approval.notified", approval_id=approval_id, recipients=sent, slack=slack)
    return sent


async def _notify_slack(approval_id: uuid.UUID, web: str) -> str:
    """Post to the channel configured on the org's Slack connection (``config.approvals_channel``)."""
    from messer_api.services import slack_notify

    async with system_session() as s:
        approval = await s.get(Approval, approval_id)
        if approval is None:
            return "skipped:gone"
        conn = await slack_notify.slack_connection(s, approval.org_id)
        channel = str(((conn.config if conn else None) or {}).get("approvals_channel") or "").strip()
        if conn is None or not channel:
            return "skipped:not_configured"
        project = await s.get(Project, approval.project_id)
        blocks = slack_notify.approval_blocks(
            title=approval.title, workforce=approval.workforce_name, project=project.name if project else "",
            tool=approval.tool_name, summary=approval.context_summary, payload=approval.payload or {},
            url=f"{web}/app/approvals?id={approval.id}")
        return await slack_notify.post(s, conn, channel, f"Aprobación pendiente: {approval.title}", blocks)


async def resume_run(_ctx: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    """Continue a paused run with the recorded decisions (the request comes from approvals.resume_request)."""
    try:
        result = await runtime_client.run(request)
    except RuntimeUnavailable as exc:
        log.warning("approval.resume_failed", run_id=request.get("run_id"), error=str(exc))
        raise  # arq retries the job
    # Runs started from a channel (WhatsApp, Slack, …) answer the user there once resumed.
    await deliver_resumed_run(request, result)
    return {"run_id": result.get("run_id"), "status": result.get("status")}


JOBS = [notify_approval, resume_run]
