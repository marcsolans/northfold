"""Knowledge base lifecycle and ingestion end to end (API upload → worker job → chunks/tables)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from kb_helpers import ingest_all, make_docx, make_pdf, multipart
from sqlalchemy import select, text

from messer_common.db import system_session
from messer_common.db.models import AuditLog, KbChunk, KbFile, KbTable, KnowledgeBase
from messer_common.events import replay

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def test_create_kb_provisions_schema_role_views_and_index(team, as_user) -> None:  # type: ignore[no-untyped-def]
    builder = await as_user(team.builder)
    res = await builder.post("/api/v1/knowledge-bases", json={"name": "Soporte", "embedding_model": "hash-384"})
    assert res.status_code == 201, res.text
    kb = res.json()
    assert kb["embedding_model"] == "hash-384" and kb["embedding_dim"] == 384
    assert kb["stats"]["files"] == 0
    async with system_session() as s:
        row = await s.get(KnowledgeBase, uuid.UUID(kb["id"]))
        assert row is not None
        views = {
            r[0]
            for r in await s.execute(
                text("SELECT table_name FROM information_schema.views WHERE table_schema = :s"), {"s": row.schema_name}
            )
        }
        assert views == {"documents", "chunks", "entities"}
        role = (
            await s.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :r"), {"r": row.reader_role})
        ).first()
        assert role is not None and role[0] is False
        index = (
            await s.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                {"n": "ix_kb_chunks_vec_" + row.schema_name.removeprefix("kb_")},
            )
        ).scalar_one()
        assert "hnsw" in index and "vector(384)" in index and str(row.id) in index
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "knowledge.kb.create"))).scalar_one()
        assert audit.entity_id == kb["id"]

    # Viewers read but cannot create; builders cannot delete; other organizations do not see it.
    viewer = await as_user(team.viewer)
    assert (await viewer.get(f"/api/v1/knowledge-bases/{kb['id']}")).status_code == 200
    assert (await viewer.post("/api/v1/knowledge-bases", json={"name": "X"})).status_code == 403
    assert (await builder.delete(f"/api/v1/knowledge-bases/{kb['id']}")).status_code == 403
    listing = (await viewer.get("/api/v1/knowledge-bases")).json()
    assert [k["id"] for k in listing] == [kb["id"]]
    models = (await viewer.get("/api/v1/knowledge-bases/embedding-models")).json()
    assert any(m["id"] == "hash-384" and m["default"] for m in models)


async def test_delete_kb_drops_everything(team, as_user, make_kb, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    kb = await make_kb(team)
    admin = await as_user(team.admin)
    res = await admin.post(
        f"/api/v1/knowledge-bases/{kb.id}/files", files=multipart(("nota.txt", b"Hola mundo", "text/plain"))
    )
    assert res.status_code == 201, res.text
    outsider_user = await make_user()
    await make_org(owner=outsider_user, name="Otra")
    outsider = await as_user(outsider_user)
    assert (await outsider.get(f"/api/v1/knowledge-bases/{kb.id}")).status_code == 404
    assert (await outsider.delete(f"/api/v1/knowledge-bases/{kb.id}")).status_code in (403, 404)

    assert (await admin.delete(f"/api/v1/knowledge-bases/{kb.id}")).status_code == 204
    async with system_session() as s:
        assert await s.get(KnowledgeBase, kb.id) is None
        schema = (await s.execute(text("SELECT 1 FROM pg_namespace WHERE nspname = :s"), {"s": kb.schema_name})).first()
        role = (await s.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": kb.reader_role})).first()
        index = (
            await s.execute(
                text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": f"ix_kb_chunks_vec_{kb.schema_name[3:]}"}
            )
        ).first()
        assert schema is None and role is None and index is None
        assert (await s.execute(select(KbFile).where(KbFile.kb_id == kb.id))).first() is None


async def test_upload_pdf_docx_csv_and_ingest(team, as_user, make_kb) -> None:  # type: ignore[no-untyped-def]
    kb = await make_kb(team, name="Manuales")
    builder = await as_user(team.builder)
    pdf = make_pdf(
        [
            [
                ("Manual del router X200", 22),
                ("Instalación", 15),
                ("Conecte el cable de alimentación al puerto DC.", 11),
            ],
            [("Garantía", 15), ("La garantía cubre defectos de fabricación durante dos años.", 11)],
        ]
    )
    docx = make_docx(
        [
            ("h1", "Política de devoluciones"),
            ("p", "Los clientes pueden devolver productos en un plazo de 30 días naturales."),
            ("h2", "Excepciones"),
            ("p", "Los productos personalizados no admiten devolución."),
        ]
    )
    csv = b"codigo;cliente;importe;fecha\nF-001;Acme SL;1.250,00;15/01/2026\nF-002;Beta SA;99,90;20/01/2026\n"
    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        files=multipart(
            ("manual.pdf", pdf, PDF_MIME),
            ("devoluciones.docx", docx, DOCX_MIME),
            ("facturas.csv", csv, "text/csv"),
            ("antiguo.doc", b"binary", "application/msword"),
        ),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert [f["status"] for f in body["files"]] == ["queued", "queued", "queued"]
    assert body["errors"][0]["filename"] == "antiguo.doc" and body["errors"][0]["code"] == "unsupported_format"

    assert await ingest_all(kb.id) == ["ready", "ready", "ready"]

    files = (await builder.get(f"/api/v1/knowledge-bases/{kb.id}/files")).json()["items"]
    by_name = {f["filename"]: f for f in files}
    assert by_name["manual.pdf"]["pages"] == 2 and by_name["manual.pdf"]["chunk_count"] >= 1
    assert by_name["devoluciones.docx"]["chunk_count"] >= 1
    assert by_name["facturas.csv"]["chunk_count"] == 0 and by_name["facturas.csv"]["table_id"]

    async with system_session() as s:
        chunks = list(
            (
                await s.execute(
                    select(KbChunk).where(KbChunk.kb_id == kb.id).order_by(KbChunk.file_id, KbChunk.ordinal)
                )
            ).scalars()
        )
        assert all(c.embedding is not None and len(c.embedding) == 384 for c in chunks)
        assert all(c.tsv is not None for c in chunks)
        pdf_chunks = [c for c in chunks if c.file_id == uuid.UUID(by_name["manual.pdf"]["id"])]
        assert pdf_chunks[0].heading and pdf_chunks[0].heading.startswith("Manual del router X200")
        assert {c.page_from for c in pdf_chunks} <= {1, 2} and max(c.page_to or 0 for c in pdf_chunks) == 2
        table = (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalar_one()
        assert table.name == "facturas" and table.row_count == 2
        types = {c["name"]: c["type"] for c in table.schema_json["columns"]}
        assert types == {"codigo": "text", "cliente": "text", "importe": "numeric", "fecha": "date"}
        total = (await s.execute(text(f'SELECT sum(importe) FROM "{kb.schema_name}".facturas'))).scalar_one()
        assert float(total) == 1349.9

    events = await replay(f"kb:{kb.id}")
    statuses = [e["status"] for e in events if e.get("file_id") == by_name["manual.pdf"]["id"]]
    for expected in ("queued", "parsing", "chunking", "embedding", "indexing", "ready"):
        assert expected in statuses
    assert statuses.index("parsing") < statuses.index("embedding") < statuses[::-1].index("ready") + len(statuses)

    # Chunks endpoint, chunk edit (re-embed job) and delete.
    listing = (await builder.get(f"/api/v1/knowledge-bases/{kb.id}/chunks", params={"q": "garantía"})).json()
    assert listing["total"] >= 1
    chunk = listing["items"][0]
    edited = await builder.patch(
        f"/api/v1/knowledge-bases/{kb.id}/chunks/{chunk['id']}", json={"content": "La garantía dura tres años."}
    )
    assert edited.status_code == 200 and edited.json()["metadata"]["reembed_pending"] is True
    from messer_worker.jobs.knowledge import reembed_chunk

    async with system_session() as s:
        before = (await s.get(KbChunk, uuid.UUID(chunk["id"]))).embedding  # type: ignore[union-attr]
    assert await reembed_chunk({}, chunk["id"]) is True
    async with system_session() as s:
        after = await s.get(KbChunk, uuid.UUID(chunk["id"]))
        assert after is not None and list(after.embedding) != list(before)
        assert "reembed_pending" not in after.meta
    viewer = await as_user(team.viewer)
    assert (await viewer.delete(f"/api/v1/knowledge-bases/{kb.id}/chunks/{chunk['id']}")).status_code == 403
    assert (await builder.delete(f"/api/v1/knowledge-bases/{kb.id}/chunks/{chunk['id']}")).status_code == 204

    # Download the original, then delete the CSV: its table goes away too.
    download = await viewer.get(f"/api/v1/knowledge-bases/{kb.id}/files/{by_name['facturas.csv']['id']}/download")
    assert download.status_code == 200 and download.content == csv
    assert (
        await builder.delete(f"/api/v1/knowledge-bases/{kb.id}/files/{by_name['facturas.csv']['id']}")
    ).status_code == 204
    async with system_session() as s:
        assert (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id))).first() is None
        gone = (
            await s.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_schema = :s AND table_name = 'facturas'"),
                {"s": kb.schema_name},
            )
        ).first()
        assert gone is None


async def test_ingest_bytes_external_id_replaces_and_skips_unchanged(team, make_kb) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.knowledge import ingest_bytes

    kb = await make_kb(team)
    async with system_session() as s:
        first = await ingest_bytes(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            filename="a.md",
            data=b"# Uno\n\nTexto",
            mime=None,
            source="connector",
            external_id="drive:1",
        )
    await ingest_all(kb.id)
    async with system_session() as s:
        same = await ingest_bytes(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            filename="a.md",
            data=b"# Uno\n\nTexto",
            mime=None,
            source="connector",
            external_id="drive:1",
        )
        assert same.id == first.id and same.status == "ready"
        changed = await ingest_bytes(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            filename="a-v2.md",
            data=b"# Dos\n\nOtro texto",
            mime=None,
            source="connector",
            external_id="drive:1",
        )
        assert changed.id == first.id and changed.status == "queued" and changed.filename == "a-v2.md"
    assert await ingest_all(kb.id) == ["ready"]
    async with system_session() as s:
        contents = [c.content for c in (await s.execute(select(KbChunk).where(KbChunk.kb_id == kb.id))).scalars()]
        assert contents == ["Otro texto"]
        count = (await s.execute(select(KbFile).where(KbFile.kb_id == kb.id))).all()
        assert len(count) == 1


async def test_upload_limits_and_errors(team, as_user, make_kb, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from messer_common.settings import get_settings

    kb = await make_kb(team)
    builder = await as_user(team.builder)
    monkeypatch.setattr(get_settings(), "messer_kb_max_file_mb", 1)
    big = b"a" * (1024 * 1024 + 10)
    res = await builder.post(f"/api/v1/knowledge-bases/{kb.id}/files", files=multipart(("big.txt", big, "text/plain")))
    assert res.status_code == 413 and res.json()["error"]["code"] == "file_too_large"
    res = await builder.post(f"/api/v1/knowledge-bases/{kb.id}/files", json={"x": 1})
    assert res.status_code == 415
    # A scanned PDF (no text layer) ends in error with a clear message.
    import fitz

    doc = fitz.open()
    doc.new_page()
    empty_pdf = doc.tobytes()
    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/files", files=multipart(("scan.pdf", empty_pdf, PDF_MIME))
    )
    assert res.status_code == 201
    assert await ingest_all(kb.id) == ["error"]
    file = (await builder.get(f"/api/v1/knowledge-bases/{kb.id}/files", params={"status": "error"})).json()["items"][0]
    assert "texto" in file["error"]
    # Reprocess queues it again.
    res = await builder.post(f"/api/v1/knowledge-bases/{kb.id}/files/{file['id']}/reprocess")
    assert res.status_code == 200 and res.json()["status"] == "queued"


async def test_events_stream_replays_status(team, make_kb) -> None:  # type: ignore[no-untyped-def]
    from messer_api.routers.knowledge import kb_event_stream
    from messer_api.services.knowledge.common import publish_kb_event

    kb = await make_kb(team)
    await publish_kb_event(kb.id, {"type": "file", "file_id": "f1", "status": "parsing"})
    stream: Any = kb_event_stream(kb.id)
    first = await asyncio.wait_for(anext(stream), timeout=5)
    assert first["event"] == "file" and '"parsing"' in first["data"]
    await stream.aclose()


async def test_ready_file_emits_workflow_trigger_event(team, make_kb, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.knowledge import ingest_bytes
    from messer_common import triggers

    calls: list[dict[str, Any]] = []

    async def fake_emit(session: Any, **kwargs: Any) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(triggers, "emit", fake_emit)
    kb = await make_kb(team)
    async with system_session() as s:
        record = await ingest_bytes(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            filename="aviso.md",
            data=b"# Aviso\n\nTexto",
            mime=None,
            source="upload",
        )
        bad = await ingest_bytes(
            s, org_id=team.org_id, kb_id=kb.id, filename="vacio.csv", data=b"\n\n", mime="text/csv", source="upload"
        )
    assert sorted(await ingest_all(kb.id)) == ["error", "ready"]
    assert len(calls) == 1  # only files that finished ingesting successfully
    call = calls[0]
    assert call["event"] == "kb.file_uploaded" and call["org_id"] == team.org_id and call["kb_id"] == kb.id
    assert call["event_id"] == str(record.id) and call["event_id"] != str(bad.id)
    assert call["payload"] == {
        "kb_id": str(kb.id),
        "file_id": str(record.id),
        "filename": "aviso.md",
        "mime": "text/markdown",
        "source": "upload",
    }
