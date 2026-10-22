"""GitHub sync: connect (PAT and App), push after Messer commits, webhook → pull with member sync and versions,
merges where Messer wins on conflicts, incoming-tree vetting, permissions and disconnect.

No network: git talks to local bare repositories (``MESSER_GITHUB_GIT_URL=file://…``) and the REST API is an
``httpx.MockTransport``.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from messer_api.services import github as svc
from messer_common import github as gh
from messer_common.db import system_session
from messer_common.db.models import AuditLog, Notification, Project, Version, Workforce
from messer_common.projects_repo import ProjectRepo
from messer_common.security import decrypt
from messer_common.studio.agent_spec import default_agent_config, render_agent_code
from messer_common.studio.project_files import member_manifest

PASSWORD = "Sup3rSecret!pass"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
    "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
        check=False,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


class FakeGitHub:
    """Minimal GitHub REST API."""

    def __init__(self, *, hooks_allowed: bool = True, public_key: Any = None) -> None:
        self.hooks_allowed = hooks_allowed
        self.public_key = public_key
        self.calls: list[tuple[str, str]] = []
        self.hooks: dict[int, dict[str, Any]] = {}
        self.installation_tokens = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        auth = request.headers.get("authorization", "")
        if path.startswith("/app/") or path.endswith("/installation"):
            claims = jwt.decode(auth.removeprefix("Bearer "), self.public_key, algorithms=["RS256"])
            assert claims["iss"] == "12345"
            if path.endswith("/installation"):
                return httpx.Response(200, json={"id": 42})
            self.installation_tokens += 1
            return httpx.Response(201, json={"token": "ghs_installation", "expires_at": "2099-01-01T00:00:00Z"})
        if auth not in ("Bearer github_pat_valid", "Bearer ghs_installation"):
            return httpx.Response(401, json={"message": "Bad credentials"})
        if request.method == "GET" and path == "/repos/acme/soporte":
            perms = {"push": True} if auth.endswith("valid") else {}
            return httpx.Response(
                200, json={"full_name": "acme/soporte", "default_branch": "main", "permissions": perms}
            )
        if request.method == "GET" and path.startswith("/repos/"):
            return httpx.Response(404, json={"message": "Not Found"})
        if request.method == "POST" and path == "/repos/acme/soporte/hooks":
            if not self.hooks_allowed:
                return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
            body = json.loads(request.content)
            hook_id = 900 + len(self.hooks)
            self.hooks[hook_id] = body
            return httpx.Response(201, json={"id": hook_id})
        if request.method == "DELETE" and path.startswith("/repos/acme/soporte/hooks/"):
            self.hooks.pop(int(path.rsplit("/", 1)[1]), None)
            return httpx.Response(204)
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def remotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    root = tmp_path / "github"
    bare = root / "acme" / "soporte.git"
    bare.mkdir(parents=True)
    git(bare, "init", "--bare", "-q", "-b", "main")
    monkeypatch.setenv("MESSER_GITHUB_GIT_URL", f"file://{root}")
    for var in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY", "GITHUB_WEBHOOK_SECRET", "GITHUB_APP_SLUG"):
        monkeypatch.setenv(var, "")
    gh.reset_github_settings()
    yield bare
    gh.api_transport = None
    gh.reset_github_settings()


@pytest.fixture
def fake_github(remotes: Path) -> FakeGitHub:
    fake = FakeGitHub()
    gh.api_transport = httpx.MockTransport(fake)
    return fake


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Record sync jobs instead of queueing them (tests run the sync directly)."""
    calls: list[tuple[str, str]] = []

    async def fake_enqueue(project_id: uuid.UUID | str, *, reason: str, after: str | None = None) -> str:
        calls.append((str(project_id), reason))
        return f"job-{len(calls)}"

    monkeypatch.setattr(svc, "enqueue_sync", fake_enqueue)
    return calls


