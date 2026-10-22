"""Search (vector, keyword, hybrid) and the read-only SQL console: rules, scope, limits, embed(), joins."""

from __future__ import annotations

import pytest
from kb_helpers import ingest_all, multipart
from sqlalchemy import select, text

from messer_api.services.knowledge import upsert_table
from messer_common.db import rls_session, system_session
from messer_common.db.models import KbChunk
from messer_common.knowledge.errors import SqlExecutionError, SqlRejected, SqlTimeout
from messer_common.knowledge.search import search
from messer_common.knowledge.sql import run_readonly

DOCS = {
    "garantia.md": "# Garantía\n\nLa garantía del router X200 cubre defectos de fabricación durante dos años.",
    "devoluciones.md": "# Devoluciones\n\nPuedes devolver cualquier producto en un plazo de 30 días naturales.",
    "envios.md": "# Envíos\n\nLos pedidos se envían en 24 horas laborables a toda la península.",
    "router.md": "# Router X200\n\nEl router X200 tiene cuatro puertos Ethernet y wifi 6.",
}


async def _kb_with_docs(team, make_kb, as_user):  # type: ignore[no-untyped-def]
    kb = await make_kb(team, name="Ayuda")
    builder = await as_user(team.builder)
    res = await builder.post(
        f"/api/v1/knowledge-bases/{kb.id}/files",
        files=multipart(*[(name, body.encode(), "text/markdown") for name, body in DOCS.items()]),
    )
    assert res.status_code == 201, res.text
    assert await ingest_all(kb.id) == ["ready"] * len(DOCS)
    return kb


