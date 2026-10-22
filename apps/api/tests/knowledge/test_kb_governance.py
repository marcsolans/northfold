"""Tables (upsert, types, rows, cells), policies per role, entity resolution and backups."""

from __future__ import annotations

import json
import uuid

import pytest
from kb_helpers import ingest_all, multipart
from sqlalchemy import select, text

from messer_api.services.knowledge import upsert_table
from messer_common.db import system_session
from messer_common.db.models import AuditLog, KbBackup, KbChunk, KbEntity, KbFile, KbPolicy, KbTable
from messer_common.knowledge.errors import KnowledgeError
from messer_common.knowledge.sql import run_readonly

CUSTOMERS = [
    {
        "id": 1,
        "nombre": "Acme Soluciones S.L.",
        "nif": "B-12345678",
        "email": "ana@acme.es",
        "region": "norte",
        "saldo": "1.200,50",
    },
    {
        "id": 2,
        "nombre": "Beta Industrial SA",
        "nif": "A87654321",
        "email": "luis@beta.com",
        "region": "sur",
        "saldo": "300",
    },
    {"id": 3, "nombre": "Gamma Consulting", "nif": None, "email": "eva@gamma.io", "region": "norte", "saldo": "0"},
]
COLUMNS = [
    {"name": "id", "type": "integer", "nullable": False},
    {"name": "nombre", "type": "text", "comment": "Razón social"},
    {"name": "nif", "type": "text"},
    {"name": "email", "type": "text"},
    {"name": "region", "type": "text"},
    {"name": "saldo", "type": "numeric"},
]


async def _customers(team, make_kb):  # type: ignore[no-untyped-def]
    kb = await make_kb(team, name="CRM")
    async with system_session() as s:
        table = await upsert_table(
            s, org_id=team.org_id, kb_id=kb.id, table="Clientes", columns=COLUMNS, rows=CUSTOMERS, primary_key=["id"]
        )
        table_id = table.id
    return kb, table_id


async def test_upsert_table_creates_evolves_and_merges(team, make_kb) -> None:  # type: ignore[no-untyped-def]
    kb, table_id = await _customers(team, make_kb)
    async with system_session() as s:
        table = await s.get(KbTable, table_id)
        assert table is not None and table.name == "clientes" and table.row_count == 3
        assert table.schema_json["primary_key"] == ["id"]
        # Second sync: one updated row, one new row, a new column; invalid value becomes NULL and is counted.
        table = await upsert_table(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            table="clientes",
            columns=[*COLUMNS, {"name": "alta", "type": "date"}],
            rows=[
                {
                    "id": 2,
                    "nombre": "Beta Industrial SA",
                    "nif": "A87654321",
                    "email": "luis@beta.com",
                    "region": "este",
                    "saldo": "abc",
                    "alta": "01/02/2024",
                },
                {
                    "id": 4,
                    "nombre": "Delta",
                    "nif": "ESB99999999",
                    "email": "x@delta.es",
                    "region": "sur",
                    "saldo": 5,
                    "alta": "2024-03-01",
                },
                {"id": None, "nombre": "sin id"},
            ],
            primary_key=["id"],
            source="sync",
        )
        assert table.row_count == 4
        load = table.schema_json["last_load"]
        assert load["rows"] == 2 and load["skipped_rows"] == 1 and load["invalid_values"] == 1
        rows = (
            await s.execute(text(f'SELECT id, region, saldo, alta FROM "{kb.schema_name}".clientes ORDER BY id'))
        ).all()
        assert [(r[0], r[1]) for r in rows] == [(1, "norte"), (2, "este"), (3, "norte"), (4, "sur")]
        assert rows[1][2] is None and str(rows[1][3]) == "2024-02-01"
        with pytest.raises(KnowledgeError) as err:
            await upsert_table(
                s, org_id=team.org_id, kb_id=kb.id, table="clientes", columns=COLUMNS, rows=[], primary_key=["nif"]
            )
        assert err.value.code == "primary_key_mismatch"


