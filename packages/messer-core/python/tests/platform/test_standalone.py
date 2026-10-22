# Added by Messer: tests for the standalone platform of exported projects (see NOTICE).
"""The standalone platform (``python -m messer.platform.standalone``) serves an exported project's members:
knowledge search over JSONL chunks, read-only SQL over CSV tables, tracing to JSONL, the model proxy (Anthropic or
the offline echo model), email, files and a clear error for connector actions."""

from __future__ import annotations

import asyncio
import csv
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from messer.platform.standalone import StandaloneConfig
from messer.platform.standalone.app import create_app
from messer.platform.standalone.knowledge import KnowledgeError, check_select, tokenize
from messer.platform.standalone.models import OFFLINE_NOTICE

ORG = "11111111-1111-1111-1111-111111111111"
PROJECT = "22222222-2222-2222-2222-222222222222"
KB = "33333333-3333-3333-3333-333333333333"
TOKEN = "standalone-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}

CHUNKS = [
    {
        "id": "c1",
        "file_id": "f1",
        "filename": "condiciones.pdf",
        "ordinal": 0,
        "heading": "Pagos",
        "content": "El plazo de pago de las facturas es de 30 días desde la fecha de emisión.",
        "page_from": 2,
        "page_to": 2,
        "metadata": {"lang": "es"},
    },
    {
        "id": "c2",
        "file_id": "f1",
        "filename": "condiciones.pdf",
        "ordinal": 1,
        "heading": "Devoluciones",
        "content": "Las devoluciones se aceptan durante 14 días si el producto no se ha usado.",
        "page_from": 3,
        "page_to": 3,
        "metadata": {},
    },
    {
        "id": "c3",
        "file_id": "f2",
        "filename": "faq.md",
        "ordinal": 0,
        "heading": None,
        "content": "Nuestro horario de atención es de lunes a viernes de 9 a 18 h.",
        "page_from": None,
        "page_to": None,
        "metadata": {},
    },
]


