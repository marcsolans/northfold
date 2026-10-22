"""Git smart HTTP: clone/fetch/push against the API with real git clients, merge policy, roles and versions."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import AuditLog, Membership, Notification, Version, Workforce
from messer_common.projects_repo import ProjectRepo
from messer_runtime.testing import free_port


@dataclass
class LiveApi:
    base_url: str
    client: httpx.AsyncClient


@pytest.fixture
async def live_api() -> AsyncIterator[LiveApi]:
    from messer_api.main import create_app

    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(250):
        if server.started:
            break
        await asyncio.sleep(0.02)
    base = f"http://127.0.0.1:{port}"
    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        try:
            yield LiveApi(base_url=base, client=client)
        finally:
            server.should_exit = True
            await task


@dataclass
class Setup:
    api: LiveApi
    org_id: str
    project_id: str
    key: str
    remote: str


async def run_git(*args: str, cwd: Path, token: str | None = None, check: bool = True) -> tuple[int, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(cwd.parent),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Dev",
        "GIT_AUTHOR_EMAIL": "dev@acme.example",
        "GIT_COMMITTER_NAME": "Dev",
        "GIT_COMMITTER_EMAIL": "dev@acme.example",
    }
    if token is not None:
        basic = base64.b64encode(f"messer:{token}".encode()).decode()
        env.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader"})
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {basic}"
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "init.defaultBranch=main",
        *args,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode(errors="replace")
    if check:
        assert proc.returncode == 0, f"git {' '.join(args)} failed:\n{text}"
    return proc.returncode or 0, text


async def _setup(api: LiveApi, *, scaffold: bool = False) -> Setup:
    c = api.client
    res = await c.post("/api/v1/auth/signup", json={"email": "dev@acme.example", "password": "Contrasena123"})
    assert res.status_code == 200, res.text
    org_id = str(res.json()["org_id"])
    key = (await c.post("/api/v1/api-keys", json={"name": "cli"})).json()["key"]
    headers = {"Authorization": f"Bearer {key}"}
    if scaffold:
        res = await c.post(f"/api/v1/orgs/{org_id}/projects", json={"name": "Local"}, headers=headers)
        assert res.status_code == 201, res.text
        pid = res.json()["id"]
    else:
        pid = (await c.post("/api/v1/projects", json={"name": "Soporte"}, headers=headers)).json()["id"]
        res = await c.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"}, headers=headers)
        assert res.status_code == 201, res.text
    remote = f"{api.base_url}/api/v1/orgs/{org_id}/projects/{pid}/git"
    return Setup(api=api, org_id=org_id, project_id=str(pid), key=key, remote=remote)


AGENT = """from messer import Agent