async def test_table_rows_api_filter_sort_edit_and_types(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb, table_id = await _customers(team, make_kb)
    viewer = await as_user(team.viewer)
    builder = await as_user(team.builder)
    base = f"/api/v1/knowledge-bases/{kb.id}/tables/{table_id}"
    tables = (await viewer.get(f"/api/v1/knowledge-bases/{kb.id}/tables")).json()
    assert tables[0]["name"] == "clientes" and tables[0]["primary_key"] == ["id"]
    res = await viewer.get(
        f"{base}/rows",
        params={
            "filters": json.dumps([{"column": "region", "op": "eq", "value": "norte"}]),
            "sort": "saldo",
            "order": "desc",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] == 2 and [r[0] for r in body["rows"]] == [1, 3]
    assert [c["name"] for c in body["columns"]][:2] == ["id", "nombre"] and body["columns"][0]["pk"]
    contains = (
        await viewer.get(
            f"{base}/rows", params={"filters": json.dumps([{"column": "nombre", "op": "contains", "value": "beta"}])}
        )
    ).json()
    assert contains["total"] == 1
    paged = (await viewer.get(f"{base}/rows", params={"limit": 2, "offset": 2})).json()
    assert paged["total"] == 3 and [r[0] for r in paged["rows"]] == [3]
    bad = await viewer.get(f"{base}/rows", params={"filters": json.dumps([{"column": "nope", "op": "eq", "value": 1}])})
    assert bad.status_code == 400

    # Cell edits: builders only, by primary key, with type validation and audit.
    assert (
        await viewer.patch(f"{base}/rows", json={"pk": {"id": 1}, "column": "region", "value": "x"})
    ).status_code == 403
    res = await builder.patch(f"{base}/rows", json={"pk": {"id": 1}, "column": "saldo", "value": "2.000,75"})
    assert res.status_code == 200, res.text
    assert res.json()["row"]["saldo"] == 2000.75
    assert (
        await builder.patch(f"{base}/rows", json={"pk": {"id": 99}, "column": "saldo", "value": 1})
    ).status_code == 404
    assert (
        await builder.patch(f"{base}/rows", json={"pk": {"id": 1}, "column": "saldo", "value": "x"})
    ).status_code == 422

    # Type changes: refused when values would be lost unless forced.
    res = await builder.patch(f"{base}/columns/region", json={"type": "integer"})
    assert res.status_code == 422 and res.json()["error"]["details"]["failures"] == 3
    res = await builder.patch(f"{base}/columns/saldo", json={"type": "text"})
    assert res.status_code == 200 and {c["name"]: c["type"] for c in res.json()["columns"]}["saldo"] == "text"
    res = await builder.patch(f"{base}/columns/saldo", json={"type": "numeric"})
    assert res.status_code == 200
    res = await builder.patch(f"{base}/columns/region", json={"type": "integer", "force": True})
    assert res.status_code == 200
    async with system_session() as s:
        actions = {a for (a,) in await s.execute(select(AuditLog.action).where(AuditLog.org_id == team.org_id))}
        assert {"knowledge.table.cell_update", "knowledge.table.alter_type"} <= actions


async def test_csv_upload_creates_editable_table(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb = await make_kb(team)
    builder = await as_user(team.builder)
    csv = b"Codigo Postal,Ciudad,Habitantes\n08001,Barcelona,1620000\n28001,Madrid,3300000\n"
    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/tables", files=multipart(("ciudades.csv", csv, "text/csv"))
    )
    assert res.status_code == 201, res.text
    table = res.json()[0]
    assert {c["name"]: c["type"] for c in table["columns"]} == {
        "codigo_postal": "text",
        "ciudad": "text",
        "habitantes": "integer",
    }
    assert table["row_count"] == 2 and table["primary_key"] == []
    rows = (await builder.get(f"/api/v1/knowledge-bases/{kb.id}/tables/{table['id']}/rows")).json()
    assert rows["columns"][0]["name"] == "_row_id" and rows["rows"][0][1] == "08001"
    res = await builder.patch(
        f"/api/v1/knowledge-bases/{kb.id}/tables/{table['id']}/rows",
        json={"pk": {"_row_id": rows["rows"][0][0]}, "column": "ciudad", "value": "Barna"},
    )
    assert res.status_code == 200 and res.json()["row"]["ciudad"] == "Barna"
    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/tables", files=multipart(("notas.txt", b"x", "text/plain"))
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "not_tabular"


async def test_policies_mask_and_filter_per_role(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb, table_id = await _customers(team, make_kb)
    admin = await as_user(team.admin)
    viewer = await as_user(team.viewer)
    builder = await as_user(team.builder)
    policies = f"/api/v1/knowledge-bases/{kb.id}/policies"
    viewer_policy = {
        "table": "clientes",
        "role": "viewer",
        "row_filter_sql": "region = 'norte'",
        "masked_columns": {"email": "redact", "nif": "truncate:3"},
        "compliance_tags": ["gdpr"],
        "break_glass": True,
    }
    assert (await builder.post(policies, json=viewer_policy)).status_code == 403
    res = await admin.post(policies, json=viewer_policy)
    assert res.status_code == 201, res.text
    agent_policy = {"table": "clientes", "role": "agent", "masked_columns": {"email": "hash"}}
    assert (await admin.post(policies, json=agent_policy)).status_code == 201
    invalid = await admin.post(policies, json={"table": "clientes", "role": "viewer", "row_filter_sql": "nope = 1"})
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "policy_filter"
    invalid = await admin.post(
        policies, json={"table": "clientes", "role": "viewer", "masked_columns": {"x": "redact"}}
    )
    assert invalid.status_code == 422
    invalid = await admin.post(
        policies, json={"table": "clientes", "role": "viewer", "masked_columns": {"email": "rot13"}}
    )
    assert invalid.status_code == 422

    sql = "SELECT id, nif, email FROM clientes ORDER BY id"
    # Governance off: nothing applies.
    raw = await run_readonly(kb_id=kb.id, sql=sql, role="viewer")
    assert len(raw.rows) == 3 and raw.policy is None

    # Shadow: unmasked data, report of what would apply.
    assert (
        await admin.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"governance_mode": "shadow"})
    ).status_code == 200
    shadow = await run_readonly(kb_id=kb.id, sql=sql, role="viewer")
    assert len(shadow.rows) == 3 and shadow.rows[0][2] == "ana@acme.es"
    assert shadow.policy and shadow.policy["would_apply"][0]["masked_columns"] == {
        "email": "redact",
        "nif": "truncate:3",
    }

    # Enforce: viewers get filtered + masked rows, admins raw rows, agents hashed e-mails.
    assert (
        await builder.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"governance_mode": "enforce"})
    ).status_code == 403
    assert (
        await admin.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"governance_mode": "enforce"})
    ).status_code == 200
    as_viewer = await run_readonly(kb_id=kb.id, sql=sql, role="viewer")
    assert as_viewer.rows == [[1, "B-1", "***"], [3, None, "***"]]
    assert as_viewer.policy and as_viewer.policy["applied"][0]["relation"] == "clientes"
    as_admin = await run_readonly(kb_id=kb.id, sql=sql, role="admin")
    assert as_admin.rows[0] == [1, "B-12345678", "ana@acme.es"] and len(as_admin.rows) == 3
    as_agent = await run_readonly(kb_id=kb.id, sql=sql, role=None)
    assert len(as_agent.rows) == 3 and len(as_agent.rows[0][2]) == 16 and as_agent.rows[0][2] != "ana@acme.es"
    # Masked values join consistently (hash is stable) and qualified access is refused.
    with pytest.raises(KnowledgeError) as err:
        await run_readonly(kb_id=kb.id, sql=f"SELECT email FROM {kb.schema_name}.clientes", role="viewer")
    assert err.value.code == "sql_policy"
    # Through the API: the table viewer and the console apply the caller's policies.
    rows = (await viewer.get(f"/api/v1/knowledge-bases/{kb.id}/tables/{table_id}/rows")).json()
    assert rows["total"] == 2 and {c["name"]: c["masked"] for c in rows["columns"]}["email"] is True
    console = (await viewer.post(f"/api/v1/knowledge-bases/{kb.id}/query", json={"sql": sql})).json()
    assert console["rows"][0][2] == "***"

    # Break-glass: admins only, with a reason, audited; bypasses policies that allow it.
    denied = await viewer.post(
        f"/api/v1/knowledge-bases/{kb.id}/query", json={"sql": sql, "break_glass": {"reason": "Auditoría"}}
    )
    assert denied.status_code == 403
    async with system_session() as s:
        policy = (await s.execute(select(KbPolicy).where(KbPolicy.role == "viewer"))).scalar_one()
        policy.role = "admin"  # make the admin subject to the policy to exercise break-glass
    masked_admin = await run_readonly(kb_id=kb.id, sql=sql, role="admin")
    assert masked_admin.rows[0][2] == "***"
    res = await admin.post(
        f"/api/v1/knowledge-bases/{kb.id}/query",
        json={"sql": sql, "break_glass": {"reason": "Requerimiento judicial 42/2026"}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["rows"][0][2] == "ana@acme.es" and res.json()["policy"]["break_glass"] is True
    async with system_session() as s:
        entry = (await s.execute(select(AuditLog).where(AuditLog.action == "knowledge.break_glass"))).scalar_one()
        assert entry.diff["reason"] == "Requerimiento judicial 42/2026" and entry.actor_id == team.admin.id


async def test_document_policies_apply_to_search(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    from messer_common.db import rls_session
    from messer_common.knowledge.search import search

    kb = await make_kb(team)
    builder = await as_user(team.builder)
    admin = await as_user(team.admin)
    await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        files=multipart(
            ("nominas.md", b"# Nominas\n\nEl salario de Ana es confidencial.", "text/markdown"),
            ("publico.md", b"# Publico\n\nEl salario medio del sector es publico.", "text/markdown"),
        ),
    )
    await ingest_all(kb.id)
    res = await admin.post(
        f"/api/v1/knowledge-bases/{kb.id}/policies",
        json={
            "table": "*documents*",
            "role": "agent",
            "row_filter_sql": "filename <> 'nominas.md'",
            "masked_columns": {"filename": "hash"},
        },
    )
    assert res.status_code == 201, res.text
    await admin.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"governance_mode": "enforce"})
    async with rls_session(team.principal("owner")) as db:
        agent_hits = await search(db, kb_id=kb.id, query="salario", mode="keyword", k=5, role=None)
        owner_hits = await search(db, kb_id=kb.id, query="salario", mode="keyword", k=5, role="owner")
    assert len(owner_hits) == 2
    assert len(agent_hits) == 1 and "medio" in agent_hits[0].content and agent_hits[0].filename != "publico.md"
    with pytest.raises(KnowledgeError):
        await run_readonly(
            kb_id=kb.id, sql="SELECT * FROM kb_text_search($1::uuid, 'salario', 5)", params=[str(kb.id)], role=None
        )
    view = await run_readonly(kb_id=kb.id, sql="SELECT content FROM chunks", role=None)
    assert len(view.rows) == 1


