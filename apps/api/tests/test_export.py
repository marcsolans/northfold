"""Project export: a self-contained .zip (project at a ref, linked knowledge as data, engine wheel, compose files)
that runs without Messer — verified by unzipping it, validating ``docker compose config`` when the docker CLI exists,
and running the standalone platform plus an agent as subprocesses (no Docker) and asking the agent a question."""

from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import zipfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from sqlalchemy import select, text

from messer_common.db import Principal, system_session
from messer_common.db.models import KbChunk, KbFile, KbPolicy, KnowledgeBase, Membership, Secret, User
from messer_common.security import encrypt
from messer_common.settings import get_settings

PASSWORD = "Sup3rSecret!pass"
OFFLINE_MARK = "Modelo offline de la exportación"


@pytest.fixture(autouse=True)
async def _drop_kb_roles(clean_database: None) -> AsyncIterator[None]:
    """Knowledge bases create cluster-wide reader roles: drop them so repeated runs do not accumulate roles."""
    yield
    async with system_session() as s:
        rows = await s.execute(text("SELECT schema_name, reader_role FROM public.knowledge_bases"))
        for schema, role in rows.all():
            await s.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            if (await s.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).first():
                await s.execute(text(f'DROP ROLE "{role}"'))


async def _owner_principal(email: str) -> Principal:
    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalar_one()
    return Principal(user_id=user.id, org_id=org_id, role="owner", email=email)


async def _knowledge(principal: Principal, project_id: uuid.UUID | None, name: str) -> KnowledgeBase:
    from messer_api.services.knowledge import create_kb, upsert_table

    kb = await create_kb(principal, name=name, embedding_model="hash-384", project_id=project_id)
    assert principal.org_id is not None
    async with system_session() as s:
        file = KbFile(
            org_id=principal.org_id,
            kb_id=kb.id,
            path=f"kb/{kb.id}/condiciones.pdf",
            filename="condiciones.pdf",
            mime="application/pdf",
            size=1234,
            status="ready",
            pages=3,
            chunk_count=2,
        )
        s.add(file)
        await s.flush()
        s.add_all(
            [
                KbChunk(
                    org_id=principal.org_id,
                    kb_id=kb.id,
                    file_id=file.id,
                    ordinal=0,
                    content="El plazo de pago de las facturas es de 30 días desde la emisión.",
                    heading="Pagos",
                    page_from=2,
                    page_to=2,
                    meta={"section": "pagos"},
                ),
                KbChunk(
                    org_id=principal.org_id,
                    kb_id=kb.id,
                    file_id=file.id,
                    ordinal=1,
                    content="Las devoluciones se aceptan durante 14 días.",
                    heading="Devoluciones",
                    page_from=3,
                    page_to=3,
                ),
            ]
        )
        await upsert_table(
            s,
            org_id=principal.org_id,
            kb_id=kb.id,
            table="facturas",
            columns=[
                {"name": "numero", "type": "text", "nullable": False},
                {"name": "cliente", "type": "text"},
                {"name": "importe", "type": "numeric"},
                {"name": "pagada", "type": "boolean"},
            ],
            rows=[
                {"numero": "F-001", "cliente": "Acme", "importe": 120.5, "pagada": True},
                {"numero": "F-002", "cliente": "Globex", "importe": 980, "pagada": False},
            ],
            primary_key=["numero"],
        )
    return kb


async def _signup(client: httpx.AsyncClient, email: str) -> None:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "O"})
    assert res.status_code == 200, res.text


