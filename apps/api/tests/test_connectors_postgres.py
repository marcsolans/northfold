"""PostgreSQL connector against the test database itself: introspection, read-only enforcement, and full and
incremental syncs merged on the primary key into a knowledge base table."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select, text

from messer_api.services.connector_syncs import execute_sync
from messer_api.services.knowledge import create_kb
from messer_common.db import system_session
from messer_common.db.models import KbTable, KnowledgeBase, Sync
from messer_common.settings import get_settings
from messer_common.testing.fixtures import principal_for
from messer_connectors.sql import SqlError
from messer_connectors.sql.engines import PostgresEngine

SCHEMA = "crm_demo"


@pytest.fixture
async def sample_tables() -> AsyncIterator[None]:
    async with system_session() as s:
        await s.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await s.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await s.execute(
            text(
                f"""
                CREATE TABLE {SCHEMA}.customers (
                    id integer PRIMARY KEY,
                    name text NOT NULL,
                    email text,
                    city text,
                    balance numeric(12, 2) DEFAULT 0,
                    active boolean DEFAULT true,
                    tags jsonb DEFAULT '[]'::jsonb,
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                COMMENT ON TABLE {SCHEMA}.customers IS 'Clientes de Albor';
                COMMENT ON COLUMN {SCHEMA}.customers.balance IS 'Saldo pendiente en euros';
                CREATE TABLE {SCHEMA}.invoices (
                    number text PRIMARY KEY,
                    customer_id integer NOT NULL REFERENCES {SCHEMA}.customers(id),
                    amount numeric(12, 2) NOT NULL,
                    issued date NOT NULL
                );
                INSERT INTO {SCHEMA}.customers (id, name, email, city, balance, tags, updated_at) VALUES
                  (1, 'Talleres Mendaro S.A.', 'compras@talleres-mendaro.example', 'Eibar', 1284.60, '["industria"]', now() - interval '3 days'),
                  (2, 'Clínica Dental Arrieta', 'administracion@clinica-arrieta.example', 'Getxo', 642.10, '[]', now() - interval '2 days'),
                  (3, 'Construcciones Ugalde S.L.', 'ane.ugalde@construcciones-ugalde.example', 'Bilbao', 875.25, '["obra"]', now() - interval '1 day');
                INSERT INTO {SCHEMA}.invoices VALUES
                  ('F-2026-0412', 1, 1284.60, '2026-08-03'), ('F-2026-0488', 3, 875.25, '2026-09-12');
                """
            )
        )
    yield
    async with system_session() as s:
        await s.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


@pytest.fixture
async def setup(make_org, login, sample_tables):  # type: ignore[no-untyped-def]
    org, user = await make_org()
    client = await login(user.email)
    kb = await create_kb(principal_for(user.id, org.id, "owner"), name="Clientes")
    res = await client.post(
        "/api/v1/connections",
        json={
            "connector_key": "postgresql",
            "name": "ERP",
            "credentials": {"connection_string": get_settings().database_url},
            "config": {"schemas": [SCHEMA]},
        },
    )
    assert res.status_code == 201, res.text
    conn = res.json()
    assert conn["status"] == "active", conn["error"]
    assert conn["config"]["read_only"] is True and "connection_string" not in conn["config"]
    return client, org, kb, conn


async def _kb_rows(kb: KnowledgeBase, table: str) -> list[dict[str, Any]]:
    async with system_session() as s:
        record = (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id, KbTable.name == table))).scalar_one()
        rows = (await s.execute(text(f'SELECT * FROM "{kb.schema_name}"."{record.name}" ORDER BY id'))).mappings().all()
    return [dict(r) for r in rows]


async def test_introspection_reports_columns_keys_and_comments(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, _, conn = setup
    schema = (await client.get(f"/api/v1/connections/{conn['id']}/schema")).json()
    tables = {t["name"]: t for t in schema["tables"]}
    assert set(tables) == {"customers", "invoices"}
    customers = tables["customers"]
    assert customers["schema"] == SCHEMA and customers["comment"] == "Clientes de Albor"
    assert customers["primary_key"] == ["id"]
    cols = {c["name"]: c for c in customers["columns"]}
    assert cols["balance"]["type"] == "numeric(12,2)" and cols["balance"]["kb_type"] == "numeric"
    assert cols["balance"]["comment"] == "Saldo pendiente en euros"
    assert cols["updated_at"]["kb_type"] == "timestamp" and cols["tags"]["kb_type"] == "json"
    assert cols["name"]["nullable"] is False and cols["id"]["pk"] is True
    fk = tables["invoices"]["foreign_keys"][0]
    assert fk["columns"] == ["customer_id"] and fk["ref_table"] == "customers" and fk["ref_columns"] == ["id"]

    resources = (await client.get(f"/api/v1/connections/{conn['id']}/resources")).json()
    assert {r["id"] for r in resources} == {f"table:{SCHEMA}.customers", f"table:{SCHEMA}.invoices"}
    described = await client.post(
        f"/api/v1/connections/{conn['id']}/actions/describe_table", json={"args": {"table": f"{SCHEMA}.invoices"}}
    )
    assert described.json()["result"]["primary_key"] == ["number"]


async def test_queries_are_read_only(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, _, conn = setup
    base = f"/api/v1/connections/{conn['id']}/actions/query"
    res = await client.post(
        base, json={"args": {"sql": f"SELECT name FROM {SCHEMA}.customers WHERE city = $1", "params": ["Bilbao"]}}
    )
    assert res.status_code == 200, res.text
    assert res.json()["result"]["rows"] == [["Construcciones Ugalde S.L."]]
    limited = await client.post(base, json={"args": {"sql": f"SELECT * FROM {SCHEMA}.customers", "limit": 2}})
    assert limited.json()["result"]["row_count"] == 2 and limited.json()["result"]["truncated"] is True

    for sql in (
        f"DELETE FROM {SCHEMA}.customers",
        f"WITH gone AS (DELETE FROM {SCHEMA}.customers RETURNING id) SELECT * FROM gone",
        f"SELECT 1; UPDATE {SCHEMA}.customers SET balance = 0",
    ):
        blocked = await client.post(base, json={"args": {"sql": sql}})
        assert blocked.status_code == 403, sql
        assert blocked.json()["error"]["code"] == "read_only"
    actions = {a["name"] for a in (await client.get(f"/api/v1/connections/{conn['id']}/actions")).json()}
    assert "execute" not in actions

    # Beyond the statement guard, the transaction itself is read-only (even for the owner role).
    engine = PostgresEngine(get_settings().database_url)
    with pytest.raises(SqlError) as exc:
        await engine._run(f"UPDATE {SCHEMA}.customers SET balance = 0", None, limit=10, timeout_ms=5000, write=False)
    assert exc.value.code == "read_only"
    async with system_session() as s:
        balances = (await s.execute(text(f"SELECT sum(balance) FROM {SCHEMA}.customers"))).scalar_one()
    assert float(balances) == pytest.approx(2801.95)


async def test_full_and_incremental_sync_merge_on_primary_key(setup) -> None:  # type: ignore[no-untyped-def]
    client, _org, kb, conn = setup
    res = await client.post(
        "/api/v1/syncs",
        json={
            "connection_id": conn["id"],
            "kb_id": str(kb.id),
            "resource": f"table:{SCHEMA}.customers",
            "mode": "full",
        },
    )
    assert res.status_code == 201, res.text
    sync_id = uuid.UUID(res.json()["id"])
    outcome = await execute_sync(sync_id)
    assert outcome["status"] == "success", outcome
    assert outcome["stats"]["rows_upserted"] == 3
    rows = await _kb_rows(kb, "customers")
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert float(rows[0]["balance"]) == pytest.approx(1284.60) and rows[0]["active"] is True

    # Switch to incremental on updated_at: the first run loads everything and stores the cursor.
    res = await client.patch(f"/api/v1/syncs/{sync_id}", json={"mode": "incremental", "cursor_field": "updated_at"})
    assert res.status_code == 200, res.text
    first = await execute_sync(sync_id)
    assert first["status"] == "success" and first["stats"]["rows_upserted"] == 3 and first["cursor"]

    async with system_session() as s:
        await s.execute(
            text(
                f"UPDATE {SCHEMA}.customers SET name = 'Talleres Mendaro (Eibar)', balance = 0, updated_at = now() WHERE id = 1"
            )
        )
        await s.execute(
            text(
                f"INSERT INTO {SCHEMA}.customers (id, name, city, updated_at) VALUES (4, 'Papelería Lurra', 'Pamplona', now())"
            )
        )
    second = await execute_sync(sync_id)
    assert second["status"] == "success", second
    # Only rows at or after the cursor are read: the two changed rows plus the boundary row.
    assert second["stats"]["rows_upserted"] < 4
    rows = await _kb_rows(kb, "customers")
    assert [r["id"] for r in rows] == [1, 2, 3, 4]  # merged on PK: no duplicates
    assert rows[0]["name"] == "Talleres Mendaro (Eibar)" and float(rows[0]["balance"]) == 0
    assert rows[3]["city"] == "Pamplona"

    async with system_session() as s:
        sync = await s.get(Sync, sync_id)
        assert sync is not None
        assert sync.status == "success" and sync.last_error is None and sync.cursor
        assert sync.stats["totals"]["runs"] == 3 and len(sync.stats["history"]) == 3
    listed = (await client.get("/api/v1/syncs", params={"kb_id": str(kb.id)})).json()
    assert listed[0]["stats"]["last_run"]["rows_upserted"] == second["stats"]["rows_upserted"]

    bad = await client.patch(f"/api/v1/syncs/{sync_id}", json={"cursor_field": None})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "cursor_field_required"


async def test_sync_errors_are_persisted(setup) -> None:  # type: ignore[no-untyped-def]
    client, _, kb, conn = setup
    res = await client.post(
        "/api/v1/syncs",
        json={"connection_id": conn["id"], "kb_id": str(kb.id), "resource": f"table:{SCHEMA}.missing", "mode": "full"},
    )
    sync_id = uuid.UUID(res.json()["id"])
    outcome = await execute_sync(sync_id)
    assert outcome["status"] == "error" and "no existe" in outcome["error"]
    detail = (await client.get(f"/api/v1/syncs/{sync_id}")).json()
    assert detail["status"] == "error" and detail["last_error"] and detail["stats"]["totals"]["errors"] == 1
    invalid = await client.post(
        "/api/v1/syncs", json={"connection_id": conn["id"], "kb_id": str(kb.id), "resource": "folder:x"}
    )
    assert invalid.status_code == 422
    too_often = await client.post(
        "/api/v1/syncs",
        json={
            "connection_id": conn["id"],
            "kb_id": str(kb.id),
            "resource": f"table:{SCHEMA}.invoices",
            "schedule": "* * * * *",
        },
    )
    assert too_often.status_code == 422 and too_often.json()["error"]["code"] == "schedule_too_frequent"
    scheduled = await client.post(
        "/api/v1/syncs",
        json={
            "connection_id": conn["id"],
            "kb_id": str(kb.id),
            "resource": f"table:{SCHEMA}.invoices",
            "schedule": "0 6 * * *",
        },
    )
    assert scheduled.status_code == 201 and scheduled.json()["next_run_at"]