async def test_search_modes_rank_relevant_chunks(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb = await _kb_with_docs(team, make_kb, as_user)
    async with rls_session(team.principal("viewer")) as db:
        hybrid = await search(db, kb_id=kb.id, query="garantía del router", mode="hybrid", k=4)
        keyword = await search(db, kb_id=kb.id, query="devolver producto", mode="keyword", k=4)
        vector = await search(db, kb_id=kb.id, query="plazo para devolver un producto", mode="vector", k=4)
    assert hybrid[0].filename == "garantia.md"
    # Both garantia (keyword + vector) and router (vector) appear; the doc matching both ranks first.
    assert {h.filename for h in hybrid[:3]} >= {"garantia.md", "router.md"}
    assert hybrid[0].score > hybrid[-1].score
    assert keyword[0].filename == "devoluciones.md" and len(keyword) == 1
    assert vector[0].filename == "devoluciones.md"
    assert vector[0].heading == "Devoluciones" and vector[0].page_from is None

    viewer = await as_user(team.viewer)
    res = await viewer.post(
        f"/api/v1/knowledge-bases/{kb.id}/search", json={"query": "envío península", "mode": "hybrid", "k": 2}
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["hits"][0]["filename"] == "envios.md" and len(body["hits"]) <= 2


async def test_search_uses_per_kb_vector_index(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb = await _kb_with_docs(team, make_kb, as_user)
    async with system_session() as s:
        await s.execute(text("SET LOCAL enable_seqscan = off"))
        emb = (await s.execute(select(KbChunk.embedding).where(KbChunk.kb_id == kb.id).limit(1))).scalar_one()
        literal = "[" + ",".join(str(float(x)) for x in emb) + "]"
        plan = "\n".join(
            r[0]
            for r in await s.execute(
                text(
                    "EXPLAIN SELECT id FROM public.kb_chunks c WHERE c.kb_id = :kb AND c.embedding IS NOT NULL "
                    "ORDER BY (c.embedding::vector(384)) <=> CAST(:e AS vector(384)) LIMIT 5"
                ),
                {"kb": str(kb.id), "e": literal},
            )
        )
    assert f"ix_kb_chunks_vec_{kb.schema_name[3:]}" in plan


async def test_sql_console_rules_scope_and_limits(team, make_kb, as_user, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    kb = await _kb_with_docs(team, make_kb, as_user)
    other = await make_kb(team, name="Otra base")
    outsider_owner = await make_user()
    outsider_org, _ = await make_org(owner=outsider_owner, name="Ajena")
    from messer_api.services.knowledge import create_kb
    from messer_common.db import Principal

    foreign = await create_kb(
        Principal(user_id=outsider_owner.id, org_id=outsider_org.id, role="owner"),
        name="Ajena",
        embedding_model="hash-384",
    )

    # Writes and multiple statements never reach the database.
    for sql in (
        "DELETE FROM documents",
        "SELECT 1; SELECT 2",
        "WITH x AS (UPDATE documents SET size = 0 RETURNING 1) SELECT 1",
    ):
        with pytest.raises(SqlRejected):
            await run_readonly(kb_id=kb.id, sql=sql)
    # Another knowledge base's schema, public tables and catalog are out of reach.
    with pytest.raises(SqlRejected) as err:
        await run_readonly(kb_id=kb.id, sql=f"SELECT * FROM {other.schema_name}.documents")
    assert err.value.code == "sql_scope"
    with pytest.raises(SqlRejected) as err:
        await run_readonly(kb_id=kb.id, sql="SELECT content FROM public.kb_chunks")
    assert err.value.code == "sql_permission"
    with pytest.raises(SqlRejected):
        await run_readonly(kb_id=kb.id, sql="SELECT * FROM public.orgs")
    # The search functions only accept this knowledge base (not another one, not another organization's).
    for target in (other.id, foreign.id):
        with pytest.raises(SqlRejected) as err:
            await run_readonly(
                kb_id=kb.id, sql="SELECT * FROM kb_text_search($1::uuid, 'router', 5)", params=[str(target)]
            )
        assert err.value.code == "sql_permission"
    # The views only show this knowledge base.
    own = await run_readonly(kb_id=kb.id, sql="SELECT count(*) AS n FROM documents")
    assert own.columns == ["n"] and own.rows == [[len(DOCS)]]
    # Read-only transaction even for functions with side effects that slipped through.
    with pytest.raises(SqlRejected):
        await run_readonly(kb_id=kb.id, sql="SELECT nextval('x')")

    # Row limit and truncation, statement timeout.
    limited = await run_readonly(kb_id=kb.id, sql="SELECT g FROM generate_series(1, 5000) g", limit=100)
    assert limited.row_count == 100 and limited.truncated and limited.rows[0] == [1]
    with pytest.raises(SqlTimeout):
        await run_readonly(kb_id=kb.id, sql="SELECT count(*) FROM generate_series(1, 200000000) a", timeout_ms=200)
    # Parameters, syntax errors, EXPLAIN.
    params = await run_readonly(kb_id=kb.id, sql="SELECT $1::int + $2::int AS total", params=[2, 3])
    assert params.rows == [[5]] and params.column_types == ["int4"]
    with pytest.raises(SqlRejected):
        await run_readonly(kb_id=kb.id, sql="SELECT $1", params=[])
    with pytest.raises(SqlExecutionError):
        await run_readonly(kb_id=kb.id, sql="SELECT no_existe FROM documents")
    plan = await run_readonly(kb_id=kb.id, sql="SELECT * FROM chunks WHERE content ILIKE '%router%'", explain=True)
    assert plan.rows == [] and isinstance(plan.plan, list) and "Plan" in plan.plan[0]
    explained = await run_readonly(kb_id=kb.id, sql="EXPLAIN SELECT 1")
    assert explained.columns == ["QUERY PLAN"]


async def test_embed_expansion_and_join_table_with_documents(team, make_kb, as_user) -> None:  # type: ignore[no-untyped-def]
    kb = await _kb_with_docs(team, make_kb, as_user)
    async with system_session() as s:
        await upsert_table(
            s,
            org_id=team.org_id,
            kb_id=kb.id,
            table="productos",
            columns=[
                {"name": "sku", "type": "text", "nullable": False},
                {"name": "nombre", "type": "text"},
                {"name": "precio", "type": "numeric"},
                {"name": "documento", "type": "text"},
            ],
            rows=[
                {"sku": "X200", "nombre": "Router X200", "precio": "89,90", "documento": "router.md"},
                {"sku": "G1", "nombre": "Garantía extendida", "precio": 19, "documento": "garantia.md"},
            ],
            primary_key=["sku"],
        )
    # embed('…') becomes a computed vector parameter.
    vec = await run_readonly(
        kb_id=kb.id,
        sql="SELECT filename, score FROM kb_vector_search($1::uuid, embed('plazo para devolver productos'), 2)",
        params=[str(kb.id)],
    )
    assert vec.rows[0][0] == "devoluciones.md"
    vec_param = await run_readonly(
        kb_id=kb.id,
        sql="SELECT filename FROM chunks ORDER BY embedding <=> embed($1) LIMIT 1",
        params=["envío de pedidos"],
    )
    assert vec_param.rows == [["envios.md"]]
    # Phase 4 criterion: a query joins a table with documents.
    joined = await run_readonly(
        kb_id=kb.id,
        sql=(
            "SELECT p.sku, p.precio, d.filename, d.score "
            "FROM productos p JOIN kb_text_search($1::uuid, 'router', 10) d ON d.filename = p.documento "
            "ORDER BY d.score DESC"
        ),
        params=[str(kb.id)],
    )
    assert joined.columns == ["sku", "precio", "filename", "score"]
    assert joined.rows[0][0] == "X200"
    assert joined.rows[0][1] == 89.9

    # Same through the API (viewer) and the engine-compatible endpoint (API key).
    viewer = await as_user(team.viewer)
    res = await viewer.post(
        f"/api/v1/knowledge-bases/{kb.id}/query",
        json={"sql": "SELECT sku, nombre FROM productos ORDER BY sku", "params": []},
    )
    assert res.status_code == 200, res.text
    assert res.json()["rows"] == [["G1", "Garantía extendida"], ["X200", "Router X200"]]
    res = await viewer.post(f"/api/v1/knowledge-bases/{kb.id}/query", json={"sql": "DROP TABLE productos"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "sql_not_read_only"
    schema = (await viewer.get(f"/api/v1/knowledge-bases/{kb.id}/schema")).json()
    names = {r["name"]: r for r in schema["relations"]}
    assert {"productos", "documents", "chunks", "entities"} <= set(names)
    assert names["productos"]["kind"] == "table" and names["chunks"]["kind"] == "view"


async def test_engine_endpoint_with_api_key_and_jwt(team, make_kb, as_user, api_key_client) -> None:  # type: ignore[no-untyped-def]
    kb = await _kb_with_docs(team, make_kb, as_user)
    agent = await api_key_client(team)
    url = f"/api/v1/orgs/{team.org_id}/knowledge-bases/{kb.id}/query"
    res = await agent.post(url, json={"sql": "SELECT filename FROM documents ORDER BY filename", "params": []})
    assert res.status_code == 200, res.text
    assert [r[0] for r in res.json()["rows"]] == sorted(DOCS)
    res = await agent.post(url, json={"sql": "SELECT 1", "params": [], "explain": True})
    assert res.status_code == 200 and res.json()["plan"]
    search_res = await agent.post(
        f"/api/v1/orgs/{team.org_id}/knowledge-bases/{kb.id}/search", json={"query": "wifi", "mode": "hybrid", "k": 3}
    )
    assert search_res.status_code == 200 and search_res.json()["hits"][0]["filename"] == "router.md"
    # Path organization must match the key's organization.
    import uuid

    res = await agent.post(f"/api/v1/orgs/{uuid.uuid4()}/knowledge-bases/{kb.id}/query", json={"sql": "SELECT 1"})
    assert res.status_code == 403
    viewer = await as_user(team.viewer)
    res = await viewer.post(url, json={"sql": "SELECT count(*) FROM chunks", "params": []})
    assert res.status_code == 200 and res.json()["rows"][0][0] >= len(DOCS)