async def _signup(client: httpx.AsyncClient, email: str = "owner@example.com") -> None:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "O"})
    assert res.status_code == 200, res.text


async def _project_with_agent(client: httpx.AsyncClient) -> str:
    created = await client.post("/api/v1/projects", json={"name": "Soporte", "description": "Atención"})
    assert created.status_code == 201, created.text
    pid = str(created.json()["id"])
    agent = await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte", "description": "Dudas"})
    assert agent.status_code == 201, agent.text
    return pid


async def _project(pid: str) -> Project:
    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(pid))
        assert project is not None
        s.expunge(project)
        return project


def _webhook(body: dict[str, Any], secret: str, event: str = "push") -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    return raw, {
        "X-GitHub-Event": event,
        "X-Hub-Signature-256": gh.sign(secret, raw),
        "X-GitHub-Delivery": uuid.uuid4().hex,
        "Content-Type": "application/json",
    }


def _agent_code(name: str, prompt: str) -> str:
    cfg = default_agent_config(name, "Desde GitHub")
    cfg.system_prompt = prompt
    return render_agent_code(cfg)


def test_repo_and_branch_validation() -> None:
    assert gh.parse_repo("acme/soporte") == ("acme", "soporte")
    assert gh.parse_repo("https://github.com/acme/soporte.git") == ("acme", "soporte")
    for bad in ("acme", "acme/so porte", "../etc/passwd", "acme/..", "-x/y"):
        with pytest.raises(gh.GitHubError):
            gh.parse_repo(bad)
    assert gh.validate_branch("refs/heads/release/1.0") == "release/1.0"
    for bad in ("", "-main", "a..b", "x.lock", "a b", "a//b", "@{x}"):
        with pytest.raises(gh.GitHubError):
            gh.validate_branch(bad)
    body = b'{"zen": "Keep it logically awesome."}'
    assert gh.verify_signature("s3cret", body, gh.sign("s3cret", body))
    assert not gh.verify_signature("s3cret", body, gh.sign("other", body))
    assert not gh.verify_signature("", body, gh.sign("", body))
    assert not gh.verify_signature("s3cret", body, None)


