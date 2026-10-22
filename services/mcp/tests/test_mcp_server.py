"""Phase 10 criterion: from an MCP client (as Claude Code does) create an agent in Messer and deploy it.

The MCP server runs on a real port and calls the platform API in-process; the deployment pipeline (normally a
worker job) runs in-test, and the agent executes in the runtime's sandbox with the offline demo model.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult, TextContent

from messer_common.queue import Jobs
from messer_mcp import api as mcp_api
from messer_mcp.config import McpConfig
from messer_mcp.server import create_app, file_uri
from messer_runtime.testing import Harness, free_port

API_BASE = "http://testserver"


@dataclass
class Stack:
    api: httpx.AsyncClient
    mcp_url: str
    key: str
    org_id: str


@pytest.fixture
async def stack(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Stack]:
    from messer_api.main import create_app as create_api
    from messer_api.services import deployments

    api_app = create_api()
    monkeypatch.setattr(mcp_api, "transport", httpx.ASGITransport(app=api_app))
    pipelines: list[asyncio.Task[Any]] = []

    async def worker_enqueue(job: str, *args: Any, **_: Any) -> None:
        """The worker's DEPLOY job, executed in-test once the deployment row is committed."""
        if job != Jobs.DEPLOY:
            return
        dep_id, force, skip_evals = args

        async def run() -> Any:
            for _ in range(200):
                try:
                    return await deployments.run_pipeline(uuid.UUID(dep_id), force=force, skip_evals=skip_evals)
                except LookupError:
                    await asyncio.sleep(0.05)
            raise AssertionError("deployment row never committed")

        pipelines.append(asyncio.create_task(run()))

    monkeypatch.setattr(deployments, "enqueue", worker_enqueue)

    port = free_port()
    config = McpConfig(
        public_url=f"http://127.0.0.1:{port}", issuer_url=API_BASE, api_url=API_BASE, host="127.0.0.1", port=port
    )
    server = uvicorn.Server(
        uvicorn.Config(create_app(config), host="127.0.0.1", port=port, log_level="warning", lifespan="on")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(250):
        if server.started:
            break
        await asyncio.sleep(0.02)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api_app), base_url=API_BASE, timeout=120) as c:
        res = await c.post("/api/v1/auth/signup", json={"email": "claude@acme.example", "password": "Contrasena123"})
        assert res.status_code == 200, res.text
        org_id = str(res.json()["org_id"])
        key = (await c.post("/api/v1/api-keys", json={"name": "Claude Code"})).json()["key"]
        c.cookies.clear()
        try:
            yield Stack(api=c, mcp_url=f"http://127.0.0.1:{port}/mcp", key=key, org_id=org_id)
        finally:
            for pipeline in pipelines:
                if not pipeline.done():
                    pipeline.cancel()
            server.should_exit = True
            await task


def data(result: CallToolResult) -> Any:
    assert not result.isError, result.content
    if result.structuredContent is not None:
        content = result.structuredContent
        return content.get("result", content) if set(content) == {"result"} else content
    first = result.content[0]
    assert isinstance(first, TextContent)
    return json.loads(first.text)


