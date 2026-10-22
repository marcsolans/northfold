"""API keys (scoped, shown once, revocable) and write-only project secrets that reach the sandbox."""

from __future__ import annotations

import uuid

import httpx

from messer_runtime.testing import Harness


async def _project(client: httpx.AsyncClient) -> str:
    assert (await client.post("/api/v1/auth/signup", json={"email": "keys@acme.example",
                                                         "password": "Contrasena123"})).status_code == 200
    pid = (await client.post("/api/v1/projects", json={"name": "Claves"})).json()["id"]
    assert (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "asistente"})).status_code == 201
    return str(pid)


async def test_scoped_api_key_runs_and_is_revocable(client: httpx.AsyncClient, runtime: Harness) -> None:
    pid = await _project(client)
    bad = await client.post("/api/v1/api-keys", json={"name": "x", "scopes": ["todo"]})
    assert bad.status_code == 400
    created = await client.post("/api/v1/api-keys", json={"name": "CRM", "project_id": pid, "scopes": ["runs:write"]})
    assert created.status_code == 201, created.text
    key = created.json()["key"]
    assert key.startswith("msr_") and "key" not in (await client.get("/api/v1/api-keys")).json()[0]
    async with httpx.AsyncClient(transport=client._transport, base_url="http://testserver") as anon:  # noqa: SLF001
        headers = {"Authorization": f"Bearer {key}"}
        ok = await anon.post(f"/v1/projects/{pid}/workforce/asistente/run",
                             json={"input": {"prompt": "Hola"}, "environment": "development"}, headers=headers)
        assert ok.status_code == 200, ok.text
        forbidden = await anon.get(f"/v1/runs/{ok.json()['run_id']}", headers=headers)
        assert forbidden.status_code == 403 and forbidden.json()["error"]["code"] == "missing_scope"
        other = await anon.post(f"/v1/projects/{uuid.uuid4()}/workforce/asistente/run",
                                json={"input": {"prompt": "Hola"}}, headers=headers)
        assert other.status_code == 403
        revoked = await client.delete(f"/api/v1/api-keys/{created.json()['id']}")
        assert revoked.status_code == 204
        after = await anon.post(f"/v1/projects/{pid}/workforce/asistente/run",
                                json={"input": {"prompt": "Hola"}, "environment": "development"}, headers=headers)
        assert after.status_code == 401


async def test_secrets_are_write_only_and_reach_the_sandbox(client: httpx.AsyncClient) -> None:
    from messer_runtime.runs import _project_secrets

    pid = await _project(client)
    assert (await client.put(f"/api/v1/projects/{pid}/secrets/crm_token", json={"value": "x"})).status_code == 400
    assert (await client.put(f"/api/v1/projects/{pid}/secrets/AWS_KEY", json={"value": "x"})).status_code == 400
    res = await client.put(f"/api/v1/projects/{pid}/secrets/CRM_TOKEN", json={"value": "tok-123"})
    assert res.status_code == 200, res.text
    listed = (await client.get(f"/api/v1/projects/{pid}/secrets")).json()
    assert listed == [{"name": "CRM_TOKEN", "created_at": listed[0]["created_at"], "updated_at": listed[0]["updated_at"]}]
    assert await _project_secrets(uuid.UUID(pid)) == {"CRM_TOKEN": "tok-123"}
    assert (await client.delete(f"/api/v1/projects/{pid}/secrets/CRM_TOKEN")).status_code == 204
    runs = await client.get(f"/api/v1/projects/{pid}/runs")
    assert runs.status_code == 200 and runs.json()["items"] == []
