"""Post platform notifications (approvals, alarms) to Slack through the organization's Slack connection."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import Connection
from messer_common.logging import get_logger

log = get_logger("messer.slack_notify")

SLACK_TIMEOUT_S = 10


async def slack_connection(session: AsyncSession, org_id: uuid.UUID) -> Connection | None:
    """The organization's Slack connection (a real one is preferred over a demo one)."""
    return (
        await session.execute(
            select(Connection)
            .where(Connection.org_id == org_id, Connection.connector_key == "slack",
                   Connection.status.in_(("active", "demo")))
            .order_by(Connection.demo.asc(), Connection.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def post(session: AsyncSession, conn: Connection, channel: str, text: str,
               blocks: list[dict[str, Any]] | None = None) -> str:
    """Returns ``posted``, ``demo`` or ``failed:<code>`` / ``skipped:<reason>``."""
    try:
        from messer_connectors.base import ConnectorError
        from messer_connectors.credentials import load_context
        from messer_connectors.registry import get_adapter
    except ImportError:
        return "skipped:connectors_unavailable"
    args: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        args["blocks"] = blocks
    try:
        ctx = await load_context(session, conn.id)
        await asyncio.wait_for(get_adapter("slack").run_action(ctx, "post_message", args), timeout=SLACK_TIMEOUT_S)
    except ConnectorError as exc:
        log.warning("slack.post_failed", connection_id=str(conn.id), code=exc.code, error=exc.message)
        return f"failed:{exc.code}"
    except TimeoutError:
        return "failed:timeout"
    return "demo" if conn.demo else "posted"


def approval_blocks(*, title: str, workforce: str, project: str, tool: str, summary: str, url: str,
                    payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [{"type": "mrkdwn", "text": f"*{k}*\n{str(v)[:200]}"} for k, v in list(payload.items())[:8]]
    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Aprobación pendiente: {title}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn",
                                     "text": f"*{workforce}* necesita aprobación en *{project}* para `{tool}`."}},
    ]
    if fields:
        blocks.append({"type": "section", "fields": fields})
    if summary:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": summary[:500]}]})
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "Revisar y decidir"}, "url": url,
         "style": "primary"},
    ]})
    return blocks