def write_export(root: Path) -> Path:
    data = root / "data"
    kb_dir = data / "knowledge" / KB
    (kb_dir / "tables").mkdir(parents=True)
    (data / "knowledge" / "index.json").write_text(
        json.dumps({"knowledge_bases": [{"id": KB, "name": "Facturación", "description": "Condiciones y facturas"}]})
    )
    (kb_dir / "kb.json").write_text(
        json.dumps(
            {
                "id": KB,
                "name": "Facturación",
                "files": [{"id": "f1", "filename": "condiciones.pdf"}, {"id": "f2", "filename": "faq.md"}],
                "tables": [{"name": "facturas", "row_count": 3}],
            }
        )
    )
    with (kb_dir / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in CHUNKS:
            fh.write(json.dumps(chunk, ensure_ascii=False) + "\n")
    schema = {
        "name": "facturas",
        "columns": [
            {"name": "_row_id", "type": "integer"},
            {"name": "numero", "type": "text"},
            {"name": "cliente", "type": "text"},
            {"name": "importe", "type": "numeric"},
            {"name": "pagada", "type": "boolean"},
            {"name": "emitida", "type": "date"},
        ],
        "primary_key": ["_row_id"],
    }
    (kb_dir / "tables" / "facturas.schema.json").write_text(json.dumps(schema))
    with (kb_dir / "tables" / "facturas.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["_row_id", "numero", "cliente", "importe", "pagada", "emitida"])
        w.writerow([1, "F-2025-001", "Acme", "120.50", "true", "2025-01-10"])
        w.writerow([2, "F-2025-002", "Globex", "980", "false", "2025-02-01"])
        w.writerow([3, "F-2025-003", "acme industrial", "", "false", ""])
    (root / "messer-export.json").write_text(
        json.dumps({"project": {"id": PROJECT, "name": "Soporte"}, "members": [{"name": "soporte", "port": 8001}]})
    )
    return data


def make_config(tmp_path: Path, **overrides: Any) -> StandaloneConfig:
    data = write_export(tmp_path)
    values: dict[str, Any] = {
        "data_dir": data,
        "state_dir": tmp_path / "state",
        "token": TOKEN,
        "org_id": ORG,
        "project_id": PROJECT,
        "manifest_path": tmp_path / "messer-export.json",
        "public_url": "http://platform:8000",
    }
    values.update(overrides)
    return StandaloneConfig(**values)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(make_config(tmp_path)))


def test_tokenize_stems_spanish_plurals_and_accents() -> None:
    assert tokenize("Facturas") == tokenize("factura")
    assert tokenize("condiciones") == tokenize("Condición")
    assert tokenize("a 30 días") == ["30", "dia"]


def test_auth_and_scope(client: TestClient) -> None:
    assert client.get("/healthcheck").json() == {"ok": True}
    assert client.get("/").status_code == 401
    assert client.get("/", headers={"Authorization": "Bearer wrong"}).status_code == 401
    # The Anthropic SDK sends the platform credential as x-api-key: "Bearer <token>".
    info = client.get("/", headers={"x-api-key": f"Bearer {TOKEN}"})
    assert info.status_code == 200
    assert info.json()["model"] == "offline" and info.json()["knowledge_bases"][0]["id"] == KB
    assert info.json()["members"] == [{"name": "soporte", "port": 8001}]
    other = client.post(f"/orgs/{'9' * 8}/knowledge-bases/{KB}/search", json={"query": "pago"}, headers=AUTH)
    assert other.status_code == 404


def test_knowledge_search_bm25(client: TestClient) -> None:
    res = client.post(
        f"/orgs/{ORG}/knowledge-bases/{KB}/search", json={"query": "¿Cuál es el plazo de pago?", "k": 2}, headers=AUTH
    )
    assert res.status_code == 200, res.text
    hits = res.json()["hits"]
    assert hits[0]["chunk_id"] == "c1" and hits[0]["filename"] == "condiciones.pdf" and hits[0]["page_from"] == 2
    assert set(hits[0]) == {
        "chunk_id",
        "file_id",
        "filename",
        "content",
        "heading",
        "page_from",
        "page_to",
        "score",
        "metadata",
    }
    assert hits[0]["score"] > 0 and len(hits) <= 2
    devol = client.post(f"/orgs/{ORG}/knowledge-bases/{KB}/search", json={"query": "devolución producto"}, headers=AUTH)
    assert devol.json()["hits"][0]["chunk_id"] == "c2"
    none = client.post(f"/orgs/{ORG}/knowledge-bases/{KB}/search", json={"query": "zzzz"}, headers=AUTH)
    assert none.json()["hits"] == []
    missing = client.post(f"/orgs/{ORG}/knowledge-bases/../../etc/search", json={"query": "x"}, headers=AUTH)
    assert missing.status_code == 404


def test_read_only_sql(client: TestClient) -> None:
    url = f"/orgs/{ORG}/knowledge-bases/{KB}/query"
    res = client.post(
        url,
        json={
            "sql": "SELECT numero, importe, pagada FROM facturas WHERE importe > $1 ORDER BY importe",
            "params": [100],
        },
        headers=AUTH,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["columns"] == ["numero", "importe", "pagada"]
    assert body["rows"] == [["F-2025-001", 120.5, 1], ["F-2025-002", 980.0, 0]]
    assert body["column_types"] == ["text", "numeric", "integer"] and body["row_count"] == 2
    assert body["truncated"] is False
    ilike = client.post(
        url,
        json={
            "sql": "WITH a AS (SELECT * FROM facturas) SELECT count(*) AS n FROM a "
            "WHERE cliente ILIKE 'ACME%' -- comment"
        },
        headers=AUTH,
    )
    assert ilike.json()["rows"] == [[2]]
    nulls = client.post(url, json={"sql": "SELECT importe, emitida FROM facturas WHERE _row_id = 3"}, headers=AUTH)
    assert nulls.json()["rows"] == [[None, None]]
    for sql, code in [
        ("DELETE FROM facturas", "read_only"),
        ("UPDATE facturas SET importe = 0", "read_only"),
        ("PRAGMA table_info(facturas)", "read_only"),
        ("SELECT 1; DROP TABLE facturas", "multiple_statements"),
        ("  ", "empty_sql"),
        ("SELECT load_extension('evil')", "read_only"),
        ("SELECT * FROM nope", "sql_error"),
    ]:
        bad = client.post(url, json={"sql": sql}, headers=AUTH)
        assert bad.status_code == 400, (sql, bad.text)
        assert bad.json()["error"]["type"] == code, (sql, bad.json())
    # Strings may contain semicolons and "$1"; only real parameters are rewritten.
    assert check_select("SELECT ';' AS a, '$1' AS b WHERE x = $2") == "SELECT ';' AS a, '$1' AS b WHERE x = ?2"
    with pytest.raises(KnowledgeError):
        check_select("ATTACH DATABASE 'x' AS y")
    still = client.post(url, json={"sql": "SELECT count(*) FROM facturas"}, headers=AUTH)
    assert still.json()["rows"] == [[3]]


def test_tracing_roundtrip(client: TestClient, tmp_path: Path) -> None:
    run = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"
    url = f"/orgs/{ORG}/projects/{PROJECT}/runs/{run}"
    assert client.get(url, headers=AUTH).json() == {"trace": None}
    trace = [{"path": "soporte", "input": {"prompt": "hola"}, "output": "¡Hola!"}]
    assert client.patch(url, json={"parent_id": None, "trace": trace}, headers=AUTH).status_code == 204
    assert client.get(url, headers=AUTH).json() == {"trace": trace}
    log_lines = (tmp_path / "state" / "traces" / "traces.jsonl").read_text().splitlines()
    assert json.loads(log_lines[0])["run_id"] == run
    assert client.get("/traces", headers=AUTH).json()["runs"][0]["run_id"] == run
    assert client.patch(f"/orgs/{ORG}/projects/{PROJECT}/runs/..%2Fx", json={}, headers=AUTH).status_code in (400, 404)
    assert client.get(f"/orgs/{ORG}/projects/other/runs/{run}", headers=AUTH).status_code == 404


def test_offline_model(client: TestClient) -> None:
    url = f"/orgs/{ORG}/proxies/anthropic/v1/messages"
    tools = [{"name": "knowledge_search", "description": "Busca", "input_schema": {"type": "object"}}]
    first = client.post(
        url,
        json={
            "model": "claude-sonnet-5-5",
            "max_tokens": 100,
            "tools": tools,
            "messages": [{"role": "user", "content": "¿Plazo de pago?"}],
        },
        headers=AUTH,
    )
    assert first.status_code == 200
    block = first.json()["content"][0]
    assert first.json()["stop_reason"] == "tool_use" and block["name"] == "knowledge_search"
    assert block["input"] == {"query": "¿Plazo de pago?"}
    result = json.dumps({"results": [{"content": "30 días", "source": "condiciones.pdf", "pages": [2, 2]}]})
    second = client.post(
        url,
        json={
            "model": "x",
            "max_tokens": 100,
            "tools": tools,
            "messages": [
                {"role": "user", "content": "¿Plazo de pago?"},
                {"role": "assistant", "content": [block]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": block["id"], "content": result}]},
            ],
        },
        headers=AUTH,
    )
    text = second.json()["content"][0]["text"]
    assert "30 días (condiciones.pdf, p. 2)" in text and OFFLINE_NOTICE in text
    echo = client.post(
        url,
        json={
            "model": "x",
            "max_tokens": 10,
            "stream": True,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Hola"}]}],
        },
        headers=AUTH,
    )
    assert echo.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in echo.text.splitlines() if line.startswith("data: ")]
    assert [e["type"] for e in events][0] == "message_start" and events[-1]["type"] == "message_stop"
    streamed = "".join(e["delta"]["text"] for e in events if e["type"] == "content_block_delta")
    assert streamed.startswith("Echo: Hola") and OFFLINE_NOTICE in streamed
    count = client.post(
        f"{url}/count_tokens", json={"messages": [{"role": "user", "content": "x" * 400}]}, headers=AUTH
    )
    assert count.json()["input_tokens"] > 50
    other = client.post(f"/orgs/{ORG}/proxies/openai-completions/chat/completions", json={}, headers=AUTH)
    assert other.status_code == 422 and other.json()["error"]["type"] == "not_available_in_export"


def test_anthropic_forwarding(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if body.get("stream"):
            return httpx.Response(
                200,
                content=b'event: message_stop\ndata: {"type": "message_stop"}\n\n',
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json={"id": "msg_1", "type": "message", "content": [{"type": "text", "text": "ok"}]})

    app = create_app(
        make_config(tmp_path, anthropic_api_key="sk-ant-test", anthropic_base_url="https://anthropic.test"),
        anthropic_transport=httpx.MockTransport(upstream),
    )
    client = TestClient(app)
    url = f"/orgs/{ORG}/proxies/anthropic/v1/messages"
    res = client.post(
        url,
        json={"model": "claude-sonnet-5-5", "max_tokens": 5, "messages": []},
        headers={**AUTH, "anthropic-version": "2023-06-01", "anthropic-beta": "tools-2024"},
    )
    assert res.json()["content"][0]["text"] == "ok"
    assert str(seen[0].url) == "https://anthropic.test/v1/messages"
    assert seen[0].headers["x-api-key"] == "sk-ant-test" and seen[0].headers["anthropic-beta"] == "tools-2024"
    assert "authorization" not in seen[0].headers  # the local token never leaves the export
    streamed = client.post(url, json={"model": "m", "max_tokens": 5, "messages": [], "stream": True}, headers=AUTH)
    assert "message_stop" in streamed.text and streamed.headers["content-type"].startswith("text/event-stream")
    assert client.get("/", headers=AUTH).json()["model"] == "anthropic"


def test_email_files_and_connectors(client: TestClient, tmp_path: Path) -> None:
    mail = client.post(
        f"/orgs/{ORG}/proxies/v1/tools/send_email",
        json={"to": "ana@example.com", "subject": "Factura", "body": "Adjunta"},
        headers=AUTH,
    )
    assert mail.status_code == 200, mail.text
    assert mail.json()["output"]["delivery"] == "log" and mail.json()["output"]["sent"] is False
    outbox = [json.loads(x) for x in (tmp_path / "state" / "outbox.jsonl").read_text().splitlines()]
    assert outbox[0]["to"] == "ana@example.com" and outbox[0]["subject"] == "Factura"
    bad = client.post(f"/orgs/{ORG}/proxies/v1/tools/send_email", json={"to": "x"}, headers=AUTH)
    assert bad.status_code == 422
    assert client.post(f"/orgs/{ORG}/proxies/v1/tools/unknown", json={}, headers=AUTH).status_code == 404

    up = client.post("/files", files={"file": ("informe final.txt", b"hola", "text/plain")}, headers=AUTH)
    assert up.status_code == 200, up.text
    meta = up.json()
    assert meta["name"] == "informe_final.txt" and meta["content_length"] == 4
    assert meta["url"].startswith("http://platform:8000/files/")
    down = client.get(f"/files/{meta['id']}")
    assert down.status_code == 200 and down.content == b"hola"
    assert client.get("/files/../../etc/passwd").status_code == 404
    assert client.post("/files", files={"file": ("x.txt", b"x", "text/plain")}).status_code == 401

    action = client.post(f"/orgs/{ORG}/connections/abc/actions/send_message", json={"args": {}}, headers=AUTH)
    assert action.status_code == 422 and action.json()["error"]["type"] == "not_available_in_export"
    assert "no están disponibles en el proyecto exportado" in action.json()["error"]["message"]
    creds = client.get(f"/orgs/{ORG}/connections/abc/credentials", headers=AUTH)
    assert creds.status_code == 422


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_engine_agent_against_standalone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real engine Agent uses the standalone platform for its model (offline), knowledge and tracing."""
    import messer.state.config_loader as config_loader
    import uvicorn
    from messer import Agent
    from messer.core.llm import clients
    from messer.platform.tools import knowledge_search

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(make_config(tmp_path)), host="127.0.0.1", port=port, log_level="warning", lifespan="off"
        )
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MESSER_API_HOST", f"http://127.0.0.1:{port}/")
    monkeypatch.setenv("MESSER_API_KEY", TOKEN)
    monkeypatch.setenv("MESSER_ORG_ID", ORG)
    monkeypatch.setenv("MESSER_PROJECT_ID", PROJECT)
    monkeypatch.setattr(config_loader, "_cached_default_config", None)
    monkeypatch.setattr(config_loader, "_default_config_resolved", False)
    monkeypatch.setattr(clients, "_CLIENT_CACHE", {})
    try:
        agent = Agent(
            name="soporte",
            model="anthropic/claude-sonnet-4-6",
            max_tokens=512,
            tools=[knowledge_search(kb_ids=[KB])],
            system_prompt="Responde con las fuentes.",
        )
        result = await agent(prompt="¿Cuál es el plazo de pago de las facturas?").collect()
        assert result.status.code == "success", result.error
        text = result.output.collect_text()
        assert "30 días" in text and "condiciones.pdf" in text and OFFLINE_NOTICE in text
        stored = list((tmp_path / "state" / "traces" / "runs").glob("*.json"))
        assert stored, "the run trace is stored by the platform tracing provider"
    finally:
        server.should_exit = True
        await task
