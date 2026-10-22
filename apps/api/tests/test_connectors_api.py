"""Connectors API: catalog seed, demo connections, OAuth start/callback, credentials, actions, webhooks, roles."""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select, text

from messer_common.db import system_session
from messer_common.db.models import ApiKey, Connection
from messer_common.security import decrypt_json, encrypt_json, generate_api_key, hash_token
from messer_common.settings import get_settings, reset_settings_cache
from messer_connectors import http as chttp
from messer_connectors import registry
from messer_connectors.adapters.webhooks import sign

OAUTH_ENV = ("GOOGLE", "MICROSOFT", "SLACK", "NOTION", "HUBSPOT", "SALESFORCE")


@pytest.fixture
def no_oauth_apps(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in OAUTH_ENV:
        monkeypatch.setenv(f"{key}_CLIENT_ID", "")
        monkeypatch.setenv(f"{key}_CLIENT_SECRET", "")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def hubspot_app(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("HUBSPOT_CLIENT_ID", "hub-client")
    monkeypatch.setenv("HUBSPOT_CLIENT_SECRET", "hub-secret")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def mock_http() -> Iterator[list[httpx.Request]]:
    seen: list[httpx.Request] = []
    handlers: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.hubapi.com" and request.url.path == "/oauth/v1/token":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                return httpx.Response(200, json={"access_token": "at-hub-1", "refresh_token": "rt-hub", "expires_in": 1800,
                                                 "token_type": "bearer", "hub_id": 42})  # fmt: skip
            return httpx.Response(
                200, json={"access_token": "at-hub-2", "refresh_token": "rt-hub-2", "expires_in": 1800}
            )
        if request.url.host == "erp.example":
            if request.method == "GET":
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(201, json={"created": json.loads(request.content or b"{}")})
        custom = handlers.get(request.url.host)
        if custom:
            return custom(request)
        return httpx.Response(404, json={"error": "unexpected"})

    chttp.set_transport(httpx.MockTransport(handler))
    yield seen
    chttp.set_transport(None)


@pytest.fixture
async def owner(make_org, login):  # type: ignore[no-untyped-def]
    org, user = await make_org(name="Albor")
    client = await login(user.email)
    client.headers["X-Messer-Org"] = str(org.id)
    return client, org, user


async def test_catalog_is_seeded_and_searchable(owner) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = owner
    async with system_session() as s:
        keys = {row[0] for row in (await s.execute(text("select key from connectors"))).all()}
    assert {spec.key for spec in registry.catalog()} <= keys
    res = await client.get("/api/v1/connectors")
    assert res.status_code == 200
    body = res.json()
    assert len(body["items"]) == len(registry.catalog())
    assert {c["key"] for c in body["categories"]} >= {"files", "crm", "database", "developer"}
    crm = (await client.get("/api/v1/connectors", params={"category": "crm"})).json()["items"]
    assert {c["key"] for c in crm} == {"hubspot", "salesforce"}
    found = (await client.get("/api/v1/connectors", params={"q": "sharepoint"})).json()["items"]
    assert [c["key"] for c in found] == ["sharepoint"]
    detail = (await client.get("/api/v1/connectors/gmail")).json()
    assert {a["name"] for a in detail["actions"]} >= {"search_messages", "send_message"}
    assert next(a for a in detail["actions"] if a["name"] == "send_message")["side_effect"] is True
    assert (await client.get("/api/v1/connectors/nope")).status_code == 404


async def test_connect_without_oauth_app_creates_demo_connection(owner, no_oauth_apps) -> None:  # type: ignore[no-untyped-def]
    client, _org, _ = owner
    detail = (await client.get("/api/v1/connectors/gmail")).json()
    assert detail["availability"] == {"mode": "demo", "missing_env": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]}
    res = await client.post("/api/v1/connections/oauth/gmail/start", json={})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mode"] == "demo" and body["missing_env"] == ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    conn = body["connection"]
    assert conn["demo"] is True and conn["status"] == "demo" and conn["missing_env"]
    listed = (await client.get("/api/v1/connections")).json()
    assert [c["id"] for c in listed] == [conn["id"]]
    actions = (await client.get(f"/api/v1/connections/{conn['id']}/actions")).json()
    assert {a["name"] for a in actions} >= {"search_messages", "get_message", "send_message"}
    res = await client.post(
        f"/api/v1/connections/{conn['id']}/actions/search_messages", json={"args": {"query": "factura"}}
    )
    assert res.status_code == 200, res.text
    assert res.json()["demo"] is True and res.json()["result"]
    test = (await client.post(f"/api/v1/connections/{conn['id']}/test")).json()
    assert test["ok"] is True and test["status"] == "demo"


