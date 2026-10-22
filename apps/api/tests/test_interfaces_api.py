"""Interfaces API: CRUD as code (commits), versions, preview data over a knowledge base table, roles, publication
snapshots and the public app endpoints (production only, login, sanitized definitions)."""

from __future__ import annotations

import copy
import json
import uuid
from typing import Any

import httpx
import pytest
from interfaces_support import (
    PASSWORD,
    Owner,
    add_agent,
    anon_client,
    deploy,
    drop_kb_roles,
    invoices_kb,
    signup_owner,
)
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import AuditLog, Interface, KbPolicy, KnowledgeBase, Membership, Project
from messer_common.interfaces import EXAMPLES
from messer_common.projects_repo import ProjectRepo

pytestmark = pytest.mark.usefixtures("drop_kb_roles")
__all__ = ["anon_client", "drop_kb_roles"]


async def _create_dashboard(owner: Owner, kb_id: uuid.UUID, **extra: Any) -> dict[str, Any]:
    res = await owner.client.post(
        f"/api/v1/projects/{owner.project_id}/interfaces",
        json={"template": "invoices_dashboard", "name": "Panel de facturas", "kb_id": str(kb_id), **extra},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _member(owner: Owner, make_user: Any, role: str) -> httpx.AsyncClient:
    from messer_api.main import create_app

    user = await make_user(password=PASSWORD)
    async with system_session() as s:
        s.add(Membership(org_id=owner.org_id, user_id=user.id, role=role))
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver", timeout=60
    )
    res = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    client.headers["X-Messer-Org"] = str(owner.org_id)
    return client


async def test_crud_is_code_with_versions_and_audit(client: httpx.AsyncClient) -> None:
    owner = await signup_owner(client)
    kb_id = await invoices_kb(owner)
    created = await _create_dashboard(owner, kb_id)
    iid = created["id"]
    assert created["slug"] == "panel-de-facturas" and created["kind"] == "app"
    assert created["valid"] and created["issues"] == [] and created["warnings"] == []
    assert created["components"] == 5 and created["auth_required"] is True and created["published"] is False
    assert created["urls"]["public"].endswith(f"/{owner.org_slug}/{owner.project_slug}/app/panel-de-facturas")

    repo = ProjectRepo.for_project(owner.project_id)
    stored = await repo.read("interfaces/panel-de-facturas/interface.json")
    assert stored is not None and '"kpi_pendientes"' in stored

    # Edit: rename the slug (moves the folder in one commit) and change a title.
    definition = copy.deepcopy(created["definition"])
    definition["slug"] = "facturas"
    definition["screens"][0]["components"][0]["title"] = "Pendientes"
    res = await client.put(f"/api/v1/interfaces/{iid}", json={"definition": definition, "message": "Retitular"})
    assert res.status_code == 200, res.text
    assert res.json()["slug"] == "facturas"
    assert await repo.read("interfaces/panel-de-facturas/interface.json") is None
    assert await repo.read("interfaces/facturas/interface.json") is not None

    versions = (await client.get(f"/api/v1/interfaces/{iid}/versions")).json()
    assert [v["message"] for v in versions][:1] == ["Retitular"]
    first = versions[0]["sha"]
    definition["screens"][0]["components"][0]["title"] = "Otra"
    res = await client.put(f"/api/v1/interfaces/{iid}", json={"definition": definition})
    assert res.status_code == 200, res.text
    versions = (await client.get(f"/api/v1/interfaces/{iid}/versions")).json()
    assert len(versions) == 2 and versions[1]["sha"] == first
    old = (await client.get(f"/api/v1/interfaces/{iid}/versions/{first}")).json()["definition"]
    assert old["screens"][0]["components"][0]["title"] == "Pendientes"

    # Invalid definitions are rejected with located issues; nothing is committed.
    head_before = await repo.head()
    broken = copy.deepcopy(definition)
    broken["screens"][0]["components"][0]["grid"]["w"] = 20
    res = await client.put(f"/api/v1/interfaces/{iid}", json={"definition": broken})
    assert res.status_code == 422
    issue = res.json()["error"]["details"]["issues"][0]
    assert issue["path"] == "screens[0].components[0].grid.w"
    assert await repo.head() == head_before

    # Unknown references are warnings (another builder may create them later).
    with_agent = copy.deepcopy(definition)
    with_agent["screens"][0]["components"].append(
        {
            "id": "boton",
            "type": "action_button",
            "grid": {"x": 0, "y": 20, "w": 3, "h": 2},
            "props": {"label": "Avisar"},
            "binding": {"kind": "agent", "workforce": "no_existe"},
        }
    )
    res = await client.post(f"/api/v1/projects/{owner.project_id}/interfaces/validate", json={"definition": with_agent})
    body = res.json()
    assert body["valid"] is True and body["warnings"][0]["code"] == "workforce_not_found"

    # Restore an earlier version (a new commit; the slug stays).
    res = await client.post(f"/api/v1/interfaces/{iid}/versions/{first}/restore")
    assert res.status_code == 200, res.text
    assert res.json()["definition"]["screens"][0]["components"][0]["title"] == "Pendientes"

    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action).where(AuditLog.entity_id == iid))).scalars())
    assert {"interface.created", "interface.updated"} <= actions

    # Files written outside the API (git push, Composer) are indexed on listing.
    await repo.write(
        {"interfaces/chat-web/interface.json": json.dumps(EXAMPLES["public_chat"] | {"slug": "chat-web"})},
        message="Add chat",
        author="Dev",
        email="dev@example.com",
    )
    listed = (await client.get(f"/api/v1/projects/{owner.project_id}/interfaces")).json()
    assert {i["slug"] for i in listed} == {"facturas", "chat-web"}
    chat = next(i for i in listed if i["slug"] == "chat-web")
    assert chat["kind"] == "chat" and chat["workforce_name"] == "soporte"
    assert chat["urls"]["widget"].startswith("<script src=")

    res = await client.delete(f"/api/v1/interfaces/{iid}")
    assert res.status_code == 204
    assert await repo.read("interfaces/facturas/interface.json") is None
    assert (await client.get(f"/api/v1/interfaces/{iid}")).status_code == 404