async def test_connect_push_webhook_pull_and_conflicts(
    client: httpx.AsyncClient, fake_github: FakeGitHub, remotes: Path, enqueued: list[tuple[str, str]], tmp_path: Path
) -> None:
    await _signup(client)
    pid = await _project_with_agent(client)

    before = await client.get(f"/api/v1/projects/{pid}/github")
    assert before.status_code == 200 and before.json()["connected"] is False

    bad = await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "nope"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "github_auth"
    missing = await client.put(
        f"/api/v1/projects/{pid}/github", json={"repo": "acme/otro", "token": "github_pat_valid"}
    )
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "github_no_access"

    res = await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "github_pat_valid"})
    assert res.status_code == 200, res.text
    st = res.json()
    assert st["connected"] and st["mode"] == "pat" and st["branch"] == "main" and st["webhook"] == "auto"
    assert "webhook_secret" not in st
    assert enqueued[-1] == (pid, "connect")
    hook = next(iter(fake_github.hooks.values()))
    assert hook["config"]["url"].endswith("/api/github/webhook") and hook["events"] == ["push"]
    project = await _project(pid)
    assert project.github_repo == "acme/soporte"
    assert decrypt(project.github_config["token"]) == "github_pat_valid"
    assert "github_pat_valid" not in json.dumps(project.github_config)
    secret = decrypt(project.github_config["webhook_secret"])
    assert hook["config"]["secret"] == secret

    # Initial sync pushes the whole project to the empty repository.
    repo = ProjectRepo.for_project(pid)
    result = await svc.sync_project(uuid.UUID(pid), reason="connect")
    assert result["status"] == "ok", result
    head = await repo.head()
    assert result["pushed"] == head
    assert git(remotes, "rev-parse", "main") == head

    # A Messer commit triggers the commit hook (debounced push).
    enqueued.clear()
    detail = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()
    cfg = detail["config"]
    cfg["system_prompt"] = "Eres el asistente de Acme."
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    assert (pid, "commit") in enqueued
    result = await svc.sync_project(uuid.UUID(pid), reason="push")
    assert result["pushed"] == await repo.head()
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(remotes), str(clone))
    assert "Eres el asistente de Acme." in (clone / "workforce/soporte/agent.py").read_text()

    # Someone pushes to GitHub: an edited agent and a brand-new one.
    (clone / "workforce/soporte/agent.py").write_text(_agent_code("soporte", "Prompt editado en GitHub."))
    ventas_id = str(uuid.uuid4())
    (clone / "workforce/ventas").mkdir()
    ventas_cfg = default_agent_config("ventas", "Ventas")
    (clone / "workforce/ventas/agent.py").write_text(render_agent_code(ventas_cfg))
    (clone / "workforce/ventas/__init__.py").write_text("")
    (clone / "workforce/ventas/messer.yaml").write_text(
        member_manifest(
            member_id=ventas_id, kind="agent", source_mode="config", config=ventas_cfg.model_dump(mode="json")
        )
    )
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "Edit soporte, add ventas")
    git(clone, "push", "-q", "origin", "main")
    pushed_sha = git(clone, "rev-parse", "HEAD")

    payload = {"ref": "refs/heads/main", "after": pushed_sha, "repository": {"full_name": "acme/soporte"}}
    raw, headers = _webhook(payload, "wrong-secret")
    assert (await client.post("/api/github/webhook", content=raw, headers=headers)).status_code == 401
    raw, headers = _webhook({**payload, "ref": "refs/heads/other"}, secret)
    other = await client.post("/api/github/webhook", content=raw, headers=headers)
    assert other.status_code == 202 and other.json()["accepted"] is False
    raw, headers = _webhook(payload, secret)
    hooked = await client.post("/api/github/webhook", content=raw, headers=headers)
    assert hooked.status_code == 202 and hooked.json()["projects"] == [pid]
    assert enqueued[-1] == (pid, "pull")

    result = await svc.sync_project(uuid.UUID(pid), reason="pull")
    assert result["status"] == "ok", result
    assert result["pulled"]["updated"] == ["soporte"] and result["pulled"]["created"] == ["ventas"]
    assert result["pushed"] is None  # fast-forward: nothing new to push
    assert await repo.head() == pushed_sha

    soporte = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()
    assert soporte["config"]["system_prompt"] == "Prompt editado en GitHub." and soporte["source_mode"] == "config"
    ventas = (await client.get(f"/api/v1/projects/{pid}/workforce/ventas")).json()
    assert ventas["id"] == ventas_id and ventas["kind"] == "agent"
    async with system_session() as s:
        versions = (await s.execute(select(Version).where(Version.project_id == uuid.UUID(pid)))).scalars().all()
        github_versions = [v for v in versions if v.source == "github"]
        assert {v.entity_type for v in github_versions} == {"workforce", "project"}
        assert len([v for v in github_versions if v.entity_type == "workforce"]) == 2
        assert all(v.git_commit == pushed_sha for v in github_versions)
        assert any(v.message == "GitHub: Edit soporte, add ventas" for v in github_versions)
        actions = {a.action for a in (await s.execute(select(AuditLog))).scalars()}
        assert {"github.connected", "github.pulled"} <= actions
        notes = (await s.execute(select(Notification).where(Notification.kind == "github_sync"))).scalars().all()
        assert len(notes) == 1 and "soporte" in notes[0].payload["body"]

    # Both sides change the same line: Messer wins on the conflict, GitHub's other changes are merged.
    cfg = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()["config"]
    cfg["system_prompt"] = "Versión de Messer."
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    git(clone, "pull", "-q", "--ff-only")
    (clone / "workforce/soporte/agent.py").write_text(_agent_code("soporte", "Versión de GitHub."))
    (clone / "docs.md").write_text("Notas del equipo\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "Conflicting edit")
    git(clone, "push", "-q", "origin", "main")
    result = await svc.sync_project(uuid.UUID(pid), reason="push")
    assert result["status"] == "ok", result
    assert result["conflicts"] == ["workforce/soporte/agent.py"]
    head = await repo.head()
    assert result["pushed"] == head and git(remotes, "rev-parse", "main") == head
    message = git(repo.path, "log", "-1", "--format=%B")
    assert "Conflicts resolved in favour of Messer" in message and "workforce/soporte/agent.py" in message
    assert "Versión de Messer." in (repo.path / "workforce/soporte/agent.py").read_text()
    assert (repo.path / "docs.md").read_text() == "Notas del equipo\n"
    status = (await client.get(f"/api/v1/projects/{pid}/github")).json()
    assert status["state"] == "synced" and status["last_push_sha"] == head and status["head"] == head
    assert status["last_conflicts"] == ["workforce/soporte/agent.py"] and status["last_error"] is None

    # The echo of Messer's own push is ignored.
    enqueued.clear()
    raw, headers = _webhook({**payload, "after": head}, secret)
    echo = await client.post("/api/github/webhook", content=raw, headers=headers)
    assert echo.status_code == 202 and echo.json()["accepted"] is False and enqueued == []

    # Free-form code from GitHub switches the member to code mode; a removed directory deletes the member.
    git(clone, "pull", "-q", "--ff-only")
    code = (clone / "workforce/soporte/agent.py").read_text() + "\n\ndef helper() -> str:\n    return 'x'\n"
    (clone / "workforce/soporte/agent.py").write_text(code)
    git(clone, "rm", "-rq", "workforce/ventas")
    git(clone, "commit", "-qam", "Code mode and remove ventas")
    git(clone, "push", "-q", "origin", "main")
    result = await svc.sync_project(uuid.UUID(pid), reason="pull")
    assert result["pulled"]["updated"] == ["soporte"] and result["pulled"]["deleted"] == ["ventas"]
    soporte = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()
    assert soporte["source_mode"] == "code" and "def helper" in soporte["code"]
    assert (await client.get(f"/api/v1/projects/{pid}/workforce/ventas")).status_code == 404

    # Unsafe incoming trees are refused and reported; the project repository is untouched.
    before_head = await repo.head()
    git(clone, "pull", "-q", "--ff-only")
    os.symlink("/etc/passwd", clone / "workforce/soporte/leak.txt")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "Symlink")
    git(clone, "push", "-q", "origin", "main")
    result = await svc.sync_project(uuid.UUID(pid), reason="pull")
    assert result["status"] == "error" and "enlaces simbólicos" in result["error"]
    assert await repo.head() == before_head
    status = (await client.get(f"/api/v1/projects/{pid}/github")).json()
    assert status["state"] == "error" and "leak.txt" in status["last_error"]

    # Disconnect removes the webhook, the configuration and the commit-hook marker.
    gone = await client.delete(f"/api/v1/projects/{pid}/github")
    assert gone.status_code == 204
    assert fake_github.hooks == {}
    assert (await client.get(f"/api/v1/projects/{pid}/github")).json()["connected"] is False
    assert not gh.is_marked(pid, repo.path.parent)
    assert (await svc.sync_project(uuid.UUID(pid), reason="push"))["status"] == "not_connected"
    raw, headers = _webhook(payload, secret)
    assert (await client.post("/api/github/webhook", content=raw, headers=headers)).status_code == 401