async def test_oauth_start_and_callback_store_encrypted_tokens(owner, hubspot_app, mock_http) -> None:  # type: ignore[no-untyped-def]
    client, org, user = owner
    res = await client.post(
        "/api/v1/connections/oauth/hubspot/start", json={"name": "CRM", "return_to": "/app/connectors"}
    )
    assert res.status_code == 200, res.text
    url = res.json()["url"]
    parts = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert parts.netloc == "app.hubspot.com" and q["client_id"] == "hub-client"
    assert q["redirect_uri"] == f"{get_settings().messer_web_url}/api/v1/connections/oauth/hubspot/callback"
    assert "crm.objects.contacts.write" in q["scope"].split(" ")

    cb = await client.get(
        "/api/v1/connections/oauth/hubspot/callback", params={"code": "auth-code", "state": q["state"]}
    )
    assert cb.status_code == 302
    location = urlsplit(cb.headers["location"])
    assert location.path == "/app/connectors"
    conn_id = uuid.UUID(parse_qs(location.query)["connected"][0])
    token_call = next(r for r in mock_http if r.url.path == "/oauth/v1/token")
    assert parse_qs(token_call.content.decode())["code"] == ["auth-code"]

    async with system_session() as s:
        conn = await s.get(Connection, conn_id)
        assert conn is not None and conn.org_id == org.id and conn.created_by == user.id
        assert conn.name == "CRM" and conn.status == "active" and conn.demo is False
        assert conn.credentials and "at-hub-1" not in conn.credentials  # encrypted at rest
        creds = decrypt_json(conn.credentials)
    assert creds["access_token"] == "at-hub-1" and creds["refresh_token"] == "rt-hub"
    assert creds["extra"]["hub_id"] == 42

    replay = await client.get("/api/v1/connections/oauth/hubspot/callback", params={"code": "x", "state": q["state"]})
    assert replay.status_code == 302 and "oauth_error=token_used" in replay.headers["location"]
    denied = await client.get("/api/v1/connections/oauth/hubspot/callback", params={"error": "access_denied"})
    assert "oauth_error=access_denied" in denied.headers["location"]