async def test_entity_resolution_suggest_merge_dismiss(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    from messer_worker.jobs.knowledge import entity_resolution

    kb, _ = await _customers(team, make_kb)
    async with system_session() as s:
        await upsert_table(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            table="proveedores",
            columns=[
                {"name": "codigo", "type": "text"},
                {"name": "razon_social", "type": "text"},
                {"name": "vat_number", "type": "text"},
                {"name": "web", "type": "text"},
            ],
            rows=[
                {
                    "codigo": "P1",
                    "razon_social": "ACME SOLUCIONES, SL",
                    "vat_number": "ESB12345678",
                    "web": "https://www.acme.es",
                },
                {"codigo": "P2", "razon_social": "Gama Consulting", "vat_number": None, "web": None},
                {"codigo": "P3", "razon_social": "Omega Logística", "vat_number": "FR12345678901", "web": "omega.fr"},
            ],
            primary_key=["codigo"],
        )
    stats = await entity_resolution({}, str(kb.id))
    assert stats["created"] >= 2
    builder = await as_user(team.builder)
    listing = (await builder.get(f"/api/v1/knowledge-bases/{kb.id}/entities")).json()
    by_key = {e["match_key"]: e for e in listing["items"]}
    acme = by_key["tax_id:B12345678"]
    assert acme["method"] == "deterministic" and acme["entity_type"] == "company"
    assert sorted(r["table"] for r in acme["records"]) == ["clientes", "proveedores"]
    similar = next(e for e in listing["items"] if e["method"] == "similarity")
    assert {r["table"] for r in similar["records"]} == {"clientes", "proveedores"} and 0.6 <= similar["score"] < 1
    # Re-running is idempotent.
    again = await entity_resolution({}, str(kb.id))
    assert again["created"] == 0 and again["suggestions"] == stats["suggestions"]

    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/entities/{acme['id']}/merge",
        json={"golden_record": {"nombre": "Acme Soluciones S.L.", "nif": "B12345678", "email": "ana@acme.es"}},
    )
    assert res.status_code == 200, res.text
    merged = res.json()
    assert merged["status"] == "merged" and merged["golden_record"]["fields"]["nif"] == "B12345678"
    assert len(merged["golden_record"]["sources"]) == 2
    assert (await builder.post(f"/api/v1/knowledge-bases/{kb.id}/entities/{acme['id']}/dismiss")).status_code == 409
    res = await builder.post(f"/api/v1/knowledge-bases/{kb.id}/entities/{similar['id']}/dismiss")
    assert res.status_code == 200 and res.json()["status"] == "dismissed"
    golden = await run_readonly(kb_id=kb.id, sql="SELECT match_key, golden_record->'fields'->>'nombre' FROM entities")
    assert golden.rows == [["tax_id:B12345678", "Acme Soluciones S.L."]]
    async with system_session() as s:
        audit = (await s.execute(select(AuditLog).where(AuditLog.action == "knowledge.entity.merge"))).scalar_one()
        assert audit.entity_id == acme["id"] and audit.diff["golden_record"]["fields"]["email"] == "ana@acme.es"
        # Decisions survive a new run.
        await entity_resolution({}, str(kb.id))
        statuses = {e.match_key: e.status for e in (await s.execute(select(KbEntity))).scalars()}
        assert statuses["tax_id:B12345678"] == "merged"