async def test_manual_webhook_secret_and_rotation(
    client: httpx.AsyncClient, remotes: Path, enqueued: list[tuple[str, str]]
) -> None:
    fake = FakeGitHub(hooks_allowed=False)
    gh.api_transport = httpx.MockTransport(fake)
    await _signup(client, "manual@example.com")
    pid = await _project_with_agent(client)
    res = await client.put(
        f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "github_pat_valid", "branch": "dev"}
    )
    assert res.status_code == 200, res.text
    st = res.json()
    assert st["webhook"] == "manual" and st["branch"] == "dev" and len(st["webhook_secret"]) >= 32
    first = st["webhook_secret"]
    # Re-saving the same repository keeps the secret (it is never shown again) and the stored token.
    again = await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "branch": "dev"})
    assert again.status_code == 200 and "webhook_secret" not in again.json()
    rotated = await client.post(f"/api/v1/projects/{pid}/github/webhook-secret")
    assert rotated.status_code == 200 and rotated.json()["webhook_secret"] != first
    payload = {"ref": "refs/heads/dev", "after": "a" * 40, "repository": {"full_name": "acme/soporte"}}
    raw, headers = _webhook(payload, first)
    assert (await client.post("/api/github/webhook", content=raw, headers=headers)).status_code == 401
    raw, headers = _webhook(payload, rotated.json()["webhook_secret"])
    assert (await client.post("/api/github/webhook", content=raw, headers=headers)).status_code == 202

    # The branch did not exist on GitHub: the first sync creates it.
    result = await svc.sync_project(uuid.UUID(pid), reason="connect")
    assert result["status"] == "ok" and result["pushed"] == await ProjectRepo.for_project(pid).head()
    assert git(remotes, "rev-parse", "dev") == result["pushed"]


