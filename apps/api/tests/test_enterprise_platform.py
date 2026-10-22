"""Residency policy helpers, retention purge (scheduler task) and RLS on the enterprise tables."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from enterprise_support import app_client, login, set_plan
from sqlalchemy import select, text, update

from messer_common.db import Principal, rls_session, system_session
from messer_common.db import models as m
from messer_common.db.models.enterprise import OrgDomain, OrgIdentity, ScimGroup, ScimGroupMember
from messer_common.residency import Residency, allowed_provider, is_eu_region, model_route, org_residency
from messer_common.storage import get_storage
from messer_scheduler.tasks.retention import run_retention

STANDARD = Residency(org_id=uuid.uuid4(), mode="standard", region="eu-central-1")
STRICT = Residency(org_id=uuid.uuid4(), mode="eu_strict", region="eu-central-1")


@pytest.mark.parametrize(
    ("kind", "provider", "region", "standard", "strict"),
    [
        ("model", "anthropic", None, True, False),
        ("model", "bedrock", "eu-central-1", True, True),
        ("model", "bedrock:eu-west-1", None, True, True),
        ("model", "bedrock", "us-east-1", True, False),
        ("model", "openai", None, True, False),
        ("model", "messer", None, True, True),
        ("embeddings", "local", None, True, True),
        ("embeddings", "hash", None, True, True),
        ("embeddings", "voyage", None, True, False),
        ("embeddings", "bedrock", "eu-central-1", True, False),
        ("email", "smtp", None, True, True),
        ("email", "postmark", None, True, False),
        ("email", "resend", "eu-west-1", True, True),
        ("email", "resend", "us-east-1", True, False),
        ("voice", "browser", None, True, True),
        ("voice", "twilio:ie1", None, True, True),
        ("voice", "twilio", "us1", True, False),
        ("voice", "deepgram", None, True, False),
    ],
)
def test_allowed_provider(kind, provider, region, standard, strict) -> None:  # type: ignore[no-untyped-def]
    assert allowed_provider(STANDARD, kind, provider, region=region) is standard
    assert allowed_provider(STRICT, kind, provider, region=region) is strict


def test_region_helpers() -> None:
    assert is_eu_region("eu-south-2") and is_eu_region("ie1") and not is_eu_region("us-west-2")
    assert not is_eu_region(None)
    assert model_route(STRICT) == "bedrock" and model_route(STANDARD) == "anthropic"


async def test_org_residency_and_overview(client, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org(name="Residente")
    async with system_session() as s:
        assert (await org_residency(s, org.id)).mode == "standard"
        assert (await org_residency(s, uuid.uuid4())).strict  # unknown organizations fail closed
    await login(client, owner.email)
    res = await client.get("/api/v1/residency")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["data_residency"] == "standard" and body["eu_strict_available"] is False
    assert body["eu_strict_upgrade_to"] == "enterprise"
    assert {r["id"] for r in body["regions"]} >= {"eu-central-1", "eu-west-1"}
    model_rows = [p for p in body["providers"] if p["kind"] == "model"]
    assert model_rows and all(p["allowed_in_eu_strict"] is (p["provider"] in ("bedrock", "messer")) for p in model_rows)

    res = await client.patch("/api/v1/orgs/current", json={"data_residency": "eu_strict"})
    assert res.status_code == 402
    await set_plan(org.id, "enterprise")
    res = await client.patch(
        "/api/v1/orgs/current",
        json={
            "data_residency": "eu_strict",
            "region": "eu-west-1",
            "trace_retention_days": 30,
            "conversation_retention_days": 60,
        },
    )
    assert res.status_code == 200, res.text
    body = (await client.get("/api/v1/residency")).json()
    assert body["data_residency"] == "eu_strict" and body["model_route"] == "bedrock" and body["region"] == "eu-west-1"
    assert body["retention"] == {"trace_days": 30, "conversation_days": 60, "last_purge_at": None, "last_purge": None}
    embeddings = next(p for p in body["providers"] if p["kind"] == "embeddings")
    assert embeddings["active"] is True  # tests use the local hash embedder


async def test_retention_purges_old_traces_and_conversations(make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org(name="Retención")
    other, _ = await make_org(name="Otra")
    now = datetime.now(UTC)
    async with system_session() as s:
        await s.execute(
            update(m.Org).where(m.Org.id == org.id).values(trace_retention_days=30, conversation_retention_days=90)
        )
        project = m.Project(org_id=org.id, name="P", slug="p", repo_path="/tmp/p")
        other_project = m.Project(org_id=other.id, name="Q", slug="q", repo_path="/tmp/q")
        s.add_all([project, other_project])
        await s.flush()
        old, paused, recent, foreign = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        s.add_all(
            [
                m.Run(
                    id=old, org_id=org.id, project_id=project.id, status="success", started_at=now - timedelta(days=45)
                ),
                m.Run(
                    id=paused,
                    org_id=org.id,
                    project_id=project.id,
                    status="paused",
                    started_at=now - timedelta(days=45),
                ),
                m.Run(
                    id=recent, org_id=org.id, project_id=project.id, status="error", started_at=now - timedelta(days=5)
                ),
                m.Run(
                    id=foreign,
                    org_id=other.id,
                    project_id=other_project.id,
                    status="success",
                    started_at=now - timedelta(days=45),
                ),
            ]
        )
        await s.flush()
        s.add_all(
            [m.Span(org_id=org.id, run_id=old, call_id=f"c{i}", kind="tool", name="t", t0=i) for i in range(3)]
            + [m.Span(org_id=org.id, run_id=recent, call_id="r", kind="llm", name="l", t0=0)]
        )
        for i, age in enumerate((120, 10)):
            s.add(
                m.Conversation(
                    org_id=org.id,
                    project_id=project.id,
                    channel_key="studio",
                    workforce_name="a",
                    external_user_id=f"u{i}",
                )
            )
            await s.flush()
            await s.execute(
                text("UPDATE conversations SET updated_at = :t WHERE external_user_id = :u"),
                {"t": now - timedelta(days=age), "u": f"u{i}"},
            )
        expired = m.DataRequest(
            org_id=org.id,
            kind="export",
            status="completed",
            file_path=f"{org.id}/data-requests/x.zip",
            completed_at=now - timedelta(days=30),
        )
        s.add(expired)
    await get_storage().put(f"{org.id}/data-requests/x.zip", b"zip")

    results = await run_retention(now)
    mine = next(r for r in results if r.org_id == org.id)
    assert (mine.runs, mine.spans, mine.conversations) == (1, 3, 1)
    async with system_session() as s:
        remaining = {r.id for r in (await s.execute(select(m.Run))).scalars()}
        assert remaining == {paused, recent, foreign}  # the default 90-day retention keeps the other org's run
        assert (await s.execute(text("SELECT count(*) FROM conversations"))).scalar_one() == 1
        summary = (
            await s.execute(
                select(m.AuditLog).where(m.AuditLog.org_id == org.id, m.AuditLog.action == "retention.purged")
            )
        ).scalar_one()
        assert summary.diff["runs"] == 1 and summary.diff["spans"] == 3 and summary.diff["conversations"] == 1
        req = await s.get(m.DataRequest, expired.id)
        assert req is not None and req.status == "expired" and req.file_path is None
    assert not await get_storage().exists(f"{org.id}/data-requests/x.zip")
    # Idempotent: a second pass finds nothing for this organization.
    assert all(r.org_id != org.id for r in await run_retention(now))


async def test_enterprise_tables_are_isolated_by_rls(make_org, make_user) -> None:  # type: ignore[no-untyped-def]
    org_a, user_a = await make_org(name="A")
    org_b, user_b = await make_org(name="B")
    async with system_session() as s:
        group = ScimGroup(org_id=org_b.id, display_name="Secret group")
        s.add_all([OrgDomain(org_id=org_b.id, domain="b-corp.eu", verification_token="t"), group])
        await s.flush()
        s.add_all(
            [
                OrgIdentity(org_id=org_b.id, user_id=user_b.id, scim_managed=True, scim_user_name=user_b.email),
                ScimGroupMember(org_id=org_b.id, group_id=group.id, user_id=user_b.id),
            ]
        )
    tables = ("org_domains", "org_identities", "scim_groups", "scim_group_members")
    async with rls_session(Principal(user_id=user_a.id, org_id=org_a.id)) as s:
        for table in tables:
            n = (await s.execute(text(f"SELECT count(*) FROM {table} WHERE org_id = :b"), {"b": org_b.id})).scalar_one()
            assert n == 0, table
    async with rls_session(Principal(user_id=user_b.id, org_id=org_b.id)) as s:
        for table in tables:
            n = (await s.execute(text(f"SELECT count(*) FROM {table} WHERE org_id = :b"), {"b": org_b.id})).scalar_one()
            assert n == 1, table
    viewer = await make_user()
    async with system_session() as s:
        s.add(m.Membership(org_id=org_b.id, user_id=viewer.id, role="viewer"))
    async with rls_session(Principal(user_id=viewer.id, org_id=org_b.id)) as s:
        n = (await s.execute(text("SELECT count(*) FROM org_identities"))).scalar_one()
        assert n == 0  # admin-only tables
    async with app_client() as browser:
        await login(browser, viewer.email)
        assert (await browser.get("/api/v1/sso/connections")).status_code == 403
        assert (await browser.get("/api/v1/data-requests")).status_code == 403
        assert (await browser.get("/api/v1/data-requests/mine")).status_code == 200
