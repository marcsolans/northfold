"""Phase 4 acceptance: upload 3 PDFs and a CSV, sync a Drive folder (demo), an agent answers citing its sources,
and a SQL query joins a table with documents."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from kb_helpers import ingest_all, make_pdf, multipart

from messer_api.services.connector_syncs import execute_sync
from messer_common.knowledge.sql import run_readonly
from messer_common.settings import reset_settings_cache
from messer_runtime.testing import Harness

PDFS = {
    "condiciones-generales.pdf": [[("Condiciones generales de venta", 18),
                                   ("El plazo de pago de las facturas es de 30 días desde su emisión.", 11)]],
    "politica-abonos.pdf": [[("Política de abonos", 18),
                             ("Los abonos superiores a 500 euros requieren aprobación del responsable.", 11)]],
    "garantias.pdf": [[("Garantías", 18), ("La garantía de los equipos es de dos años.", 11)]],
}
CSV = (b"numero;cliente;importe;estado;documento\n"
       b"F-1001;Acme SL;1.250,00;pendiente;condiciones-generales.pdf\n"
       b"F-1002;Beta SA;320,00;pagada;politica-abonos.pdf\n")


@pytest.fixture
def no_google_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    reset_settings_cache()
    yield
    reset_settings_cache()


async def _sse(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


async def test_phase4_documents_drive_agent_sources_and_join(no_google_app, team, make_kb, as_user,  # type: ignore[no-untyped-def]
                                                             runtime: Harness) -> None:
    # no_google_app resets the settings cache, so it must run before the runtime fixture patches the runtime URL.
    owner = await as_user(team.owner)
    pid = (await owner.post("/api/v1/projects", json={"name": "Atención facturas"})).json()["id"]
    kb = await make_kb(team, name="Facturación", project_id=uuid.UUID(pid))

    # 1. Three PDFs and a CSV.
    files = [(name, make_pdf(pages), "application/pdf") for name, pages in PDFS.items()]
    files.append(("facturas.csv", CSV, "text/csv"))
    res = await owner.post(f"/api/v1/knowledge-bases/{kb.id}/files", files=multipart(*files))
    assert res.status_code == 201, res.text
    assert await ingest_all(kb.id) == ["ready"] * 4

    # 2. A Drive folder through the connector's demo mode.
    started = (await owner.post("/api/v1/connections/oauth/google_drive/start", json={})).json()
    assert started["mode"] == "demo"
    sync = await owner.post("/api/v1/syncs", json={"connection_id": started["connection"]["id"], "kb_id": str(kb.id),
                                                   "resource": "folder:fld-policies", "run_now": True})
    assert sync.status_code == 201, sync.text
    outcome = await execute_sync(uuid.UUID(sync.json()["id"]))
    assert outcome["status"] == "success" and outcome["stats"]["files_ingested"] == 3
    assert set(await ingest_all(kb.id)) == {"ready"}

    # 3. An agent with knowledge search answers and cites the source document.
    created = await owner.post(f"/api/v1/projects/{pid}/workforce", json={"name": "facturas"})
    assert created.status_code == 201, created.text
    agent = created.json()
    cfg = agent["config"]
    cfg["knowledge_bases"] = [str(kb.id)]
    cfg["tools"] = [{"type": "builtin", "key": "knowledge_search"}]
    saved = await owner.put(f"/api/v1/projects/{pid}/workforce/facturas/config", json=cfg)
    assert saved.status_code == 200, saved.text
    events = await _sse(owner, f"/api/v1/projects/{pid}/workforce/facturas/chat",
                        {"message": "¿Qué plazo de pago tienen las facturas según las condiciones?"})
    finished = events[-1]
    assert finished["type"] == "RUN_FINISHED" and finished["status"] == "success", finished
    answer = "".join(e["item"].get("text_delta", "") for e in events
                     if e.get("type") == "DELTA" and isinstance(e.get("item"), dict))
    assert "30 días" in answer and "condiciones-generales.pdf" in answer, answer
    detail = (await owner.get(f"/api/v1/runs/{finished['run_id']}")).json()
    assert any(s["kind"] == "tool" and s["name"] == "knowledge_search" for s in detail["spans"])

    # 4. A query joins the invoices table with the documents.
    joined = await run_readonly(
        kb_id=kb.id,
        sql=("SELECT f.numero, f.importe, d.filename FROM facturas f "
             "JOIN documents d ON d.filename = f.documento WHERE f.estado = 'pendiente'"),
        params=[],
    )
    assert joined.rows == [["F-1001", 1250.0, "condiciones-generales.pdf"]], joined.rows