async def test_commit_hook_debounces_pushes(client: httpx.AsyncClient, fake_github: FakeGitHub) -> None:
    from messer_common.queue import close_queue

    await _signup(client, "debounce@example.com")
    pid = await _project_with_agent(client)
    # Not connected: commits enqueue nothing.
    assert not gh.is_marked(pid, ProjectRepo.for_project(pid).path.parent)
    gh.mark_connected(ProjectRepo.for_project(pid), {"repo": "acme/soporte", "branch": "main"})
    for _ in range(3):
        bucket = int(time.time() // svc.PUSH_DEBOUNCE_S)
        first = await svc.enqueue_sync(pid, reason="commit")
        second = await svc.enqueue_sync(pid, reason="commit")
        if bucket == int(time.time() // svc.PUSH_DEBOUNCE_S):
            assert first == f"github-push:{pid}:{bucket}" and second is None
            break
    await close_queue()


@pytest.fixture
def app_keys(remotes: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", pem.replace("\n", "\\n"))
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "app-webhook-secret")
    monkeypatch.setenv("GITHUB_APP_SLUG", "messer-test")
    gh.reset_github_settings()
    fake = FakeGitHub(public_key=key.public_key())
    gh.api_transport = httpx.MockTransport(fake)
    yield fake


async def test_github_app_mode(
    client: httpx.AsyncClient, app_keys: FakeGitHub, remotes: Path, enqueued: list[tuple[str, str]]
) -> None:
    await _signup(client, "app@example.com")
    pid = await _project_with_agent(client)
    st = (await client.get(f"/api/v1/projects/{pid}/github")).json()
    assert st["app_available"] and st["app_install_url"] == "https://github.com/apps/messer-test/installations/new"
    res = await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "mode": "app"})
    assert res.status_code == 200, res.text
    assert res.json()["mode"] == "app" and res.json()["webhook"] == "app"
    project = await _project(pid)
    assert project.github_config["installation_id"] == 42 and "token" not in project.github_config

    result = await svc.sync_project(uuid.UUID(pid), reason="connect")
    assert result["status"] == "ok", result
    assert git(remotes, "rev-parse", "main") == result["pushed"]
    assert app_keys.installation_tokens == 1  # cached across calls

    payload = {"zen": "Design for failure.", "repository": {"full_name": "acme/soporte"}}
    raw, headers = _webhook(payload, "app-webhook-secret", event="ping")
    ping = await client.post("/api/github/webhook", content=raw, headers=headers)
    assert ping.status_code == 200 and ping.json()["projects"] == 1
    # App deliveries for repositories no project syncs are acknowledged, not rejected.
    raw, headers = _webhook({"repository": {"full_name": "acme/ajeno"}}, "app-webhook-secret", event="ping")
    assert (await client.post("/api/github/webhook", content=raw, headers=headers)).status_code == 202


