"""On-prem connector agent: enrollment, outbound WebSocket, RPC round trips through Redis, DB queries and syncs
routed through the agent (the agent client runs in-process against the ASGI app served by uvicorn)."""

from __future__ import annotations

import asyncio
import socket
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from sqlalchemy import select, text

from messer_api.services.connector_syncs import execute_sync
from messer_api.services.knowledge import create_kb
from messer_common.db import system_session
from messer_common.db.models import ConnectorAgent, KbFile, KbTable
from messer_common.settings import get_settings
from messer_common.testing.fixtures import principal_for
from messer_connector_agent.cli import enroll
from messer_connector_agent.client import AgentClient
from messer_connector_agent.config import AgentConfig, Source
from messer_connectors import agent_rpc
from messer_connectors.base import AgentUnavailable, ConnectorError

SCHEMA = "agent_demo"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
async def live_api() -> AsyncIterator[str]:
    from messer_api.main import create_app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(), host="127.0.0.1", port=port, lifespan="off", log_level="warning", ws="websockets-sansio"
        )
    )
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.025)
    assert server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, timeout=15)


@pytest.fixture
async def on_prem_data(tmp_path: Path) -> AsyncIterator[Path]:
    async with system_session() as s:
        await s.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        await s.execute(text(f"CREATE SCHEMA {SCHEMA}"))
        await s.execute(
            text(
                f"CREATE TABLE {SCHEMA}.stock (sku text PRIMARY KEY, product text NOT NULL, units integer NOT NULL);"
                f"INSERT INTO {SCHEMA}.stock VALUES ('AL-1001', 'Papel A4', 1840), ('AL-1040', 'Silla Ergo Plus', 36);"
            )
        )
    docs = tmp_path / "documentos"
    (docs / "procedimientos").mkdir(parents=True)
    (docs / "manual.md").write_text("# Manual interno\n\nDocumento de la red del cliente.", encoding="utf-8")
    (docs / "procedimientos" / "cobros.md").write_text("# Cobros\n\nRecordatorio a 7 días.", encoding="utf-8")
    (tmp_path / "secreto.txt").write_text("fuera de las rutas permitidas", encoding="utf-8")
    yield docs
    async with system_session() as s:
        await s.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))