async def test_mcp_client_creates_and_deploys_an_agent(stack: Stack, runtime: Harness) -> None:
    headers = {"Authorization": f"Bearer {stack.key}"}
    async with streamablehttp_client(stack.mcp_url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "messer"
            names = {t.name for t in (await session.list_tools()).tools}
            assert {"list_projects", "create_agent", "update_agent", "deploy", "run_agent", "run_evals"} <= names

            who = data(await session.call_tool("whoami", {}))
            assert who["auth"] == "api_key" and who["org"]["id"] == stack.org_id

            project = data(await session.call_tool("create_project", {"name": "Facturas"}))
            pid = str(project["id"])
            agent = data(
                await session.call_tool(
                    "create_agent",
                    {
                        "project_id": pid,
                        "name": "facturas",
                        "description": "Responde dudas de facturas",
                        "system_prompt": "Eres el asistente de facturación de Acme.",
                        "model_tier": "fast",
                        "tools": ["current_datetime"],
                    },
                )
            )
            assert agent["config"]["system_prompt"] == "Eres el asistente de facturación de Acme."
            assert 'name="facturas"' in agent["code"]
            assert [p["name"] for p in data(await session.call_tool("list_projects", {}))] == ["Facturas"]

            updated = data(
                await session.call_tool(
                    "update_agent",
                    {"project_id": pid, "name": "facturas", "changes": {"memory": {"keep_last_n": 10}}},
                )
            )
            assert updated["config"]["memory"]["keep_last_n"] == 10
            assert updated["config"]["system_prompt"] == "Eres el asistente de facturación de Acme."

            evals = data(await session.call_tool("run_evals", {"project_id": pid, "name": "facturas"}))
            assert evals["status"] == "passed" and evals["passed"] == 1, evals

            # Production is not deployed yet.
            before = await session.call_tool(
                "run_agent", {"project_id": pid, "name": "facturas", "prompt": "Hola"}
            )
            assert before.isError and "not_deployed" in str(before.content)

            dep = data(await session.call_tool("deploy", {"project_id": pid, "wait_seconds": 120}))
            assert dep["status"] == "live", dep["logs"]
            assert data(await session.call_tool("get_deployment", {"deployment_id": dep["id"]}))["status"] == "live"

            run = data(await session.call_tool("run_agent", {"project_id": pid, "name": "facturas", "prompt": "Hola"}))
            assert run["status"] == "success" and run["output"], run
            runs = data(await session.call_tool("list_runs", {"project_id": pid}))
            assert any(r["id"].replace("-", "") == run["run_id"].replace("-", "") for r in runs["items"])
            trace = data(await session.call_tool("get_run", {"run_id": run["run_id"]}))
            assert trace["environment"] == "production" and trace["spans"]

            # Project files are resources.
            resources = (await session.list_resources()).resources
            uri = file_uri(pid, "workforce/facturas/agent.py")
            assert uri in {str(r.uri) for r in resources}
            content = (await session.read_resource(uri)).contents[0]
            assert 'name="facturas"' in getattr(content, "text", "")

    # The production run API answers with the deployed version.
    res = await stack.api.post(
        f"/v1/projects/{pid}/workforce/facturas/run",
        json={"input": {"prompt": "¿Cuál es mi factura pendiente?"}},
        headers=headers,
    )
    assert res.status_code == 200 and res.json()["status"] == "success", res.text


async def test_mcp_requires_a_valid_bearer_and_publishes_metadata(stack: Stack) -> None:
    async with httpx.AsyncClient(timeout=30) as c:
        res = await c.post(stack.mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert res.status_code == 401
        challenge = res.headers["www-authenticate"]
        assert challenge.startswith("Bearer") and "/.well-known/oauth-protected-resource/mcp" in challenge
        res = await c.post(
            stack.mcp_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer msr_not-a-real-key"},
        )
        assert res.status_code == 401
        base = stack.mcp_url.removesuffix("/mcp")
        prm = (await c.get(f"{base}/.well-known/oauth-protected-resource/mcp")).json()
        assert prm["resource"] == stack.mcp_url and prm["authorization_servers"] == [API_BASE]
        assert "projects:write" in prm["scopes_supported"]
        assert (await c.get(f"{base}/.well-known/oauth-protected-resource")).json() == prm
        asm = (await c.get(f"{base}/.well-known/oauth-authorization-server")).json()
        assert asm["token_endpoint"] == f"{API_BASE}/oauth/token" and asm["code_challenge_methods_supported"] == ["S256"]
        assert (await c.get(f"{base}/healthcheck")).json()["ok"] is True


async def test_mcp_tool_errors_carry_the_api_message(stack: Stack) -> None:
    async with streamablehttp_client(stack.mcp_url, headers={"Authorization": f"Bearer {stack.key}"}) as (r, w, _):
        async with ClientSession(r, w) as session:
            await session.initialize()
            missing = await session.call_tool("get_project", {"project_id": str(uuid.uuid4())})
            assert missing.isError and "404" in str(missing.content)
            both = await session.call_tool(
                "update_agent", {"project_id": str(uuid.uuid4()), "name": "x", "changes": {}, "code": "x"}
            )
            assert both.isError and "exactamente uno" in str(both.content)