async def test_github_roles(
    client: httpx.AsyncClient, make_user, make_org, login, fake_github: FakeGitHub, enqueued: list[tuple[str, str]]
) -> None:  # type: ignore[no-untyped-def]
    builder = await make_user("gh-builder@example.com")
    viewer = await make_user("gh-viewer@example.com")
    org, owner = await make_org(name="Acme GH", members={str(builder.id): "builder", str(viewer.id): "viewer"})
    await login(owner.email, PASSWORD)
    pid = await _project_with_agent(client)

    await login(builder.email, PASSWORD)
    denied = await client.put(
        f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "github_pat_valid"}
    )
    assert denied.status_code == 403
    not_connected = await client.post(f"/api/v1/projects/{pid}/github/sync")
    assert not_connected.status_code == 400 and not_connected.json()["error"]["code"] == "github_not_connected"

    await login(owner.email, PASSWORD)
    assert (
        await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "github_pat_valid"})
    ).status_code == 200

    await login(builder.email, PASSWORD)
    queued = await client.post(f"/api/v1/projects/{pid}/github/sync")
    assert queued.status_code == 202 and enqueued[-1] == (pid, "manual")
    assert (await client.delete(f"/api/v1/projects/{pid}/github")).status_code == 403

    await login(viewer.email, PASSWORD)
    st = await client.get(f"/api/v1/projects/{pid}/github")
    assert st.status_code == 200 and st.json()["repo"] == "acme/soporte"
    assert "token" not in st.json() and "webhook_secret" not in st.json()
    assert (await client.post(f"/api/v1/projects/{pid}/github/sync")).status_code == 403

    # A second project in the same organization cannot sync the same branch.
    await login(owner.email, PASSWORD)
    other = await client.post("/api/v1/projects", json={"name": "Otro"})
    clash = await client.put(
        f"/api/v1/projects/{other.json()['id']}/github", json={"repo": "acme/soporte", "token": "github_pat_valid"}
    )
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "github_branch_in_use"
    async with system_session() as s:
        assert (
            await s.execute(select(Workforce).where(Workforce.project_id == uuid.UUID(pid)))
        ).scalar_one().name == "soporte"
    _ = org


async def test_worker_jobs(
    client: httpx.AsyncClient, fake_github: FakeGitHub, remotes: Path, enqueued: list[tuple[str, str]]
) -> None:
    from arq import Retry

    from messer_common.events import get_redis
    from messer_worker.jobs import github as jobs

    await _signup(client, "worker@example.com")
    pid = await _project_with_agent(client)
    assert (await jobs.github_push({"job_try": 1}, pid))["status"] == "not_connected"
    res = await client.put(f"/api/v1/projects/{pid}/github", json={"repo": "acme/soporte", "token": "github_pat_valid"})
    assert res.status_code == 200
    pushed = await jobs.github_push({"job_try": 1}, pid)
    assert pushed["status"] == "ok" and pushed["pushed"] == git(remotes, "rev-parse", "main")
    pulled = await jobs.github_pull({"job_try": 1}, pid, pushed["pushed"])
    assert pulled["status"] == "ok" and pulled["pushed"] is None and pulled["pulled"] is None

    # Another sync holds the project lock: the job is retried later instead of running concurrently.
    lock = get_redis().lock(f"github-sync:{pid}", timeout=30)
    assert await lock.acquire()
    try:
        with pytest.raises(Retry):
            await jobs.github_push({"job_try": 1}, pid)
    finally:
        await lock.release()