async def test_preview_data_runs_sql_with_params_and_policies(client: httpx.AsyncClient, make_user: Any) -> None:
    owner = await signup_owner(client)
    kb_id = await invoices_kb(owner)
    iid = (await _create_dashboard(owner, kb_id))["id"]
    url = f"/api/v1/interfaces/{iid}/components"

    kpi = (await client.post(f"{url}/kpi_pendientes/data", json={})).json()
    assert kpi["source"] == "knowledge_sql" and kpi["rows"] == [{"total": 2}]
    amount = (await client.post(f"{url}/kpi_importe/data", json={})).json()
    assert float(amount["rows"][0]["importe"]) == pytest.approx(1500.5)
    overdue = (await client.post(f"{url}/kpi_vencidas/data", json={})).json()
    assert overdue["rows"] == [{"total": 1}]

    table = (await client.post(f"{url}/tabla_pendientes/data", json={})).json()
    assert [r["numero"] for r in table["rows"]] == ["F-001", "F-002"]
    assert table["columns"] == ["numero", "cliente", "importe", "fecha_vencimiento", "estado"]
    # Filter values are parameters: injection attempts are just values that match nothing.
    paid = (await client.post(f"{url}/tabla_pendientes/data", json={"inputs": {"estado": "pagada"}})).json()
    assert [r["numero"] for r in paid["rows"]] == ["F-003"]
    injected = (await client.post(f"{url}/tabla_pendientes/data", json={"inputs": {"estado": "x' OR '1'='1"}})).json()
    assert injected["rows"] == []
    bad = await client.post(f"{url}/tabla_pendientes/data", json={"inputs": {"estado": {"a": 1}}})
    assert bad.status_code == 422

    chart = (await client.post(f"{url}/grafico_mensual/data", json={})).json()
    assert chart["columns"] == ["mes", "importe"] and len(chart["rows"]) >= 2
    assert (await client.post(f"{url}/nope/data", json={})).status_code == 404

    # Unsaved component (editor preview): builders only, validated like the saved ones.
    draft = {
        "id": "borrador",
        "type": "kpi",
        "grid": {"x": 0, "y": 0, "w": 3, "h": 2},
        "binding": {"kind": "knowledge_sql", "kb_id": str(kb_id), "sql": "SELECT max(importe) AS m FROM facturas"},
    }
    res = await client.post(f"{url}/borrador/data", json={"draft": draft})
    assert res.status_code == 200 and float(res.json()["rows"][0]["m"]) == pytest.approx(1200.5)
    draft_bad = draft | {"binding": draft["binding"] | {"sql": "SELECT $1"}}
    res = await client.post(f"{url}/borrador/data", json={"draft": draft_bad})
    assert res.status_code == 422 and res.json()["error"]["details"]["issues"][0]["path"] == "component.binding.params"

    # Viewers use interfaces (their knowledge policies apply) but cannot edit them or send drafts.
    async with system_session() as s:
        s.add(
            KbPolicy(
                org_id=owner.org_id,
                kb_id=kb_id,
                table="facturas",
                role="viewer",
                masked_columns={"cliente": "redact"},
                row_filter_sql="importe < 1000",
            )
        )
    async with system_session() as s:
        kb = await s.get(KnowledgeBase, kb_id)
        assert kb is not None
        kb.governance_mode = "enforce"
    viewer = await _member(owner, make_user, "viewer")
    try:
        rows = (await viewer.post(f"{url}/tabla_pendientes/data", json={})).json()["rows"]
        assert [r["numero"] for r in rows] == ["F-002"]
        assert rows[0]["cliente"] != "Globex"
        assert (await viewer.post(f"{url}/borrador/data", json={"draft": draft})).status_code == 403
        assert (await viewer.put(f"/api/v1/interfaces/{iid}", json={"definition": {}})).status_code == 403
        assert (await viewer.delete(f"/api/v1/interfaces/{iid}")).status_code == 403
        assert (await viewer.get(f"/api/v1/interfaces/{iid}")).status_code == 200
    finally:
        await viewer.aclose()


