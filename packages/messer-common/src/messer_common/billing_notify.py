"""Billing and budget notices to the people responsible for an organization (in-app + email).

Each recipient gets the notification in their own language: the email template's subject becomes the
in-app title and its first paragraph the body, so both channels always say the same thing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .db.base import new_id
from .db.models import Membership, Notification, User
from .db.models.business import BillingNotice
from .email import EmailError, send_template
from .emails import render_email
from .logging import get_logger

log = get_logger("messer.billing_notify")

ROLE_RANK = {"viewer": 1, "builder": 2, "admin": 3, "owner": 4}


@dataclass(slots=True)
class Recipient:
    user_id: uuid.UUID
    email: str
    name: str | None
    locale: str


async def org_recipients(session: AsyncSession, org_id: uuid.UUID, min_role: str = "admin") -> list[Recipient]:
    rows = (
        await session.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.org_id == org_id, User.status == "active", User.deleted_at.is_(None))
            .order_by(Membership.created_at)
        )
    ).all()
    need = ROLE_RANK[min_role]
    return [
        Recipient(user_id=u.id, email=u.email, name=u.name, locale=u.locale or "es")
        for u, role in rows
        if ROLE_RANK.get(role, 0) >= need
    ]


async def claim_notice(
    session: AsyncSession, *, org_id: uuid.UUID, kind: str, ref: str = "", payload: dict[str, Any] | None = None
) -> bool:
    """Record that a notice was delivered. Returns False when it already was (so callers skip sending)."""
    result = await session.execute(
        insert(BillingNotice)
        .values(id=new_id(), org_id=org_id, kind=kind, ref=ref, payload=payload or {})
        .on_conflict_do_nothing(constraint="uq_billing_notices_org_kind_ref")
        .returning(BillingNotice.id)
    )
    return result.first() is not None


async def notify_org(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    template: str,
    context: dict[str, Any],
    url: str,
    min_role: str = "admin",
    email: bool = True,
    recipients: list[Recipient] | None = None,
) -> int:
    """Create an in-app notification for each recipient and send the email. Returns recipients notified.

    Email failures are logged and never abort the caller's transaction (the in-app notice still lands).
    """
    people = recipients if recipients is not None else await org_recipients(session, org_id, min_role)
    for person in people:
        ctx = {"name": person.name or person.email, **context, "url": url}
        subject, _html, text = render_email(template, ctx, person.locale)
        body = text.strip().split("\n")[0] if text.strip() else ""
        session.add(
            Notification(
                id=new_id(),
                org_id=org_id,
                user_id=person.user_id,
                kind=kind,
                payload={"title": subject, "body": body, "url": _relative(url)},
                channel="in_app",
            )
        )
        if email:
            try:
                await send_template(person.email, template, ctx, person.locale)
            except EmailError as exc:
                log.error("billing_notify.email_failed", org_id=str(org_id), template=template, error=str(exc))
    return len(people)


def _relative(url: str) -> str:
    """In-app links are relative to the web origin."""
    for marker in ("/app", "/admin"):
        idx = url.find(marker)
        if idx > 0 and url[:idx].startswith("http"):
            return url[idx:]
    return url