async def test_backup_and_restore_roundtrip(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    from messer_worker.jobs.knowledge import kb_backup, kb_restore

    kb, table_id = await _customers(team, make_kb)
    admin = await as_user(team.admin)
    await admin.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        files=multipart(("faq.md", b"# FAQ\n\nHorario: de 9 a 18 h.", "text/markdown")),
    )
    await ingest_all(kb.id)
    await admin.post(
        f"/api/v1/knowledge-bases/{kb.id}/policies",
        json={"table": "clientes", "role": "viewer", "masked_columns": {"email": "redact"}},
    )
    viewer = await as_user(team.viewer)
    assert (await viewer.post(f"/api/v1/knowledge-bases/{kb.id}/backups")).status_code == 403
    res = await admin.post(f"/api/v1/knowledge-bases/{kb.id}/backups")
    assert res.status_code == 202, res.text
    backup_id = res.json()["id"]
    assert await kb_backup({"job_try": 1}, backup_id) == "ready"
    backups = (await viewer.get(f"/api/v1/knowledge-bases/{kb.id}/backups")).json()
    assert backups[0]["status"] == "ready" and backups[0]["stats"]["rows"] == 3 and backups[0]["stats"]["chunks"] == 1

    async with system_session() as s:
        before_chunks = [
            (c.id, c.content, list(c.embedding))
            for c in (await s.execute(select(KbChunk).where(KbChunk.kb_id == kb.id))).scalars()
        ]
    # Damage the knowledge base: delete the file, change a row, drop the policy.
    files = (await admin.get(f"/api/v1/knowledge-bases/{kb.id}/files")).json()["items"]
    await admin.delete(f"/api/v1/knowledge-bases/{kb.id}/files/{files[0]['id']}")
    await admin.patch(
        f"/api/v1/knowledge-bases/{kb.id}/tables/{table_id}/rows",
        json={"pk": {"id": 1}, "column": "nombre", "value": "Cambiado"},
    )
    policy = (await admin.get(f"/api/v1/knowledge-bases/{kb.id}/policies")).json()[0]
    await admin.delete(f"/api/v1/knowledge-bases/{kb.id}/policies/{policy['id']}")

    res = await admin.post(f"/api/v1/knowledge-bases/{kb.id}/backups/{backup_id}/restore")
    assert res.status_code == 202 and res.json()["status"] == "restoring"
    assert await kb_restore({"job_try": 1}, backup_id) == "restored"

    async with system_session() as s:
        after_chunks = [
            (c.id, c.content, list(c.embedding))
            for c in (await s.execute(select(KbChunk).where(KbChunk.kb_id == kb.id))).scalars()
        ]
        assert after_chunks == before_chunks
        restored = await s.get(KbBackup, uuid.UUID(backup_id))
        assert restored is not None and restored.restored_at is not None
        file = (await s.execute(select(KbFile).where(KbFile.kb_id == kb.id))).scalar_one()
        assert file.filename == "faq.md" and file.meta.get("blob_missing") is True
        assert (await s.execute(select(KbPolicy).where(KbPolicy.kb_id == kb.id))).scalar_one().masked_columns == {
            "email": "redact"
        }
        table = (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalar_one()
        assert table.row_count == 3
    names = await run_readonly(kb_id=kb.id, sql="SELECT nombre FROM clientes ORDER BY id")
    assert names.rows[0] == ["Acme Soluciones S.L."]
    search_after = await run_readonly(
        kb_id=kb.id,
        sql="SELECT filename FROM kb_hybrid_search($1::uuid, 'horario', embed('horario'), 1)",
        params=[str(kb.id)],
    )
    assert search_after.rows == [["faq.md"]]