def _unzip(data: bytes, target: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert all(not n.startswith("/") and ".." not in n.split("/") for n in names)
        zf.extractall(target)
    roots = {n.split("/", 1)[0] for n in names}
    assert len(roots) == 1
    return target / roots.pop()


@pytest.fixture
def exported(tmp_path: Path) -> Iterator[Path]:
    yield tmp_path / "unzipped"
    shutil.rmtree(tmp_path / "unzipped", ignore_errors=True)


async def test_export_zip_contents(client: httpx.AsyncClient, exported: Path) -> None:
    email = "export-owner@example.com"
    await _signup(client, email)
    created = await client.post("/api/v1/projects", json={"name": "Soporte facturas", "description": "Atención"})
    pid = created.json()["id"]
    principal = await _owner_principal(email)
    linked = await _knowledge(principal, uuid.UUID(pid), "Facturación")
    unlinked = await _knowledge(principal, None, "Otra base")
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, linked.id)
        assert kb is not None
        kb.governance_mode = "enforce"
        s.add(
            KbPolicy(
                org_id=kb.org_id, kb_id=kb.id, table="facturas", role="agent", masked_columns={"cliente": "redact"}
            )
        )
        s.add(
            Secret(
                org_id=kb.org_id, project_id=uuid.UUID(pid), name="CRM_TOKEN", encrypted_value=encrypt("supersecreto")
            )
        )

    agent = await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte", "description": "Dudas"})
    first_commit = agent.json()["commit"]
    cfg = agent.json()["config"]
    cfg["knowledge_bases"] = [str(linked.id)]
    cfg["tools"] = [{"type": "builtin", "key": "knowledge_search"}]
    cfg["system_prompt"] = "Responde citando las condiciones."
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200

    res = await client.get(f"/api/v1/projects/{pid}/export.zip")
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert res.headers["content-disposition"].startswith('attachment; filename="soporte-facturas-')
    root = _unzip(res.content, exported)
    assert root.name == "soporte-facturas"

    manifest = json.loads((root / "messer-export.json").read_text())
    assert manifest["format"] == "messer-export/1" and manifest["commit"] == res.headers["x-messer-commit"]
    assert manifest["members"] == [
        {
            "name": "soporte",
            "kind": "agent",
            "service": "soporte",
            "port": 8001,
            "entrypoint": ".messer/entrypoints/entry_soporte.py::runnable",
            "url": "http://localhost:8001",
        }
    ]
    assert [k["id"] for k in manifest["knowledge_bases"]] == [str(linked.id)]
    assert manifest["secrets"] == ["CRM_TOKEN"]

    # Project files at the ref, engine wheel, entry points and docs.
    assert "Responde citando las condiciones." in (root / "project/workforce/soporte/agent.py").read_text()
    wheel = next((root / "vendor").glob("messer_core-*.whl"))
    with zipfile.ZipFile(wheel) as whl:
        assert "messer/platform/standalone/app.py" in whl.namelist()
    assert wheel.name in (root / "Dockerfile").read_text()
    assert "workforce.soporte.agent" in (root / ".messer/entrypoints/entry_soporte.py").read_text()
    readme = (root / "README.md").read_text()
    assert "Inicio rápido" in readme and "Quick start" in readme and "docker compose up" in readme
    assert "ANTHROPIC_API_KEY=" in (root / ".env.example").read_text()
    assert "CRM_TOKEN=" in (root / "secrets.env.example").read_text()
    assert any(line.startswith("anthropic==") for line in (root / "constraints.txt").read_text().splitlines())
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".whl":
            assert "supersecreto" not in path.read_text(errors="ignore"), path

    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    platform = compose["services"]["platform"]
    assert platform["command"][:3] == ["python", "-m", "messer.platform.standalone"]
    member = compose["services"]["soporte"]
    assert member["command"][:3] == ["python", "-m", "messer.server"]
    assert member["environment"]["MESSER_API_HOST"] == "http://platform:8000/"
    assert member["environment"]["MESSER_ORG_ID"] == str(principal.org_id)
    assert member["environment"]["MESSER_PROJECT_ID"] == pid
    assert member["ports"] == ["127.0.0.1:8001:8001"]
    assert member["depends_on"]["platform"]["condition"] == "service_healthy"

    # Knowledge exported as data, with the agent-role policies applied (the agent never sees «cliente»).
    kb_dir = root / "data/knowledge" / str(linked.id)
    assert not (root / "data/knowledge" / str(unlinked.id)).exists()
    chunks = [json.loads(line) for line in (kb_dir / "chunks.jsonl").read_text().splitlines()]
    assert [c["ordinal"] for c in chunks] == [0, 1] and chunks[0]["filename"] == "condiciones.pdf"
    assert chunks[0]["metadata"] == {"section": "pagos"} and chunks[0]["page_from"] == 2
    schema = json.loads((kb_dir / "tables/facturas.schema.json").read_text())
    assert schema["primary_key"] == ["numero"]
    types = {c["name"]: c["type"] for c in schema["columns"]}
    assert types == {"numero": "text", "cliente": "text", "importe": "numeric", "pagada": "boolean"}
    assert [c for c in schema["columns"] if c["masked"]] == [{"name": "cliente", "type": "text", "masked": True}]
    csv_rows = (kb_dir / "tables/facturas.csv").read_text().splitlines()
    assert csv_rows[0] == "numero,cliente,importe,pagada"
    assert csv_rows[1].startswith("F-001,***,120.5") and csv_rows[1].endswith(",true")
    assert "Acme" not in (kb_dir / "tables/facturas.csv").read_text()
    kb_meta = json.loads((kb_dir / "kb.json").read_text())
    assert kb_meta["files"][0]["filename"] == "condiciones.pdf" and kb_meta["tables"][0]["row_count"] == 2

    if shutil.which("docker"):
        check = await asyncio.to_thread(_compose_config, root)
        assert check.returncode == 0, check.stderr

    # An older ref exports that commit; bad refs are refused; the wheel is built once and reused.
    old = await client.get(f"/api/v1/projects/{pid}/export.zip", params={"ref": first_commit})
    assert old.status_code == 200 and old.headers["x-messer-commit"] == first_commit
    with zipfile.ZipFile(io.BytesIO(old.content)) as zf:
        assert "Responde citando" not in zf.read("soporte-facturas/project/workforce/soporte/agent.py").decode()
    assert (
        await client.get(f"/api/v1/projects/{pid}/export.zip", params={"ref": "--output=/tmp/x"})
    ).status_code == 400
    assert (await client.get(f"/api/v1/projects/{pid}/export.zip", params={"ref": "nope"})).status_code == 404
    wheel_dirs = [p for p in (get_settings().runtime_cache_dir / "engine-wheels").iterdir() if p.is_dir()]
    assert len([p for p in wheel_dirs if ".tmp-" not in p.name]) >= 1
    async with system_session() as s:
        actions = (
            await s.execute(text("SELECT count(*) FROM audit_log WHERE action = 'project.exported'"))
        ).scalar_one()
        assert actions == 2