async def _wait_for(predicate: Any, within_s: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + within_s
    while asyncio.get_running_loop().time() < deadline:
        if await predicate():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("condition not met in time")


async def test_agent_enrollment_rpc_and_routed_connections(  # type: ignore[no-untyped-def]
    make_org, login, live_api, on_prem_data, tmp_path
) -> None:
    org, user = await make_org()
    client = await login(user.email)
    created = await client.post("/api/v1/connector-agents", json={"name": "Servidor oficina Bilbao"})
    assert created.status_code == 201, created.text
    body = created.json()
    agent_id = uuid.UUID(body["agent"]["id"])
    assert body["agent"]["status"] == "pending" and "--token" in body["commands"]["binary"]

    # Enrollment exchange over real HTTP (the CLI uses blocking urllib, so it runs in a thread).
    state_file = tmp_path / "credentials.json"
    state = await asyncio.to_thread(enroll, live_api, body["enrollment_token"], state_file=state_file)
    assert state.agent_id == str(agent_id) and state_file.stat().st_mode & 0o777 == 0o600
    async with system_session() as s:
        agent = await s.get(ConnectorAgent, agent_id)
        assert agent is not None and agent.enrolled_at is not None and agent.agent_secret_hash != state.agent_secret
    with pytest.raises(SystemExit):  # single use
        await asyncio.to_thread(enroll, live_api, body["enrollment_token"], state_file=tmp_path / "again.json")

    config = AgentConfig(
        sources={"erp": Source(name="erp", type="postgresql", dsn=get_settings().database_url)},
        paths=[on_prem_data.resolve()],
    )
    agent_client = AgentClient(state, config)
    stop = asyncio.Event()
    runner = asyncio.create_task(agent_client.run_forever(stop))
    try:
        await asyncio.wait_for(agent_client.connected.wait(), timeout=10)

        info = await agent_rpc.call(agent_id, "ping", {}, timeout_s=5)
        assert info["sources"] == [{"name": "erp", "type": "postgresql"}] and info["paths"] == [
            str(on_prem_data.resolve())
        ]

        async def online() -> bool:
            listed = (await client.get("/api/v1/connector-agents")).json()
            return listed[0]["status"] == "online" and bool(listed[0]["capabilities"].get("sources"))

        await _wait_for(online)
        ping = (await client.post(f"/api/v1/connector-agents/{agent_id}/ping")).json()
        assert ping["ok"] is True and ping["agent"]["version"]

        # A database connection routed through the agent never receives a connection string.
        refused = await client.post(
            "/api/v1/connections",
            json={
                "connector_key": "postgresql",
                "agent_id": str(agent_id),
                "config": {"agent_source": "erp"},
                "credentials": {"connection_string": get_settings().database_url},
            },
        )
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "agent_connection_string"
        unknown = await client.post(
            "/api/v1/connections",
            json={"connector_key": "postgresql", "agent_id": str(agent_id), "config": {"agent_source": "nope"}},
        )
        assert unknown.status_code == 422
        res = await client.post(
            "/api/v1/connections",
            json={
                "connector_key": "postgresql",
                "name": "ERP local",
                "agent_id": str(agent_id),
                "config": {"agent_source": "erp", "schemas": [SCHEMA]},
            },
        )
        assert res.status_code == 201, res.text
        conn = res.json()
        assert conn["status"] == "active" and conn["agent_id"] == str(agent_id) and conn["has_credentials"] is False

        query = await client.post(
            f"/api/v1/connections/{conn['id']}/actions/query",
            json={
                "args": {
                    "sql": f"SELECT product, units FROM {SCHEMA}.stock WHERE units > $1 ORDER BY sku",
                    "params": [100],
                }
            },
        )
        assert query.status_code == 200, query.text
        assert query.json()["result"]["rows"] == [["Papel A4", 1840]]
        blocked = await client.post(
            f"/api/v1/connections/{conn['id']}/actions/query", json={"args": {"sql": f"DELETE FROM {SCHEMA}.stock"}}
        )
        assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "read_only"
        schema = (await client.get(f"/api/v1/connections/{conn['id']}/schema")).json()
        assert [t["name"] for t in schema["tables"]] == ["stock"] and schema["tables"][0]["primary_key"] == ["sku"]

        kb = await create_kb(principal_for(user.id, org.id, "owner"), name="Inventario")
        sync = (
            await client.post(
                "/api/v1/syncs",
                json={"connection_id": conn["id"], "kb_id": str(kb.id), "resource": f"table:{SCHEMA}.stock"},
            )
        ).json()
        outcome = await execute_sync(uuid.UUID(sync["id"]))
        assert outcome["status"] == "success" and outcome["stats"]["rows_upserted"] == 2, outcome
        async with system_session() as s:
            table = (await s.execute(select(KbTable).where(KbTable.kb_id == kb.id))).scalar_one()
            rows = (
                await s.execute(text(f'SELECT sku, units FROM "{kb.schema_name}"."{table.name}" ORDER BY sku'))
            ).all()
        assert [tuple(r) for r in rows] == [("AL-1001", 1840), ("AL-1040", 36)]

        # Files from the customer's network copied into the knowledge base.
        files_conn = (
            await client.post(
                "/api/v1/connections",
                json={
                    "connector_key": "onprem_files",
                    "agent_id": str(agent_id),
                    "config": {"root": str(on_prem_data.resolve())},
                },
            )
        ).json()
        assert files_conn["status"] == "active", files_conn["error"]
        sync = (
            await client.post(
                "/api/v1/syncs",
                json={
                    "connection_id": files_conn["id"],
                    "kb_id": str(kb.id),
                    "resource": f"path:{on_prem_data.resolve()}",
                },
            )
        ).json()
        outcome = await execute_sync(uuid.UUID(sync["id"]))
        assert outcome["status"] == "success" and outcome["stats"]["files_ingested"] == 2, outcome
        async with system_session() as s:
            names = sorted(f.filename for f in (await s.execute(select(KbFile).where(KbFile.kb_id == kb.id))).scalars())
        assert names == ["cobros.md", "manual.md"]
        with pytest.raises(ConnectorError) as exc:
            await agent_rpc.call(agent_id, "files.read", {"path": str(tmp_path / "secreto.txt")}, timeout_s=5)
        assert exc.value.code == "path_not_allowed"
    finally:
        stop.set()
        await asyncio.wait_for(runner, timeout=15)

    async def offline() -> bool:
        listed = (await client.get("/api/v1/connector-agents")).json()
        return listed[0]["status"] == "offline"

    await _wait_for(offline)
    with pytest.raises(AgentUnavailable):
        await agent_rpc.call(agent_id, "ping", {}, timeout_s=2)

    deleted = await client.delete(f"/api/v1/connector-agents/{agent_id}")
    assert deleted.status_code == 204
    conn_after = (await client.get(f"/api/v1/connections/{conn['id']}")).json()
    assert conn_after["status"] == "error"


async def test_websocket_rejects_bad_agent_credentials(live_api) -> None:  # type: ignore[no-untyped-def]
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    url = live_api.replace("http://", "ws://") + "/api/v1/connector-agents/connect"
    with pytest.raises(InvalidStatus):
        async with connect(
            url, additional_headers={"Authorization": "Bearer nope", "X-Messer-Agent-Id": str(uuid.uuid4())}
        ):
            pass
