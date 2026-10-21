"""Row Level Security: organization A can never read or write organization B's data.

A complete data set is created for org B (one row in every business table). Then, on the
application role (the one every request uses), a member of org A must see zero rows of org B
in every RLS table and must fail to insert rows into org B.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, ProgrammingError

from messer_common.db import RLS_TABLES, Principal, rls_session, system_session
from messer_common.db import models as m


async def _populate(org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    async with system_session() as s:
        await s.execute(
            insert(m.Connector)
            .values(key="postgresql", name="PostgreSQL", category="database", auth_type="connection_string")
            .on_conflict_do_nothing()
        )
        project = m.Project(org_id=org_id, name="P", slug=f"p-{uuid.uuid4().hex[:6]}", repo_path="/tmp/p")
        s.add(project)
        await s.flush()
        wf = m.Workforce(org_id=org_id, project_id=project.id, kind="agent", name="a", path="workforce/a")
        s.add(wf)
        await s.flush()
        version = m.Version(
            org_id=org_id,
            project_id=project.id,
            entity_type="project",
            entity_id=project.id,
            version=1,
            git_commit="abc",
        )
        s.add(version)
        await s.flush()
        env = m.Environment(org_id=org_id, project_id=project.id, name="production")
        s.add(env)
        await s.flush()
        kb = m.KnowledgeBase(
            org_id=org_id,
            name="kb",
            embedding_model="hash",
            embedding_dim=8,
            schema_name=f"kb_{uuid.uuid4().hex[:12]}",
            reader_role="r",
        )
        s.add(kb)
        await s.flush()
        kbfile = m.KbFile(org_id=org_id, kb_id=kb.id, path="x", filename="x.pdf", mime="application/pdf", size=1)
        s.add(kbfile)
        conn = m.Connection(org_id=org_id, connector_key="postgresql", name="db")
        s.add(conn)
        sso = m.SsoConnection(org_id=org_id, type="oidc", config_encrypted="x", domain="b.example")
        s.add(sso)
        await s.flush()
        run_id = uuid.uuid4()
        s.add_all(
            [
                m.Deployment(
                    org_id=org_id, environment_id=env.id, project_id=project.id, version_id=version.id, status="live"
                ),
                m.Trigger(org_id=org_id, project_id=project.id, workforce_id=wf.id, kind="cron"),
                m.Secret(org_id=org_id, project_id=project.id, name="S", encrypted_value="x"),
                m.KbChunk(org_id=org_id, kb_id=kb.id, file_id=kbfile.id, ordinal=0, content=f"secreto de {org_id}"),
                m.KbTable(org_id=org_id, kb_id=kb.id, name="t"),
                m.KbPolicy(org_id=org_id, kb_id=kb.id, table="t", role="viewer"),
                m.KbEntity(org_id=org_id, kb_id=kb.id, entity_type="company", match_key="k", method="deterministic"),
                m.KbBackup(org_id=org_id, kb_id=kb.id, path="p"),
                m.Sync(org_id=org_id, connection_id=conn.id, kb_id=kb.id, resource="table:x"),
                m.ConnectorAgent(org_id=org_id, name="agent", enrollment_token_hash=uuid.uuid4().hex),
                m.Run(id=run_id, org_id=org_id, project_id=project.id, status="success"),
                m.Approval(org_id=org_id, project_id=project.id, run_id=run_id, engine_approval_id="ap", tool_name="t"),
                m.EvalRun(org_id=org_id, project_id=project.id),
                m.Feedback(org_id=org_id, run_id=run_id, value="up"),
                m.Interface(org_id=org_id, project_id=project.id, name="i", kind="app", slug="i"),
                m.Channel(org_id=org_id, project_id=project.id, workforce_id=wf.id, provider="whatsapp"),
                m.Conversation(
                    org_id=org_id, project_id=project.id, channel_key="c", workforce_name="a", external_user_id="u"
                ),
                m.Budget(org_id=org_id, limit_usd=Decimal("10")),
                m.ModelPolicy(org_id=org_id),
                m.ApiKey(org_id=org_id, name="k", prefix="msr_x", hashed_key=uuid.uuid4().hex),
                m.Invitation(
                    org_id=org_id,
                    email="z@b.example",
                    role="viewer",
                    token_hash=uuid.uuid4().hex,
                    expires_at=now + timedelta(days=1),
                ),
                m.SsoGroupMapping(org_id=org_id, connection_id=sso.id, external_group="g", role="viewer"),
                m.ScimToken(org_id=org_id, hashed_token=uuid.uuid4().hex),
                m.DataRequest(org_id=org_id, kind="export"),
                m.Notification(org_id=org_id, user_id=user_id, kind="test"),
                m.ComposerSession(org_id=org_id, status="done", request="r"),
                m.Alarm(org_id=org_id, name="a", metric="error_rate", threshold=1),
                m.CustomMetric(org_id=org_id, name="cm"),
                m.GuardPlaybook(org_id=org_id, project_id=project.id, workforce_id=wf.id),
                m.Invoice(org_id=org_id, stripe_invoice_id=f"in_{uuid.uuid4().hex[:8]}", status="paid"),
                m.AuditLog(org_id=org_id, actor_id=user_id, action="test"),
            ]
        )
        await s.flush()
        s.add(m.Span(org_id=org_id, run_id=run_id, call_id="c", kind="llm", name="n", t0=0))


@pytest.fixture
async def two_orgs(make_org, make_user):  # type: ignore[no-untyped-def]
    org_a, user_a = await make_org(name="Org A")
    org_b, user_b = await make_org(name="Org B")
    await _populate(org_b.id, user_b.id)
    await _populate(org_a.id, user_a.id)
    return (org_a, user_a), (org_b, user_b)


SKIP_IN_TOTALS = {"alembic_version"}


async def test_every_business_table_has_rls_enabled(migrated_database: None) -> None:
    async with system_session() as s:
        rows = (
            await s.execute(
                text(
                    "select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                    "where n.nspname = 'public' and c.relkind = 'r'"
                )
            )
        ).all()
    missing = [name for name, enabled in rows if not enabled and name not in SKIP_IN_TOTALS]
    assert missing == [], f"tables without RLS: {missing}"


async def test_org_a_cannot_read_org_b(two_orgs) -> None:  # type: ignore[no-untyped-def]
    (org_a, user_a), (org_b, user_b) = two_orgs
    tables = sorted(set(RLS_TABLES) | {"audit_log", "notifications"})
    leaks: dict[str, int] = {}
    async with rls_session(Principal(user_id=user_a.id, org_id=org_a.id)) as s:
        for table in tables:
            n = (
                await s.execute(text(f'select count(*) from public."{table}" where org_id = :b'), {"b": org_b.id})
            ).scalar_one()
            if n:
                leaks[table] = n
        org_rows = (await s.execute(text("select count(*) from orgs where id = :b"), {"b": org_b.id})).scalar_one()
        user_rows = (await s.execute(text("select count(*) from users where id = :u"), {"u": user_b.id})).scalar_one()
        chunks = (
            await s.execute(text("select count(*) from kb_chunks where content = :c"), {"c": f"secreto de {org_b.id}"})
        ).scalar_one()
    assert leaks == {}, f"org A can read org B rows: {leaks}"
    assert org_rows == 0 and user_rows == 0 and chunks == 0

    # Sanity: org B's owner sees every row seeded for it (the test is not vacuous). New tables added by
    # other areas may not be seeded by the fixture; they are still covered by the leak check above.
    async with system_session() as s:
        seeded = {
            table for table in tables
            if (await s.execute(text(f'select count(*) from public."{table}" where org_id = :b'),
                                {"b": org_b.id})).scalar_one()
        }
    async with rls_session(Principal(user_id=user_b.id, org_id=org_b.id)) as s:
        visible = {
            table for table in seeded
            if (await s.execute(text(f'select count(*) from public."{table}" where org_id = :b'),
                                {"b": org_b.id})).scalar_one()
        }
    assert len(seeded) >= 40, sorted(seeded)
    assert visible == seeded, sorted(seeded - visible)


async def test_org_a_cannot_write_into_org_b(two_orgs) -> None:  # type: ignore[no-untyped-def]
    (org_a, user_a), (org_b, _) = two_orgs
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session(Principal(user_id=user_a.id, org_id=org_a.id)) as s:
            s.add(m.Project(org_id=org_b.id, name="evil", slug="evil", repo_path="/tmp"))
            await s.flush()
    async with rls_session(Principal(user_id=user_a.id, org_id=org_a.id)) as s:
        res = await s.execute(text("update projects set name = 'pwned' where org_id = :b"), {"b": org_b.id})
        assert res.rowcount == 0
        res = await s.execute(text("delete from kb_chunks where org_id = :b"), {"b": org_b.id})
        assert res.rowcount == 0


async def test_viewer_cannot_write_and_audit_is_append_only(make_org, make_user) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user()
    org, owner = await make_org(members={str(viewer.id): "viewer"})
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session(Principal(user_id=viewer.id, org_id=org.id)) as s:
            s.add(m.Project(org_id=org.id, name="x", slug="x", repo_path="/tmp"))
            await s.flush()
    async with rls_session(Principal(user_id=owner.id, org_id=org.id)) as s:
        s.add(m.Project(org_id=org.id, name="ok", slug="ok", repo_path="/tmp"))
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session(Principal(user_id=owner.id, org_id=org.id)) as s:
            await s.execute(text("update audit_log set action = 'tampered'"))
    with pytest.raises((ProgrammingError, DBAPIError)):
        async with rls_session(Principal(user_id=owner.id, org_id=org.id)) as s:
            await s.execute(text("delete from audit_log"))


async def test_kb_search_functions_respect_org(two_orgs) -> None:  # type: ignore[no-untyped-def]
    (org_a, user_a), (org_b, _) = two_orgs
    async with system_session() as s:
        kb_b = (await s.execute(text("select id from knowledge_bases where org_id = :b"), {"b": org_b.id})).scalar_one()
    with pytest.raises(DBAPIError):
        async with rls_session(Principal(user_id=user_a.id, org_id=org_a.id)) as s:
            await s.execute(text("select * from kb_text_search(:kb, 'secreto', 5)"), {"kb": kb_b})