async def test_knowledge_bases_of_other_projects_or_orgs_are_refused(
    client: httpx.AsyncClient, make_user: Any, make_org: Any
) -> None:
    owner = await signup_owner(client)
    other_org, other_owner = await make_org(name="Otra")
    from messer_api.services.knowledge import create_kb
    from messer_common.db import Principal

    foreign = await create_kb(
        Principal(user_id=other_owner.id, org_id=other_org.id, role="owner"), name="Ajena", embedding_model="hash-384"
    )
    definition = copy.deepcopy(EXAMPLES["invoices_dashboard"])
    for comp in definition["screens"][0]["components"]:
        if comp["binding"]["kind"] == "knowledge_sql":
            comp["binding"]["kb_id"] = str(foreign.id)
    definition["screens"][0]["components"] = definition["screens"][0]["components"][:5]
    res = await client.post(f"/api/v1/projects/{owner.project_id}/interfaces", json={"definition": definition})
    assert res.status_code == 201, res.text
    assert res.json()["warnings"][0]["code"] == "kb_not_found"
    data = await client.post(f"/api/v1/interfaces/{res.json()['id']}/components/kpi_pendientes/data", json={})
    assert data.status_code == 404 and data.json()["error"]["code"] == "kb_not_found"


async def test_publication_snapshot_and_public_app(
    client: httpx.AsyncClient, anon_client: httpx.AsyncClient, make_user: Any
) -> None:
    owner = await signup_owner(client)
    kb_id = await invoices_kb(owner)
    created = await _create_dashboard(owner, kb_id)
    iid, slug = created["id"], created["slug"]
    public = f"/api/public/v1/apps/{owner.org_slug}/{owner.project_slug}/{slug}"

    # Before the first deployment: a friendly 409.
    res = await anon_client.get(public)
    assert res.status_code == 409 and res.json()["error"]["code"] == "not_deployed"

    await deploy(owner)
    async with system_session() as s:
        row = await s.get(Interface, uuid.UUID(iid))
        assert row is not None and row.published_definition is not None and row.published_at is not None

    # Login required by default for apps.
    res = await anon_client.get(public)
    assert res.status_code == 401 and res.json()["error"]["code"] == "login_required"
    res = await client.get(public)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["viewer"]["authenticated"] and view["viewer"]["role"] == "owner"
    comps = view["interface"]["screens"][0]["components"]
    # The browser never receives queries, ids or mappings.
    assert all("sql" not in (c["binding"] or {}) and "kb_id" not in (c["binding"] or {}) for c in comps)
    table = next(c for c in comps if c["id"] == "tabla_pendientes")
    assert table["binding"] == {"kind": "knowledge_sql", "inputs": ["estado"]}
    data = (await client.post(f"{public}/components/tabla_pendientes/data", json={})).json()
    assert [r["numero"] for r in data["rows"]] == ["F-001", "F-002"] and "policy" not in data
    res = await client.post(f"{public}/components/kpi_pendientes/data", json={"draft": {"id": "x"}})
    assert res.status_code == 400

    # Editing the draft does not change production until the next deployment.
    definition = copy.deepcopy(created["definition"])
    definition["name"] = "Panel nuevo"
    definition["auth"] = {"required": False, "roles": []}
    assert (await client.put(f"/api/v1/interfaces/{iid}", json={"definition": definition})).status_code == 200
    assert (await anon_client.get(public)).status_code == 401
    await deploy(owner)
    res = await anon_client.get(public)
    assert res.status_code == 200 and res.json()["interface"]["name"] == "Panel nuevo"
    assert res.json()["viewer"] == {"authenticated": False, "role": None, "email": None, "can_upload": False}
    rows = (await anon_client.post(f"{public}/components/kpi_pendientes/data", json={})).json()["rows"]
    assert rows == [{"total": 2}]

    # Roles restrict access; members of other organizations are not members here.
    definition["auth"] = {"required": True, "roles": ["admin"]}
    assert (await client.put(f"/api/v1/interfaces/{iid}", json={"definition": definition})).status_code == 200
    await deploy(owner)
    viewer = await _member(owner, make_user, "viewer")
    try:
        res = await viewer.get(public)
        assert res.status_code == 403 and res.json()["error"]["code"] == "insufficient_role"
    finally:
        await viewer.aclose()

    # Removed from the code → unpublished at the next deployment.
    assert (await client.delete(f"/api/v1/interfaces/{iid}")).status_code == 204
    await deploy(owner)
    assert (await client.get(public)).status_code == 404
    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(owner.project_id))
        assert project is not None
        left = (await s.execute(select(Interface).where(Interface.project_id == project.id))).scalars().all()
    assert left == []


