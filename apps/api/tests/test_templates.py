"""Industry templates: catalog files, public API, cloning into a ready-to-run project and its evals (phase 9)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from messer_api.services import templates_catalog as catalog
from messer_common.composer.plan import validate_plan
from messer_common.db import system_session
from messer_common.db.models import Approval, Channel, KnowledgeBase, Project, Trigger, Workforce
from messer_common.projects_repo import ProjectRepo
from messer_runtime.testing import Harness

PASSWORD = "Sup3rSecret!pass"
TEMPLATE_IDS = [
    "invoice-support",
    "lead-qualification",
    "document-extraction",
    "hr-assistant",
    "contract-analysis",
    "orders-stock",
    "phone-receptionist",
    "weekly-sales-report",
]


async def _owner_client(client: httpx.AsyncClient, make_user, make_org) -> tuple[httpx.AsyncClient, uuid.UUID]:  # type: ignore[no-untyped-def]
    owner = await make_user(email=f"owner-{uuid.uuid4().hex[:6]}@acme.example")
    org, _ = await make_org(owner=owner, name=f"Acme {uuid.uuid4().hex[:4]}")
    res = await client.post("/api/v1/auth/login", json={"email": owner.email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    client.headers["X-Messer-Org"] = str(org.id)
    return client, org.id


async def ingest_project_files(project_id: uuid.UUID) -> list[str]:
    """Run the ingestion job for every queued file of the project's knowledge bases (no worker in tests)."""
    from messer_worker.jobs.knowledge import ingest_file

    async with system_session() as s:
        rows = await s.execute(
            text(
                "SELECT f.id FROM public.kb_files f JOIN public.knowledge_bases k ON k.id = f.kb_id "
                "WHERE k.project_id = :p AND f.status = 'queued' ORDER BY f.created_at"
            ),
            {"p": project_id},
        )
        ids = [str(r[0]) for r in rows]
    return [await ingest_file({"job_try": 1}, file_id) for file_id in ids]


async def _clone(client: httpx.AsyncClient, template_id: str, name: str | None = None) -> dict[str, Any]:
    res = await client.post(f"/api/v1/templates/{template_id}/clone", json={"name": name or f"Demo {template_id}"})
    assert res.status_code == 201, res.text
    return res.json()


async def _run_evals(client: httpx.AsyncClient, project_id: str, member: str) -> dict[str, Any]:
    res = await client.post(f"/api/v1/projects/{project_id}/workforce/{member}/evals", json={})
    assert res.status_code == 201, res.text
    return res.json()


async def _sse(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body, timeout=180) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def _failures(result: dict[str, Any]) -> list[Any]:
    return [r for r in result["results"] if not r.get("passed", r.get("status") == "passed")]


# ============================================================================================ catalog files


def test_every_template_loads_and_validates() -> None:
    catalog.reset_cache()
    assert catalog.load_errors() == {}
    assert [t.id for t in catalog.all_templates()] == TEMPLATE_IDS


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_plan_json_validates_against_the_composer_schema(template_id: str) -> None:
    root = catalog.templates_dir() / template_id
    plan, issues = validate_plan(json.loads((root / "plan.json").read_text(encoding="utf-8")))
    assert issues == [] and plan is not None
    assert plan.template_id == template_id
    template = catalog.get_template(template_id)
    assert template is not None
    members = {m.name for m in template.members}
    assert {a.name for a in plan.agents} | {w.name for w in plan.workflows} == members


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_template_shape(template_id: str) -> None:
    """Spec 8.4: agents, workflows, a sample knowledge base, an interface and evals (offline ones pass in demo)."""
    template = catalog.get_template(template_id)
    assert template is not None
    summary = template.summary
    assert summary["agents"], "an agent"
    assert summary["workflows"], "a workflow"
    assert summary["knowledge_bases"] and any(kb["documents"] or kb["tables"] for kb in summary["knowledge_bases"])
    assert summary["interfaces"]
    for member in template.members:
        tags = [e["tags"] for e in summary["evals"] if e["member"] == member.name]
        assert any(catalog.OFFLINE_EVAL_TAG in t for t in tags), member.name
    for kb in template.manifest.knowledge_bases:
        for doc in kb.documents:
            assert (template.root / doc.source).stat().st_size < 300_000


def test_sample_documents_render_as_labelled_pdfs() -> None:
    import fitz

    from messer_api.services.templates import SAMPLE_LABEL, render_document

    template = catalog.get_template("invoice-support")
    assert template is not None
    for doc in template.manifest.knowledge_bases[0].documents:
        data, mime = render_document(template, doc)
        assert mime == "application/pdf" and len(data) < 300_000
        pdf: Any = fitz.open("pdf", data)
        first = pdf[0].get_text()
        assert SAMPLE_LABEL.upper() in first and doc.title in first
        pdf.close()