agent = Agent(
    name="facturas",
    description="Responde dudas de facturas",
    model="anthropic/claude-haiku-5-5",
    system_prompt="Eres un asistente de facturas.",
    max_tokens=1024,
    tools=[],
)
"""


async def test_clone_push_creates_versions_and_audit(live_api: LiveApi, tmp_path: Path) -> None:
    st = await _setup(live_api)
    work = tmp_path / "work"
    await run_git("clone", "--quiet", st.remote, str(work), cwd=tmp_path, token=st.key)
    assert (work / "workforce" / "soporte" / "agent.py").is_file()
    assert (work / "messer.project.yaml").is_file()

    (work / "workforce" / "facturas").mkdir()
    (work / "workforce" / "facturas" / "__init__.py").write_text("")
    (work / "workforce" / "facturas" / "agent.py").write_text(AGENT)
    (work / "workforce" / "facturas" / "messer.yaml").write_text('_type: "agent"\nfqn: "agent.py::agent"\n')
    await run_git("add", "-A", cwd=work)
    await run_git("commit", "-q", "-m", "Add facturas agent", cwd=work)
    _, out = await run_git("push", "origin", "main", cwd=work, token=st.key)
    assert "Messer: creados: facturas" in out, out

    repo = ProjectRepo.for_project(st.project_id)
    _, local_head = await run_git("rev-parse", "HEAD", cwd=work)
    assert await repo.head() == local_head.strip()
    assert (repo.path / "workforce" / "facturas" / "agent.py").read_text() == AGENT  # working tree updated
    async with system_session() as s:
        member = (await s.execute(select(Workforce).where(Workforce.name == "facturas"))).scalar_one()
        assert (
            member.source_mode == "config" and member.config_json["system_prompt"] == "Eres un asistente de facturas."
        )
        versions = (await s.execute(select(Version).where(Version.source == "cli"))).scalars().all()
        assert {v.entity_type for v in versions} == {"workforce", "project"}
        assert all(v.author_id is not None for v in versions)
        pushed = (await s.execute(select(AuditLog).where(AuditLog.action == "git.pushed"))).scalars().all()
        assert len(pushed) == 1 and pushed[0].diff["outcome"] == "fast_forward"
        assert pushed[0].api_key_id is not None

    # The Studio sees the pushed member like any other.
    res = await live_api.client.get(f"/api/v1/projects/{st.project_id}/workforce/facturas")
    assert res.status_code == 200 and res.json()["source_mode"] == "config"


async def test_forced_push_merges_cleanly_or_is_rejected(live_api: LiveApi, tmp_path: Path) -> None:
    st = await _setup(live_api)
    work = tmp_path / "work"
    await run_git("clone", "--quiet", st.remote, str(work), cwd=tmp_path, token=st.key)
    # Messer moves on (Studio edit) while the developer commits locally.
    c = live_api.client
    cfg = (await c.get(f"/api/v1/projects/{st.project_id}/workforce/soporte")).json()["config"]
    cfg["system_prompt"] = "Cambio hecho en el Studio"
    assert (await c.put(f"/api/v1/projects/{st.project_id}/workforce/soporte/config", json=cfg)).status_code == 200
    (work / "notes.md").write_text("notas locales\n")
    await run_git("add", "-A", cwd=work)
    await run_git("commit", "-q", "-m", "Local notes", cwd=work)

    # Without force the client refuses (fetch first); with force Messer merges instead of losing its commit.
    code, out = await run_git("push", "origin", "main", cwd=work, token=st.key, check=False)
    assert code != 0 and ("fetch first" in out or "rejected" in out), out
    _, out = await run_git("push", "--force", "origin", "main", cwd=work, token=st.key)
    assert "se ha fusionado" in out, out
    repo = ProjectRepo.for_project(st.project_id)
    assert (repo.path / "notes.md").is_file()
    assert "Cambio hecho en el Studio" in (repo.path / "workforce" / "soporte" / "agent.py").read_text()
    head = await repo.head()
    _, parents = await run_git("log", "-1", "--format=%P", head, cwd=repo.path)
    assert len(parents.split()) == 2  # a merge commit

    # A conflicting forced push is refused and Messer's head does not move.
    await run_git("fetch", "--quiet", "origin", cwd=work, token=st.key)
    await run_git("reset", "--hard", "--quiet", "origin/main", cwd=work)
    agent_py = work / "workforce" / "soporte" / "agent.py"
    agent_py.write_text(agent_py.read_text().replace("Cambio hecho en el Studio", "Cambio local"))
    await run_git("commit", "-q", "-am", "Local prompt", cwd=work)
    cfg["system_prompt"] = "Otro cambio del Studio"
    assert (await c.put(f"/api/v1/projects/{st.project_id}/workforce/soporte/config", json=cfg)).status_code == 200
    studio_head = await repo.head()
    code, out = await run_git("push", "--force", "origin", "main", cwd=work, token=st.key, check=False)
    assert code != 0 and "conflicto" in out and "workforce/soporte/agent.py" in out, out
    assert await repo.head() == studio_head

    # Rewinding Messer (pushing an older commit) is refused; deleting the branch too; other branches as well.
    await run_git("reset", "--hard", "--quiet", "HEAD~1", cwd=work)
    code, out = await run_git("push", "--force", "origin", "HEAD:main", cwd=work, token=st.key, check=False)
    assert code != 0 and "git pull" in out, out
    code, out = await run_git("push", "origin", ":main", cwd=work, token=st.key, check=False)
    assert code != 0 and "no se puede borrar" in out, out
    code, out = await run_git("push", "origin", "HEAD:refs/heads/feature", cwd=work, token=st.key, check=False)
    assert code != 0 and "solo acepta pushes a la rama main" in out, out
    # Tags are accepted.
    await run_git("tag", "v1", cwd=work)
    await run_git("push", "origin", "v1", cwd=work, token=st.key)
    assert (await repo.resolve("refs/tags/v1")) == (await run_git("rev-parse", "v1", cwd=work))[1].strip()
    assert await repo.head() == studio_head


async def test_first_push_replaces_cli_scaffold(live_api: LiveApi, tmp_path: Path) -> None:
    st = await _setup(live_api, scaffold=True)
    local = tmp_path / "local"
    local.mkdir()
    await run_git("init", "-q", cwd=local)
    (local / "workforce" / "ventas").mkdir(parents=True)
    (local / "workforce" / "ventas" / "agent.py").write_text(AGENT.replace('"facturas"', '"ventas"'))
    (local / "workforce" / "ventas" / "messer.yaml").write_text(
        f'_id: "{uuid.uuid4()}"\n_type: "agent"\nfqn: "agent.py::agent"\n'
    )
    (local / "README.md").write_text("# Local\n")
    await run_git("add", "-A", cwd=local)
    await run_git("commit", "-q", "-m", "Local project", cwd=local)
    await run_git("remote", "add", "messer", st.remote, cwd=local)
    _, refs = await run_git("ls-remote", "messer", "refs/heads/main", cwd=local, token=st.key)
    scaffold = refs.split()[0]
    _, out = await run_git(
        "push",
        f"--force-with-lease=refs/heads/main:{scaffold}",
        "messer",
        "HEAD:refs/heads/main",
        cwd=local,
        token=st.key,
    )
    assert "historial importado" in out, out
    repo = ProjectRepo.for_project(st.project_id)
    assert await repo.head() == (await run_git("rev-parse", "HEAD", cwd=local))[1].strip()
    assert not (repo.path / "messer.project.yaml").exists()
    async with system_session() as s:
        names = (await s.execute(select(Workforce.name))).scalars().all()
        assert names == ["ventas"]


async def test_git_auth_roles_and_scopes(live_api: LiveApi, tmp_path: Path, make_user) -> None:  # type: ignore[no-untyped-def]
    st = await _setup(live_api)
    c = live_api.client
    # No credentials: a Basic challenge so git asks the credential helper.
    res = await c.get(f"{st.remote}/info/refs", params={"service": "git-upload-pack"})
    assert res.status_code == 401 and res.headers["www-authenticate"].startswith("Basic")
    # Dumb protocol is refused.
    auth = {"Authorization": f"Bearer {st.key}"}
    assert (await c.get(f"{st.remote}/info/refs", headers=auth)).status_code == 403
    # Another organization's credentials do not see the repository.
    other_pid = str(uuid.uuid4())
    res = await c.get(
        st.remote.replace(st.project_id, other_pid) + "/info/refs", params={"service": "git-upload-pack"}, headers=auth
    )
    assert res.status_code == 404

    # A key scoped to another project is refused; read-only scopes cannot push.
    pid2 = (await c.post("/api/v1/projects", json={"name": "Otro"})).json()["id"]
    scoped = (await c.post("/api/v1/api-keys", json={"name": "p2", "project_id": pid2})).json()["key"]
    res = await c.get(
        f"{st.remote}/info/refs", params={"service": "git-upload-pack"}, headers={"Authorization": f"Bearer {scoped}"}
    )
    assert res.status_code == 403
    reader = (await c.post("/api/v1/api-keys", json={"name": "ro", "scopes": ["projects:read"]})).json()["key"]
    work = tmp_path / "ro"
    await run_git("clone", "--quiet", st.remote, str(work), cwd=tmp_path, token=reader)
    (work / "x.md").write_text("x")
    await run_git("add", "-A", cwd=work)
    await run_git("commit", "-q", "-m", "x", cwd=work)
    code, out = await run_git("push", "origin", "main", cwd=work, token=reader, check=False)
    assert code != 0 and "403" in out, out

    # A viewer's session token fetches but cannot push.
    viewer = await make_user(email="viewer@acme.example")
    async with system_session() as s:
        s.add(Membership(org_id=uuid.UUID(st.org_id), user_id=viewer.id, role="viewer"))
    async with httpx.AsyncClient(base_url=live_api.base_url) as other:
        res = await other.post(
            "/api/v1/auth/login", json={"email": "viewer@acme.example", "password": "Sup3rSecret!pass"}
        )
        assert res.status_code == 200, res.text
        session_token = other.cookies.get("messer_at")
    assert session_token
    res = await c.get(
        f"{st.remote}/info/refs",
        params={"service": "git-upload-pack"},
        headers={"Authorization": "Basic " + base64.b64encode(f"x:{session_token}".encode()).decode()},
    )
    assert res.status_code == 200 and res.headers["content-type"] == "application/x-git-upload-pack-advertisement"
    res = await c.get(
        f"{st.remote}/info/refs",
        params={"service": "git-receive-pack"},
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert res.status_code == 403 and "builder" in res.text


async def test_push_vetting_rejects_symlinks(live_api: LiveApi, tmp_path: Path) -> None:
    st = await _setup(live_api)
    work = tmp_path / "work"
    await run_git("clone", "--quiet", st.remote, str(work), cwd=tmp_path, token=st.key)
    (work / "link").symlink_to("/etc/passwd")
    await run_git("add", "-A", cwd=work)
    await run_git("commit", "-q", "-m", "symlink", cwd=work)
    repo = ProjectRepo.for_project(st.project_id)
    before = await repo.head()
    code, out = await run_git("push", "origin", "main", cwd=work, token=st.key, check=False)
    assert code != 0 and "enlaces simbólicos" in out, out
    assert await repo.head() == before
    # Rejected objects never reach the repository (quarantine).
    _, sha = await run_git("rev-parse", "HEAD", cwd=work)
    code, _ = await run_git("cat-file", "-e", sha.strip(), cwd=repo.path, check=False)
    assert code != 0
    incoming = list((repo.path / ".git" / "objects").glob("incoming-*"))
    assert incoming == []


async def test_push_notifies_other_builders(live_api: LiveApi, tmp_path: Path, make_user) -> None:  # type: ignore[no-untyped-def]
    st = await _setup(live_api)
    builder = await make_user(email="builder@acme.example")
    async with system_session() as s:
        s.add(Membership(org_id=uuid.UUID(st.org_id), user_id=builder.id, role="builder"))
    work = tmp_path / "work"
    await run_git("clone", "--quiet", st.remote, str(work), cwd=tmp_path, token=st.key)
    readme = work / "README.md"
    readme.write_text(readme.read_text() + "\nMás detalles.\n")
    await run_git("commit", "-q", "-am", "Docs", cwd=work)
    await run_git("push", "-q", "origin", "main", cwd=work, token=st.key)
    async with system_session() as s:
        notes: list[Any] = list(
            (await s.execute(select(Notification).where(Notification.kind == "git_push"))).scalars().all()
        )
    assert [n.user_id for n in notes] == [builder.id]