async def test_publication_skips_invalid_files_and_unknown_pages(
    client: httpx.AsyncClient, anon_client: httpx.AsyncClient
) -> None:
    owner = await signup_owner(client)
    await add_agent(owner)
    repo = ProjectRepo.for_project(owner.project_id)
    await repo.write(
        {"interfaces/roto/interface.json": '{"name": "Roto", "slug": "roto", "screens": []}'},
        message="Broken",
        author="Dev",
        email="dev@example.com",
    )
    res = await client.post(
        f"/api/v1/projects/{owner.project_id}/interfaces",
        json={"template": "public_chat", "name": "Chat de soporte", "agent": "soporte"},
    )
    assert res.status_code == 201, res.text
    listed = {i["slug"]: i for i in (await client.get(f"/api/v1/projects/{owner.project_id}/interfaces")).json()}
    assert listed["roto"]["valid"] is False
    detail = (await client.get(f"/api/v1/interfaces/{listed['roto']['id']}")).json()
    assert detail["issues"][0]["path"] == "screens"
    await deploy(owner)
    async with system_session() as s:
        rows = {r.slug: r for r in (await s.execute(select(Interface))).scalars()}
    assert rows["roto"].published_definition is None
    assert rows["chat-de-soporte"].published_definition is not None
    base = f"/api/public/v1/apps/{owner.org_slug}/{owner.project_slug}"
    assert (await anon_client.get(f"{base}/roto")).status_code == 404
    assert (await anon_client.get(f"{base}/chat-de-soporte")).status_code == 404  # chats live under /chat
    assert (await anon_client.get(f"/api/public/v1/apps/nadie/{owner.project_slug}/x")).status_code == 404
    schema = await client.get("/api/v1/interfaces/schema")
    assert schema.status_code == 200 and schema.json()["title"] == "Messer interface"
    templates = (await client.get("/api/v1/interfaces/templates")).json()
    assert {t["key"] for t in templates} >= {"blank_app", "table_dashboard", "invoices_dashboard", "public_chat"}