async def test_credentials_endpoint_refreshes_and_is_restricted(owner, hubspot_app, mock_http) -> None:  # type: ignore[no-untyped-def]
    client, org, user = owner
    async with system_session() as s:
        conn = Connection(
            org_id=org.id,
            connector_key="hubspot",
            name="CRM",
            credentials=encrypt_json(
                {"access_token": "old", "refresh_token": "rt-hub", "expires_at": time.time() - 60}
            ),
            status="active",
            created_by=user.id,
        )
        s.add(conn)
        await s.flush()
        conn_id = conn.id
        key, prefix = generate_api_key()
        s.add(
            ApiKey(
                org_id=org.id, name="runtime", prefix=prefix, hashed_key=hash_token(key), scopes=["connections:read"]
            )
        )
        weak, weak_prefix = generate_api_key()
        s.add(
            ApiKey(org_id=org.id, name="weak", prefix=weak_prefix, hashed_key=hash_token(weak), scopes=["runs:write"])
        )
    path = f"/api/v1/orgs/{org.id}/connections/{conn_id}/credentials"

    anonymous = httpx.AsyncClient(transport=client._transport, base_url="http://testserver")  # no cookies
    try:
        assert (await anonymous.get(path)).status_code == 401
        assert (await anonymous.get(path, headers={"Authorization": f"Bearer {weak}"})).status_code == 403
        other_org = await anonymous.get(
            f"/api/v1/orgs/{uuid.uuid4()}/connections/{conn_id}/credentials", headers={"Authorization": f"Bearer {key}"}
        )
        assert other_org.status_code == 403
        res = await anonymous.get(path, headers={"Authorization": f"Bearer {get_settings().service_token}"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["token"] == "at-hub-2" and body["provider"] == "hubspot"
        assert body["credentials"]["refresh_token"] == "rt-hub-2"
        res = await anonymous.get(path, headers={"Authorization": f"Bearer {key}"})
        assert res.status_code == 200 and res.json()["token"] == "at-hub-2"  # still fresh: no second refresh
    finally:
        await anonymous.aclose()
    refreshes = [r for r in mock_http if r.url.path == "/oauth/v1/token"]
    assert len(refreshes) == 1
    async with system_session() as s:
        stored = decrypt_json((await s.get(Connection, conn_id)).credentials)  # type: ignore[union-attr]
    assert stored["access_token"] == "at-hub-2"


async def test_side_effect_actions_require_confirmation(owner, mock_http) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = owner
    res = await client.post(
        "/api/v1/connections",
        json={
            "connector_key": "http",
            "name": "ERP",
            "config": {"base_url": "https://erp.example/api", "auth_header_name": "Authorization"},
            "credentials": {"auth_header_value": "Bearer erp-token"},
        },
    )
    assert res.status_code == 201, res.text
    conn = res.json()
    assert conn["status"] == "active" and "auth_header_value" not in conn["config"]
    base = f"/api/v1/connections/{conn['id']}/actions"
    ok = await client.post(f"{base}/get", json={"args": {"path": "invoices"}})
    assert ok.status_code == 200 and ok.json()["side_effect"] is False
    blocked = await client.post(
        f"{base}/request", json={"args": {"method": "POST", "path": "credit-notes", "json": {"amount": 640}}}
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "confirmation_required"
    assert not [r for r in mock_http if r.method == "POST" and r.url.host == "erp.example"]
    confirmed = await client.post(
        f"{base}/request",
        json={"args": {"method": "POST", "path": "credit-notes", "json": {"amount": 640}}, "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["result"]["status"] == 201
    post = next(r for r in mock_http if r.method == "POST" and r.url.host == "erp.example")
    assert post.headers["authorization"] == "Bearer erp-token"
    bad = await client.post(f"{base}/request", json={"args": {"method": "TRACE"}, "confirm": True})
    assert bad.status_code == 422


async def test_inbound_webhook_creates_connector_events(owner) -> None:  # type: ignore[no-untyped-def]
    client, _org, _ = owner
    conn = (await client.post("/api/v1/connections", json={"connector_key": "webhooks", "name": "Pagos"})).json()
    info = (await client.get(f"/api/v1/connections/{conn['id']}/webhook")).json()
    assert info["url"].endswith(f"/api/v1/webhooks/connections/{conn['id']}") and info["verification"] == "hmac"
    secret = info["secret"]
    adapter = registry.get_adapter("webhooks")
    from messer_connectors.credentials import load_context

    async with system_session() as s:
        ctx = await load_context(s, uuid.UUID(conn["id"]))
    _, baseline = await adapter.poll_events(ctx, "received", None)

    body = json.dumps({"invoice": "F-2026-0412", "status": "paid"}).encode()
    path = f"/api/v1/webhooks/connections/{conn['id']}"
    bad = await client.post(path, content=body, headers={"X-Messer-Signature": "sha256=deadbeef"})
    assert bad.status_code == 401
    good = await client.post(
        path, content=body, headers={"X-Messer-Signature": sign(secret, body), "Content-Type": "application/json"}
    )
    assert good.status_code == 202, good.text
    events, cursor = await adapter.poll_events(ctx, "received", baseline)
    assert len(events) == 1 and events[0]["data"]["payload"] == {"invoice": "F-2026-0412", "status": "paid"}
    assert "x-messer-signature" in events[0]["data"]["headers"]
    assert (await adapter.poll_events(ctx, "received", cursor))[0] == []
    listed = await client.post(f"/api/v1/connections/{conn['id']}/actions/list_events", json={"args": {}})
    assert listed.status_code == 200 and len(listed.json()["result"]) == 1

    rotated = (await client.post(f"/api/v1/connections/{conn['id']}/webhook/rotate")).json()
    assert rotated["secret"] != secret
    stale = await client.post(path, content=body, headers={"X-Messer-Signature": sign(secret, body)})
    assert stale.status_code == 401
    assert (await client.post(f"/api/v1/webhooks/connections/{uuid.uuid4()}", content=b"{}")).status_code == 404


async def test_roles_and_validation(make_org, make_user, login) -> None:  # type: ignore[no-untyped-def]
    viewer = await make_user()
    builder = await make_user()
    org, owner_user = await make_org(members={str(viewer.id): "viewer", str(builder.id): "builder"})

    client = await login(viewer.email)
    client.headers["X-Messer-Org"] = str(org.id)
    denied = await client.post("/api/v1/connections", json={"connector_key": "webhooks"})
    assert denied.status_code == 403

    client = await login(builder.email)
    client.headers["X-Messer-Org"] = str(org.id)
    bad_dsn = await client.post(
        "/api/v1/connections", json={"connector_key": "postgresql", "credentials": {"connection_string": "nonsense"}}
    )
    assert bad_dsn.status_code == 422 and bad_dsn.json()["error"]["code"] == "invalid_config"
    needs_oauth = await client.post("/api/v1/connections", json={"connector_key": "gmail"})
    assert needs_oauth.status_code == 400 and needs_oauth.json()["error"]["code"] == "oauth_required"
    conn = (await client.post("/api/v1/connections", json={"connector_key": "webhooks"})).json()
    assert (await client.delete(f"/api/v1/connections/{conn['id']}")).status_code == 403

    client = await login(owner_user.email)
    client.headers["X-Messer-Org"] = str(org.id)
    assert (await client.delete(f"/api/v1/connections/{conn['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/connections/{conn['id']}")).status_code == 404
    async with system_session() as s:
        audit_actions = {
            r[0] for r in (await s.execute(text("select action from audit_log where org_id = :o"), {"o": org.id})).all()
        }
        remaining = (await s.execute(select(Connection).where(Connection.org_id == org.id))).scalars().all()
    assert {"connection.created", "connection.deleted"} <= audit_actions
    assert remaining == []