def test_match_template_for_section_13_request() -> None:
    es = (
        "Quiero un asistente que responda a las preguntas de los clientes sobre sus facturas usando nuestros PDF de "
        "condiciones y una tabla de facturas, que pida aprobación humana antes de emitir un abono de más de 500 €, "
        "que también atienda por WhatsApp y teléfono, y un panel con las facturas pendientes y las consultas del mes."
    )
    en = (
        "I want an assistant that answers customer questions about their invoices using our terms-and-conditions "
        "PDFs and an invoices table, that asks for human approval before issuing a credit note over €500, that also "
        "handles WhatsApp and phone, and a dashboard with pending invoices and this month's queries."
    )
    assert catalog.match_template(es) == "invoice-support"
    assert catalog.match_template(en) == "invoice-support"
    assert catalog.match_template("Quiero extraer los datos de los albaranes de proveedores a una tabla") == (
        "document-extraction"
    )
    assert catalog.match_template("Un asistente de RR. HH. para el convenio colectivo y las vacaciones") == (
        "hr-assistant"
    )
    assert catalog.match_template("Hola") is None


# ============================================================================================ public API


async def test_public_catalog_and_detail(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/templates")
    assert res.status_code == 200, res.text
    data = res.json()
    assert [i["id"] for i in data["items"]] == TEMPLATE_IDS
    first = data["items"][0]
    assert first["name"] == "Atención al cliente sobre facturas" and first["name_en"]
    assert first["voice"] is True and first["approvals"] is True and first["counts"]["documents"] >= 2
    assert {s["key"] for s in data["sectors"]} >= {"finance", "sales", "hr", "legal"}
    filtered = (await client.get("/api/v1/templates", params={"sector": "legal"})).json()
    assert [i["id"] for i in filtered["items"]] == ["contract-analysis"]

    detail = (await client.get("/api/v1/templates/invoice-support")).json()
    assert detail["agents"][0]["voice"] is True and detail["agents"][0]["greeting"]
    assert any(a == "Aprobación de administración" for a in detail["workflows"][0]["approvals"])
    assert detail["plan"]["template_id"] == "invoice-support"
    assert "workforce/asistente_facturas/tools.py" in detail["files"]
    assert (await client.get("/api/v1/templates/nope")).status_code == 404

    match = (await client.get("/api/v1/templates/match", params={"text": "abonos de facturas"})).json()
    assert match["template_id"] == "invoice-support"


async def test_private_templates_are_hidden_and_seeding_keeps_backoffice_settings(client: httpx.AsyncClient) -> None:
    from messer_common.db.models import Template

    async with system_session() as s:
        row = await s.get(Template, "orders-stock")
        assert row is not None
        row.public, row.sort_order = False, 999
    try:
        ids = [i["id"] for i in (await client.get("/api/v1/templates")).json()["items"]]
        assert "orders-stock" not in ids
        assert (await client.get("/api/v1/templates/orders-stock")).status_code == 404
        async with system_session() as s:
            await catalog.seed_templates(s)
        async with system_session() as s:
            again = await s.get(Template, "orders-stock")
            assert again is not None and again.public is False and again.sort_order == 999
    finally:
        async with system_session() as s:
            row = await s.get(Template, "orders-stock")
            assert row is not None
            row.public, row.sort_order = True, 60


async def test_clone_requires_builder(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user(email="viewer-tpl@acme.example")
    org, _ = await make_org(members={str(viewer.id): "viewer"})
    assert (
        await client.post("/api/v1/auth/login", json={"email": viewer.email, "password": PASSWORD})
    ).status_code == 200
    client.headers["X-Messer-Org"] = str(org.id)
    res = await client.post("/api/v1/templates/invoice-support/clone", json={"name": "No"})
    assert res.status_code == 403


# ============================================================================================ cloning


async def test_clone_invoice_support_end_to_end(
    client: httpx.AsyncClient, make_user, make_org, runtime: Harness
) -> None:  # type: ignore[no-untyped-def]
    """Template 1 = spec section 13: voice agent, credit-note approval above 500 €, PDFs + table, dashboard,
    WhatsApp (demo) and phone, passing evals."""
    client, org_id = await _owner_client(client, make_user, make_org)
    cloned = await _clone(client, "invoice-support", "Atención facturas")
    pid = cloned["project"]["id"]
    assert cloned["project"]["template_id"] == "invoice-support" and cloned["url"] == f"/app/projects/{pid}"
    assert {m["name"] for m in cloned["members"]} == {"asistente_facturas", "abono_factura"}
    assert sorted(cloned["interfaces"]) == ["chat-facturas", "panel-facturas"]
    kb = cloned["knowledge_bases"][0]
    assert len(kb["documents"]) == 3 and {t["name"] for t in kb["tables"]} == {"facturas", "consultas"}
    assert [c["provider"] for c in cloned["channels"]] == ["whatsapp"] and cloned["channels"][0]["demo"] is True
    assert cloned["triggers"][0]["kind"] == "webhook" and cloned["triggers"][0]["secret"].startswith("whsec_")
    assert any(n["code"] == "phone" for n in cloned["notes"])
    assert await ingest_project_files(uuid.UUID(pid)) == ["ready"] * 3

    async with system_session() as s:
        project = await s.get(Project, uuid.UUID(pid))
        assert project is not None and project.org_id == org_id
        members = {w.name: w for w in (await s.execute(select(Workforce).where(Workforce.project_id == project.id))).scalars()}
        agent_cfg = members["asistente_facturas"].config_json
        assert agent_cfg["voice"]["enabled"] is True and agent_cfg["voice"]["greeting"]
        assert agent_cfg["knowledge_bases"] == [kb["id"]]
        kb_row = await s.get(KnowledgeBase, uuid.UUID(kb["id"]))
        assert kb_row is not None and kb_row.project_id == project.id
        assert (await s.execute(select(Channel).where(Channel.project_id == project.id))).scalars().one().demo
        assert (await s.execute(select(Trigger).where(Trigger.project_id == project.id))).scalars().one().enabled
    repo = ProjectRepo.for_project(pid)
    files = await repo.list_files()
    assert "workforce/asistente_facturas/tools.py" in files and "workforce/abono_factura/layout.json" in files
    assert kb["id"] in (await repo.read("workforce/asistente_facturas/tools.py") or "")
    assert "${" not in (await repo.read("interfaces/panel-facturas/interface.json") or "")
    knowledge_yaml = await repo.read("knowledge.yaml") or ""
    assert kb["id"] in knowledge_yaml

    # Evals of every member pass with the offline demo model (llm-judged ones are skipped without a key).
    for member in ("asistente_facturas", "abono_factura"):
        result = await _run_evals(client, pid, member)
        assert result["status"] == "passed", json.dumps(result, ensure_ascii=False)[:4000]
        assert result["passed"] >= 3 and result["failed"] == 0

    # A credit note of 900 € waits for approval; 200 € is issued at once.
    chat = f"/api/v1/projects/{pid}/workforce/asistente_facturas/chat"
    big = await _sse(client, chat, {"message": "Quiero emitir un abono de 900 € en la factura F-2026-0137 por «cobro duplicado»"})
    finished = big[-1]
    assert finished["type"] == "RUN_FINISHED" and finished["status"] == "paused", finished
    assert any(e.get("type") == "APPROVAL" for e in big)
    async with system_session() as s:
        approval = (await s.execute(select(Approval).where(Approval.project_id == uuid.UUID(pid)))).scalars().one()
        assert approval.tool_name == "emitir_abono" and approval.assigned_role == "admin"
        assert approval.payload["importe"] == 900
    small = await _sse(client, chat, {"message": "Quiero emitir un abono de 200 € en la factura F-2026-0129 por «error en el precio»"})
    assert small[-1]["status"] == "success", small[-1]
    assert not any(e.get("type") == "APPROVAL" for e in small)
    answer = "".join(e["item"].get("text_delta", "") for e in small if e.get("type") == "DELTA" and isinstance(e.get("item"), dict))
    assert "AB-2026-0129" in answer

    # The decision resumes the run and issues the credit note.
    resumed = await _sse(
        client, f"/api/v1/approvals/{approval.id}/decision?stream=true", {"decision": "approve", "comment": "OK"}
    )
    assert resumed[-1]["status"] == "success", resumed[-1]

    # The dashboard's data endpoints return rows (pending invoices, this month's queries by channel).
    listed = (await client.get(f"/api/v1/projects/{pid}/interfaces")).json()
    panel = next(i for i in listed if i["slug"] == "panel-facturas")
    table = await client.post(f"/api/v1/interfaces/{panel['id']}/components/tabla-pendientes/data", json={})
    assert table.status_code == 200, table.text
    rows = table.json()["rows"]
    assert rows and {"numero", "cliente", "importe", "estado"} <= set(rows[0])
    assert {r["estado"] for r in rows} <= {"pendiente", "vencida"}
    month = await client.post(f"/api/v1/interfaces/{panel['id']}/components/kpi-consultas-mes/data", json={})
    assert month.status_code == 200 and int(month.json()["rows"][0]["consultas"]) > 0, month.text
    chart = await client.post(f"/api/v1/interfaces/{panel['id']}/components/grafico-consultas/data", json={})
    assert chart.status_code == 200 and chart.json()["rows"], chart.text

    # The credit-note workflow pauses above 500 € and runs straight through below.
    wf = f"/api/v1/projects/{pid}/workflows/abono_factura/run"
    paused = await _sse(client, wf, {"input": {"numero_factura": "F-2026-0142", "importe": 800, "motivo": "Error"}})
    assert paused[-1]["status"] == "paused", paused[-1]
    direct = await _sse(client, wf, {"input": {"numero_factura": "F-2026-0142", "importe": 80, "motivo": "Error"}})
    assert direct[-1]["status"] == "success", direct[-1]
