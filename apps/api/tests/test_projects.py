"""Projects are git repositories; agents are code generated from Studio config (and parsed back)."""

from __future__ import annotations

import httpx

from messer_common.projects_repo import ProjectRepo


async def _signup(client: httpx.AsyncClient, email: str = "builder@example.com") -> None:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "B"})
    assert res.status_code == 200, res.text


async def test_project_and_agent_lifecycle(client: httpx.AsyncClient) -> None:
    await _signup(client)
    created = await client.post("/api/v1/projects", json={"name": "Soporte facturas", "description": "Atención"})
    assert created.status_code == 201, created.text
    project = created.json()
    pid = project["id"]
    assert project["slug"] == "soporte-facturas"

    repo = ProjectRepo.for_project(pid)
    files = await repo.list_files()
    assert "messer.project.yaml" in files and "knowledge.yaml" in files and "triggers.yaml" in files

    agent = await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte", "description": "Dudas"})
    assert agent.status_code == 201, agent.text
    detail = agent.json()
    assert detail["source_mode"] == "config"
    assert "agent = Agent(" in detail["code"]
    assert "workforce/soporte/agent.py" in await repo.list_files()

    cfg = detail["config"]
    cfg["system_prompt"] = "Eres el asistente de facturas de Acme."
    cfg["temperature"] = 0.2
    cfg["tools"].append({"type": "builtin", "key": "calculator"})
    updated = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)
    assert updated.status_code == 200, updated.text
    assert "Eres el asistente de facturas de Acme." in updated.json()["code"]
    assert "calculator()" in updated.json()["code"]

    v1 = await client.post(f"/api/v1/projects/{pid}/workforce/soporte/versions", json={"message": "Primera"})
    assert v1.status_code == 201 and v1.json()["version"] == 1

    # Code edits that keep the generated shape sync back into the config.
    code = updated.json()["code"].replace("Acme.", "Acme. Responde en español.")
    edited = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/code", json={"code": code})
    assert edited.status_code == 200
    assert edited.json()["source_mode"] == "config"
    assert edited.json()["config"]["system_prompt"].endswith("Responde en español.")

    # Free-form code switches to code mode (code wins).
    custom = code + "\n\ndef helper() -> str:\n    return 'x'\n"
    custom_res = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/code", json={"code": custom})
    assert custom_res.json()["source_mode"] == "code"

    bad = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/code", json={"code": "agent = ("})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "syntax_error"

    diff = await client.get(f"/api/v1/projects/{pid}/workforce/soporte/versions/1/diff")
    assert "def helper" in diff.json()["diff"]

    restored = await client.post(f"/api/v1/projects/{pid}/workforce/soporte/versions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["source_mode"] == "config"
    assert "def helper" not in restored.json()["code"]

    commits = (await client.get(f"/api/v1/projects/{pid}/commits")).json()
    assert len(commits) >= 5

    listed = (await client.get("/api/v1/projects")).json()
    assert listed[0]["agents"] == 1


async def test_project_limit_and_viewer_readonly(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_common.db import system_session
    from messer_common.db.models import Plan, Subscription
    from sqlalchemy import update

    await _signup(client, "limits@example.com")
    me = (await client.get("/api/v1/me")).json()
    async with system_session() as s:
        await s.execute(update(Subscription).where(Subscription.org_id == me["active_org"]["id"]).values(plan_id="starter"))
        from messer_common.db.models import Org

        await s.execute(update(Org).where(Org.id == me["active_org"]["id"]).values(plan_id="starter"))
        assert (await s.get(Plan, "starter")) is not None
    assert (await client.post("/api/v1/projects", json={"name": "Uno"})).status_code == 201
    second = await client.post("/api/v1/projects", json={"name": "Dos"})
    assert second.status_code == 402
    assert second.json()["error"]["code"] == "plan_limit"


async def test_archive_endpoint_requires_service_token(client: httpx.AsyncClient) -> None:
    await _signup(client, "arch@example.com")
    pid = (await client.post("/api/v1/projects", json={"name": "Arch"})).json()["id"]
    denied = await client.get(f"/internal/v1/projects/{pid}/archive")
    assert denied.status_code == 401
    from messer_common.settings import get_settings

    ok = await client.get(f"/internal/v1/projects/{pid}/archive",
                          headers={"Authorization": f"Bearer {get_settings().service_token}"})
    assert ok.status_code == 200
    assert ok.headers["x-messer-commit"]
    assert ok.content[:2] == b"\x1f\x8b"
