"""Guided onboarding (GET/PATCH /api/v1/onboarding) and the activation checklist computed from real data."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from messer_common.db import system_session
from messer_common.db.models import (
    AuditLog,
    Connection,
    Connector,
    Deployment,
    Environment,
    KbFile,
    KnowledgeBase,
    Membership,
    Org,
    Project,
    Run,
    Version,
    Workforce,
)

PASSWORD = "Sup3rSecret!pass"


async def _login(client: httpx.AsyncClient, email: str) -> None:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text


def _steps(body: dict[str, Any]) -> dict[str, bool]:
    return {s["key"]: s["done"] for s in body["steps"]}


async def _project(org_id: uuid.UUID, name: str = "Facturas") -> Project:
    async with system_session() as s:
        project = Project(org_id=org_id, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", repo_path="/tmp/p")
        s.add(project)
        await s.flush()
    return project


async def test_checklist_starts_empty(client: httpx.AsyncClient, make_org) -> None:  # type: ignore[no-untyped-def]
    _org, owner = await make_org()
    await _login(client, owner.email)
    res = await client.get("/api/v1/onboarding/checklist")
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["key"] for s in body["steps"]] == ["describe", "template", "data", "test", "deploy"]
    assert not any(s["done"] for s in body["steps"])
    assert body["complete"] is False
    assert body["dismissed"] is False
    hrefs = {s["key"]: s["href"] for s in body["steps"]}
    assert hrefs == {
        "describe": "/onboarding",
        "template": "/app/templates",
        "data": "/app/knowledge",
        "test": "/app/templates",
        "deploy": "/app/projects",
    }


async def test_checklist_follows_real_data(client: httpx.AsyncClient, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    other_org, _ = await make_org(name="Otra")
    await _login(client, owner.email)

    # Activity in another organization never counts.
    other_project = await _project(other_org.id)
    async with system_session() as s:
        s.add(Run(id=uuid.uuid4(), org_id=other_org.id, project_id=other_project.id, status="success"))
    assert not any(_steps((await client.get("/api/v1/onboarding/checklist")).json()).values())

    project = await _project(org.id)
    state = (await client.get("/api/v1/onboarding")).json()
    assert _steps(state)["template"] is True
    assert state["project"] == {"id": str(project.id), "name": "Facturas"}
    assert state["agent"] is None
    hrefs = {s["key"]: s["href"] for s in state["steps"]}
    assert hrefs["test"] == f"/app/projects/{project.id}"
    assert hrefs["deploy"] == f"/app/projects/{project.id}/deployments"

    async with system_session() as s:
        agent = Workforce(
            org_id=org.id, project_id=project.id, kind="agent", name="atencion", path="workforce/atencion"
        )
        s.add(agent)
        kb = KnowledgeBase(
            org_id=org.id,
            name="Condiciones",
            embedding_model="hash-384",
            embedding_dim=384,
            schema_name=f"kb_{uuid.uuid4().hex[:12]}",
            reader_role=f"kb_reader_{uuid.uuid4().hex[:8]}",
        )
        s.add(kb)
        await s.flush()
        s.add(
            KbFile(
                org_id=org.id, kb_id=kb.id, path="x/terms.pdf", filename="terms.pdf", mime="application/pdf", size=10
            )
        )
    state = (await client.get("/api/v1/onboarding")).json()
    assert _steps(state) == {"describe": False, "template": True, "data": True, "test": False, "deploy": False}
    assert state["agent"]["name"] == "atencion"
    assert {s["key"]: s["href"] for s in state["steps"]}["test"] == f"/app/projects/{project.id}/agents/{agent.id}"

    async with system_session() as s:
        s.add(Run(id=uuid.uuid4(), org_id=org.id, project_id=project.id, workforce_id=agent.id, status="success"))
        env = Environment(org_id=org.id, project_id=project.id, name="production")
        version = Version(
            org_id=org.id,
            project_id=project.id,
            entity_type="project",
            entity_id=project.id,
            version=1,
            git_commit="a" * 40,
        )
        s.add_all([env, version])
        await s.flush()
        s.add(
            Deployment(
                org_id=org.id, environment_id=env.id, project_id=project.id, version_id=version.id, status="failed"
            )
        )
    assert _steps((await client.get("/api/v1/onboarding/checklist")).json())["test"] is True
    assert _steps((await client.get("/api/v1/onboarding/checklist")).json())["deploy"] is False

    async with system_session() as s:
        s.add(
            Deployment(
                org_id=org.id, environment_id=env.id, project_id=project.id, version_id=version.id, status="live"
            )
        )
    res = await client.patch("/api/v1/onboarding", json={"goal": "Responder dudas sobre facturas"})
    assert res.status_code == 200, res.text
    checklist = (await client.get("/api/v1/onboarding/checklist")).json()
    assert all(_steps(checklist).values())
    assert checklist["complete"] is True


async def test_connection_counts_as_data_but_revoked_does_not(client: httpx.AsyncClient, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    await _login(client, owner.email)
    async with system_session() as s:
        await s.execute(
            insert(Connector)
            .values(key="website_test_http", name="HTTP", category="developer", auth_type="none")
            .on_conflict_do_nothing(index_elements=[Connector.key])
        )
        conn = Connection(org_id=org.id, connector_key="website_test_http", name="API interna", status="revoked")
        s.add(conn)
    assert _steps((await client.get("/api/v1/onboarding/checklist")).json())["data"] is False
    async with system_session() as s:
        row = await s.get(Connection, conn.id)
        assert row is not None
        row.status = "active"
    assert _steps((await client.get("/api/v1/onboarding/checklist")).json())["data"] is True


async def test_patch_onboarding_merges_and_audits(client: httpx.AsyncClient, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org()
    # Another writer's marker in the same JSON column must survive (e.g. trial email bookkeeping).
    async with system_session() as s:
        row = await s.get(Org, org.id)
        assert row is not None
        row.onboarding = {"trial_emails": {"day_1": "2026-10-01"}}
    await _login(client, owner.email)

    res = await client.patch(
        "/api/v1/onboarding",
        json={
            "goal": "  Clasificar facturas de proveedores  ",
            "use_case": "document_extraction",
            "skipped_steps": ["data", "data"],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["goal"] == "Clasificar facturas de proveedores"
    assert body["use_case"] == "document_extraction"
    assert body["skipped_steps"] == ["data"]
    assert _steps(body)["describe"] is True
    assert body["updated_at"] is not None

    res = await client.patch("/api/v1/onboarding", json={"dismissed": True, "completed": True})
    body = res.json()
    assert body["dismissed"] is True
    assert body["completed_at"] is not None
    assert body["goal"] == "Clasificar facturas de proveedores"  # untouched keys are kept
    assert (await client.get("/api/v1/onboarding/checklist")).json()["dismissed"] is True

    async with system_session() as s:
        stored = (await s.get(Org, org.id)).onboarding  # type: ignore[union-attr]
        audits = list(
            (
                await s.execute(
                    select(AuditLog).where(AuditLog.org_id == org.id, AuditLog.action == "onboarding.updated")
                )
            ).scalars()
        )
    assert stored["trial_emails"] == {"day_1": "2026-10-01"}
    assert stored["updated_by"] == str(owner.id)
    assert len(audits) == 2
    assert audits[0].actor_id == owner.id

    # Clearing the goal reopens step 1.
    body = (await client.patch("/api/v1/onboarding", json={"goal": ""})).json()
    assert body["goal"] is None
    assert _steps(body)["describe"] is False


async def test_patch_onboarding_validation_and_roles(client: httpx.AsyncClient, make_org, make_user) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user()
    org, owner = await make_org(members={str(viewer.id): "viewer"})
    await _login(client, owner.email)
    for body in (
        {},
        {"goal": "x" * 2001},
        {"use_case": "world_domination"},
        {"skipped_steps": ["nope"]},
        {"unknown_field": 1},
    ):
        res = await client.patch("/api/v1/onboarding", json=body)
        assert res.status_code in (400, 422), (body, res.text)

    client.cookies.clear()
    await _login(client, viewer.email)
    client.headers["X-Messer-Org"] = str(org.id)
    assert (await client.get("/api/v1/onboarding")).status_code == 200
    denied = await client.patch("/api/v1/onboarding", json={"goal": "Hola"})
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "insufficient_role"

    # Builders can complete the onboarding.
    async with system_session() as s:
        membership = (
            await s.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == viewer.id))
        ).scalar_one()
        membership.role = "builder"
    assert (await client.patch("/api/v1/onboarding", json={"goal": "Hola equipo"})).status_code == 200


async def test_onboarding_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/onboarding")).status_code == 401
    assert (await client.get("/api/v1/onboarding/checklist")).status_code == 401
    assert (await client.patch("/api/v1/onboarding", json={"goal": "x"})).status_code == 401
