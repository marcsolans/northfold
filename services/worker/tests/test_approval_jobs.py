"""Approval notifications reach only members allowed to decide, with links that do not decide by themselves."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from messer_api.services.projects import create_project
from messer_common.approvals import read_email_link
from messer_common.db import system_session
from messer_common.db.models import Approval, Membership
from messer_common.email import ConsoleEmailAdapter
from messer_common.testing.fixtures import principal_for
from messer_worker.jobs.approvals import notify_approval


async def test_notify_approval_emails_eligible_members(make_org, make_user) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    viewer = await make_user(email="viewer@example.com")
    admin = await make_user(email="admin@example.com")
    async with system_session() as s:
        s.add(Membership(org_id=org.id, user_id=viewer.id, role="viewer"))
        s.add(Membership(org_id=org.id, user_id=admin.id, role="admin"))
        project = await create_project(s, principal_for(owner.id, org.id, "owner"), name="Pagos")
        approval = Approval(
            org_id=org.id,
            project_id=project.id,
            run_id=uuid.uuid4(),
            engine_approval_id="ap1",
            workforce_name="pagos",
            tool_name="send_email",
            title="Enviar factura",
            payload={"to": "x@example.com"},
            assigned_role="admin",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )
        s.add(approval)
        await s.flush()
        approval_id = approval.id
    ConsoleEmailAdapter.sent.clear()
    sent = await notify_approval({}, str(approval_id))
    recipients = sorted(m.to for m in ConsoleEmailAdapter.sent)
    assert sent == 2 and recipients == sorted([owner.email, "admin@example.com"])
    html = ConsoleEmailAdapter.sent[0].html
    token = html.split("/approvals/email?token=")[1].split('"')[0]
    linked_id, _, decision = read_email_link(token)
    assert linked_id == approval_id and decision == "approve"
    async with system_session() as s:
        row = await s.get(Approval, approval_id)
        assert row is not None and row.status == "pending"  # sending links never decides


async def test_notify_approval_posts_to_slack_when_configured(make_org, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services import slack_notify
    from messer_common.db.models import Connection

    org, owner = await make_org()
    posted: list[tuple[str, str, list[dict[str, object]] | None]] = []

    async def fake_post(session, conn, channel, text, blocks=None):  # type: ignore[no-untyped-def]
        posted.append((channel, text, blocks))
        return "demo"

    monkeypatch.setattr(slack_notify, "post", fake_post)
    async with system_session() as s:
        project = await create_project(s, principal_for(owner.id, org.id, "owner"), name="Abonos")
        s.add(Connection(org_id=org.id, connector_key="slack", name="Slack", status="demo", demo=True,
                         config={"approvals_channel": "#aprobaciones"}))
        approval = Approval(org_id=org.id, project_id=project.id, run_id=uuid.uuid4(), engine_approval_id="ap2",
                            workforce_name="abonos", tool_name="crear_abono", title="Abono de 900 €",
                            payload={"importe": 900, "cliente": "Acme"}, assigned_role="admin",
                            expires_at=datetime.now(UTC) + timedelta(hours=72))
        s.add(approval)
        await s.flush()
        approval_id = approval.id
    await notify_approval({}, str(approval_id))
    assert len(posted) == 1
    channel, text, blocks = posted[0]
    assert channel == "#aprobaciones" and "Abono de 900 €" in text
    assert blocks is not None and any(b.get("type") == "actions" for b in blocks)