async def test_export_requires_builder(client: httpx.AsyncClient, make_user, make_org, login) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user("export-viewer@example.com")
    org, owner = await make_org(name="Acme Export", members={str(viewer.id): "viewer"})
    await login(owner.email, PASSWORD)
    pid = (await client.post("/api/v1/projects", json={"name": "Privado"})).json()["id"]
    await login(viewer.email, PASSWORD)
    denied = await client.get(f"/api/v1/projects/{pid}/export.zip")
    assert denied.status_code == 403
    assert (await client.get(f"/api/v1/projects/{uuid.uuid4()}/export.zip")).status_code == 403
    _ = org


def _compose_config(root: Path) -> subprocess.CompletedProcess[str]:
    """``docker compose config`` validates the file without a Docker daemon."""
    return subprocess.run(
        ["docker", "compose", "-f", str(root / "docker-compose.yml"), "config", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def _spawn(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _wait_healthy(url: str, proc: subprocess.Popen[bytes], within_s: float = 60) -> None:
    deadline = time.monotonic() + within_s
    async with httpx.AsyncClient(timeout=2) as http:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                raise AssertionError(f"process exited early ({proc.returncode}):\n{out[-4000:]}")
            try:
                if (await http.get(url)).status_code < 300:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
    raise AssertionError(f"{url} did not become healthy")


async def test_exported_project_runs_without_messer(client: httpx.AsyncClient, exported: Path, tmp_path: Path) -> None:
    email = "export-run@example.com"
    await _signup(client, email)
    pid = (await client.post("/api/v1/projects", json={"name": "Facturas"})).json()["id"]
    principal = await _owner_principal(email)
    kb = await _knowledge(principal, uuid.UUID(pid), "Condiciones")
    agent = await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})
    cfg = agent.json()["config"]
    cfg["knowledge_bases"] = [str(kb.id)]
    cfg["tools"] = [{"type": "builtin", "key": "knowledge_search"}, {"type": "builtin", "key": "calculator"}]
    assert (await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)).status_code == 200
    res = await client.get(f"/api/v1/projects/{pid}/export.zip")
    assert res.status_code == 200, res.text
    root = _unzip(res.content, exported)
    compose = yaml.safe_load((root / "docker-compose.yml").read_text())
    platform_env: dict[str, Any] = compose["services"]["platform"]["environment"]
    member_spec = compose["services"]["soporte"]
    token = (root / ".env.example").read_text().split("MESSER_STANDALONE_TOKEN=", 1)[1].strip()

    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
    }
    platform_port, member_port = _free_port(), _free_port()
    procs: list[subprocess.Popen[bytes]] = []
    try:
        platform = _spawn(
            [sys.executable, "-m", "messer.platform.standalone", "--host", "127.0.0.1", "--port", str(platform_port)],
            root,
            {
                **base_env,
                "MESSER_ORG_ID": platform_env["MESSER_ORG_ID"],
                "MESSER_PROJECT_ID": platform_env["MESSER_PROJECT_ID"],
                "MESSER_STANDALONE_TOKEN": token,
                "MESSER_STANDALONE_DATA_DIR": str(root / "data"),
                "MESSER_STANDALONE_STATE_DIR": str(tmp_path / "state"),
                "MESSER_STANDALONE_MANIFEST": str(root / "messer-export.json"),
            },
        )
        procs.append(platform)
        await _wait_healthy(f"http://127.0.0.1:{platform_port}/healthcheck", platform)
        command = list(member_spec["command"])
        spec = command[command.index("--import_spec") + 1].replace("/app/", f"{root}/")
        member = _spawn(
            [
                sys.executable,
                "-m",
                "messer.server",
                "--import_spec",
                spec,
                "--host",
                "127.0.0.1",
                "--port",
                str(member_port),
            ],
            root / "project",
            {
                **base_env,
                "MESSER_ORG_ID": member_spec["environment"]["MESSER_ORG_ID"],
                "MESSER_PROJECT_ID": member_spec["environment"]["MESSER_PROJECT_ID"],
                "MESSER_API_HOST": f"http://127.0.0.1:{platform_port}/",
                "MESSER_API_KEY": token,
            },
        )
        procs.append(member)
        await _wait_healthy(f"http://127.0.0.1:{member_port}/healthcheck", member)

        async with httpx.AsyncClient(timeout=120) as http:
            run = await http.post(
                f"http://127.0.0.1:{member_port}/run", json={"prompt": "¿Cuál es el plazo de pago de las facturas?"}
            )
            assert run.status_code == 200, run.text
            event = run.json()
            assert event["status"]["code"] == "success", event
            answer = "".join(block.get("text", "") for block in event["output"]["content"] if isinstance(block, dict))
            assert "30 días" in answer and "condiciones.pdf" in answer and OFFLINE_MARK in answer
            traces = await http.get(
                f"http://127.0.0.1:{platform_port}/traces", headers={"Authorization": f"Bearer {token}"}
            )
            assert traces.status_code == 200 and traces.json()["runs"], traces.text
            sql = await http.post(
                f"http://127.0.0.1:{platform_port}/orgs/{principal.org_id}/knowledge-bases/{kb.id}/query",
                json={"sql": "SELECT numero, importe FROM facturas WHERE importe > $1", "params": [500]},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert sql.status_code == 200 and sql.json()["rows"] == [["F-002", 980.0]], sql.text
    finally:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
