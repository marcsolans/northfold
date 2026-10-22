"""Helpers for the interface tests: a signed-up owner with a project, an invoices knowledge base, deployments."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from messer_common.db import Principal, system_session
from messer_common.db.models import Deployment, Org, Project, User, Workforce
from messer_common.projects_repo import ProjectRepo

PASSWORD = "Contrasena123"

INVOICE_COLUMNS = [
    {"name": "numero", "type": "text"},
    {"name": "cliente", "type": "text"},
    {"name": "importe", "type": "numeric"},
    {"name": "estado", "type": "text"},
    {"name": "fecha_emision", "type": "date"},
    {"name": "fecha_vencimiento", "type": "date"},
]


def invoice_rows() -> list[dict[str, Any]]:
    today = date.today()
    return [
        {
            "numero": "F-001",
            "cliente": "Acme",
            "importe": 1200.5,
            "estado": "pendiente",
            "fecha_emision": (today - timedelta(days=40)).isoformat(),
            "fecha_vencimiento": (today - timedelta(days=10)).isoformat(),
        },
        {
            "numero": "F-002",
            "cliente": "Globex",
            "importe": 300,
            "estado": "pendiente",
            "fecha_emision": (today - timedelta(days=5)).isoformat(),
            "fecha_vencimiento": (today + timedelta(days=25)).isoformat(),
        },
        {
            "numero": "F-003",
            "cliente": "Initech",
            "importe": 980,
            "estado": "pagada",
            "fecha_emision": (today - timedelta(days=70)).isoformat(),
            "fecha_vencimiento": (today - timedelta(days=40)).isoformat(),
        },
    ]


@dataclass
class Owner:
    client: httpx.AsyncClient
    user_id: uuid.UUID
    org_id: uuid.UUID
    org_slug: str
    project_id: str
    project_slug: str

    def principal(self) -> Principal:
        return Principal(user_id=self.user_id, org_id=self.org_id, role="owner")


async def signup_owner(client: httpx.AsyncClient, email: str = "olga@acme.example", project: str = "Facturas") -> Owner:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": PASSWORD, "name": "Olga"})
    assert res.status_code == 200, res.text
    org_id = uuid.UUID(res.json()["org_id"])
    res = await client.post("/api/v1/projects", json={"name": project})
    assert res.status_code == 201, res.text
    pid = res.json()["id"]
    async with system_session() as s:
        org = await s.get(Org, org_id)
        proj = await s.get(Project, uuid.UUID(pid))
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        assert org is not None and proj is not None
        return Owner(client, user.id, org_id, org.slug, pid, proj.slug)


async def add_agent(owner: Owner, name: str = "soporte", tools: list[dict[str, Any]] | None = None) -> None:
    res = await owner.client.post(f"/api/v1/projects/{owner.project_id}/workforce", json={"name": name})
    assert res.status_code == 201, res.text
    cfg = res.json()["config"]
    cfg["system_prompt"] = "Eres el asistente de facturas. Responde en español."
    cfg["tools"] = tools or []
    res = await owner.client.put(f"/api/v1/projects/{owner.project_id}/workforce/{name}/config", json=cfg)
    assert res.status_code == 200, res.text


WORKFLOW_CODE = """from messer import Workflow


def registrar(factura: str, importe: float, solicitante: str = "") -> dict:
    return {"registrada": factura, "importe": importe, "por": solicitante}


workflow = Workflow(name="registrar").step(registrar)
"""


async def add_workflow(owner: Owner, name: str = "registrar") -> None:
    """A workflow member written as code (the workflow builder belongs to another area)."""
    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(owner.project_id))
        assert project is not None
        member = Workforce(
            org_id=project.org_id,
            project_id=project.id,
            kind="workflow",
            name=name,
            path=f"workforce/{name}",
            source_mode="code",
        )
        s.add(member)
        await s.flush()
        manifest = "# Messer workforce member.\n" + json.dumps(
            {
                "_id": str(member.id),
                "_type": "workflow",
                "fqn": "workflow.py::workflow",
                "studio": {"source_mode": "code"},
            }
        )
    await ProjectRepo.for_project(owner.project_id).write(
        {
            f"workforce/{name}/__init__.py": "",
            f"workforce/{name}/workflow.py": WORKFLOW_CODE,
            f"workforce/{name}/messer.yaml": manifest,
        },
        message=f"Add workflow {name}",
        author="Test",
        email="test@example.com",
    )


async def invoices_kb(owner: Owner, *, project_bound: bool = True) -> uuid.UUID:
    from messer_api.services.knowledge import create_kb, upsert_table

    kb = await create_kb(
        owner.principal(),
        name="Facturación",
        embedding_model="hash-384",
        project_id=uuid.UUID(owner.project_id) if project_bound else None,
    )
    async with system_session() as s:
        await upsert_table(
            s,
            org_id=owner.org_id,
            kb_id=kb.id,
            table="facturas",
            columns=INVOICE_COLUMNS,
            rows=invoice_rows(),
            primary_key=["numero"],
        )
    return kb.id


async def deploy(owner: Owner, *, runtime: bool = False) -> Deployment:
    """Publish HEAD to production through the deployment pipeline (evals skipped; the worker is not running)."""
    from messer_api.services import deployments

    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(owner.project_id))
        assert project is not None
        dep = await deployments.request_deployment(
            s,
            owner.principal(),
            project,
            environment="production",
            version_id=None,
            force=False,
            skip_evals=not runtime,
        )
        dep_id = dep.id
    done = await deployments.run_pipeline(dep_id, skip_evals=not runtime)
    assert done.status == "live", done.logs
    return done


async def sse(
    client: httpx.AsyncClient, url: str, body: dict[str, Any], headers: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body, headers=headers) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.fixture
async def drop_kb_roles(clean_database: None) -> AsyncIterator[None]:
    """Knowledge bases create cluster-wide reader roles: drop them before the shared truncation."""
    yield
    async with system_session() as s:
        rows = await s.execute(text("SELECT schema_name, reader_role FROM public.knowledge_bases"))
        for schema, role in rows.all():
            await s.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            exists = (await s.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).first()
            if exists:
                await s.execute(text(f'DROP ROLE "{role}"'))


@pytest.fixture
async def anon_client() -> AsyncIterator[httpx.AsyncClient]:
    """A fresh browser: its own cookie jar, no session."""
    from messer_api.main import create_app

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=120
    ) as c:
        yield c
