"""Deployments: evals gate, forcing (admin only), production runs use the deployed version, roll back, domains."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import Deployment, Environment, EvalRun, Interface, Membership, Notification, Project, User
from messer_common.projects_repo import ProjectRepo
from messer_runtime.testing import Harness


@pytest.fixture(autouse=True)
def no_queue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    from messer_api.services import deployments

    calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        calls.append((job, args))

    monkeypatch.setattr(deployments, "enqueue", fake_enqueue)
    return calls


async def _project(client: httpx.AsyncClient) -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": "dev@acme.example", "password": "Contrasena123"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Soporte"})).json()["id"]
    assert (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})).status_code == 201
    return str(pid)


async def _deploy(client: httpx.AsyncClient, pid: str, **body: Any) -> dict[str, Any]:
    from messer_api.services.deployments import run_pipeline

    res = await client.post(f"/api/v1/projects/{pid}/deployments", json={"environment": "production", **body})
    assert res.status_code == 202, res.text
    dep = res.json()
    await run_pipeline(uuid.UUID(dep["id"]), force=bool(body.get("force")), skip_evals=False)
    return (await client.get(f"/api/v1/deployments/{dep['id']}")).json()


async def test_deploy_with_passing_gate_serves_production(client: httpx.AsyncClient, runtime: Harness) -> None:
    pid = await _project(client)
    before = await client.post(f"/v1/projects/{pid}/workforce/soporte/run", json={"input": {"prompt": "Hola"}})
    assert before.status_code == 409
    dep = await _deploy(client, pid)
    assert dep["status"] == "live", dep["logs"]
    assert any("evals 1 correctas" in entry["message"] for entry in dep["logs"])
    async with system_session() as s:
        env = (
            await s.execute(
                select(Environment).where(Environment.project_id == uuid.UUID(pid), Environment.name == "production")
            )
        ).scalar_one()
        assert env.deployed_version_id is not None and env.status == "live" and env.url
        evals = (await s.execute(select(EvalRun).where(EvalRun.trigger == "deploy"))).scalars().all()
        assert len(evals) == 1 and evals[0].status == "passed"
    # Code changes after the deployment do not reach production until the next deployment.
    detail = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()
    cfg = detail["config"]
    cfg["system_prompt"] = "Versión nueva sin desplegar"
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    run = await client.post(f"/v1/projects/{pid}/workforce/soporte/run", json={"input": {"prompt": "Hola"}})
    assert run.status_code == 200 and run.json()["status"] == "success", run.text
    async with system_session() as s:
        from messer_common.db.models import Run

        row = await s.get(Run, uuid.UUID(run.json()["run_id"]))
        head = await ProjectRepo.for_project(pid).head()
        assert row is not None and row.environment == "production" and row.git_commit != head


async def test_failing_gate_blocks_and_only_admins_force(
    client: httpx.AsyncClient, runtime: Harness, make_user
) -> None:  # type: ignore[no-untyped-def]
    pid = await _project(client)
    repo = ProjectRepo.for_project(pid)
    await repo.write(
        {
            "workforce/soporte/evals/strict.yaml": (
                "- name: imposible\n  runnable: ../agent.py::agent\n  params:\n    prompt: Hola\n"
                '  output:\n    contains!: "CADENA-QUE-NUNCA-APARECE"\n'
            )
        },
        message="Add strict eval",
        author="t",
        email="t@x",
    )
    dep = await _deploy(client, pid)
    assert dep["status"] == "failed", dep["logs"]
    async with system_session() as s:
        notes = (await s.execute(select(Notification).where(Notification.kind == "deployment_failed"))).scalars().all()
        assert notes
        owner = (await s.execute(select(User).where(User.email == "dev@acme.example"))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == owner.id))).scalar_one()
    builder = await make_user(email="builder@acme.example")
    async with system_session() as s:
        s.add(Membership(org_id=org_id, user_id=builder.id, role="builder"))
    forced = await _deploy(client, pid, force=True)  # the owner is ≥ admin
    assert forced["status"] == "live" and forced["forced"], forced["logs"]
    await client.post("/api/v1/auth/logout")
    assert (
        await client.post("/api/v1/auth/login", json={"email": "builder@acme.example", "password": "Sup3rSecret!pass"})
    ).status_code == 200
    client.headers["X-Messer-Org"] = str(org_id)
    denied = await client.post(f"/api/v1/projects/{pid}/deployments", json={"force": True})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "force_requires_admin"


async def test_rollback_redeploys_a_previous_version(client: httpx.AsyncClient, runtime: Harness) -> None:
    from messer_api.services.deployments import run_pipeline

    pid = await _project(client)
    first = await _deploy(client, pid)
    second = await _deploy(client, pid)
    assert first["status"] == "live" and second["status"] == "live"
    history = (await client.get(f"/api/v1/projects/{pid}/deployments")).json()
    assert [d["status"] for d in history][:2] == ["live", "superseded"]
    res = await client.post(f"/api/v1/deployments/{first['id']}/rollback")
    assert res.status_code == 202, res.text
    back = await run_pipeline(uuid.UUID(res.json()["id"]), skip_evals=True)
    assert back.status == "live"
    async with system_session() as s:
        env = (
            await s.execute(
                select(Environment).where(Environment.project_id == uuid.UUID(pid), Environment.name == "production")
            )
        ).scalar_one()
        dep = await s.get(Deployment, back.id)
        assert dep is not None and env.deployed_version_id == dep.version_id
        assert str(dep.version_id) == first["version_id"]


async def test_custom_domain_verification(client: httpx.AsyncClient) -> None:
    from messer_api.routers import deployments as router_mod

    pid = await _project(client)
    res = await client.put(f"/api/v1/projects/{pid}/environments/production/domain", json={"domain": "ayuda.acme.es"})
    assert res.status_code == 200, res.text
    view = res.json()
    token = view["dns"][1]["value"]
    assert view["status"] == "pending" and view["dns"][0]["type"] == "CNAME"

    def doh(request: httpx.Request) -> httpx.Response:
        name, rtype = request.url.params["name"], request.url.params["type"]
        answers = {
            ("_messer-verify.ayuda.acme.es", "TXT"): f'"{token}"',
            ("ayuda.acme.es", "CNAME"): "cname.messer.local.",
        }
        data = answers.get((name, rtype))
        return httpx.Response(200, json={"Answer": [{"data": data}] if data else []})

    router_mod.dns_transport = httpx.MockTransport(doh)
    try:
        verified = await client.post(f"/api/v1/projects/{pid}/environments/production/domain/verify")
    finally:
        router_mod.dns_transport = None
    assert verified.status_code == 200 and verified.json()["status"] == "active", verified.text
    assert (await client.get("/api/internal/domains/allowed", params={"domain": "ayuda.acme.es"})).status_code == 200
    assert (await client.get("/api/internal/domains/allowed", params={"domain": "otro.es"})).status_code == 404
    resolved = (await client.get("/api/public/v1/domains/resolve", params={"host": "ayuda.acme.es"})).json()
    assert resolved["environment"] == "production" and resolved["project"] == "soporte"
    assert resolved["home"] is None

    # Once an interface is published, the domain root opens it.
    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(pid))
        assert project is not None
        s.add(
            Interface(
                org_id=project.org_id,
                project_id=project.id,
                name="Portal",
                kind="app",
                slug="portal",
                published_definition={"screens": []},
                published_at=datetime.now(UTC),
                public=True,
            )
        )
    resolved = (await client.get("/api/public/v1/domains/resolve", params={"host": "ayuda.acme.es"})).json()
    assert resolved["home"] == "/app/portal"
    assert (await client.get("/api/public/v1/domains/resolve", params={"host": "otro.es"})).status_code == 404
