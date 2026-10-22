"""OAuth 2.1 for MCP clients: dynamic registration, consent, code + PKCE, refresh rotation, revocation, roles."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select, update

from messer_common.db import system_session
from messer_common.db.models import ApiKey, AuditLog, Membership
from messer_mcp import api as mcp_api
from messer_mcp.auth import MesserTokenVerifier

BASE = "http://testserver"
REDIRECT = "http://localhost:33418/callback"


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    from messer_api.main import create_app

    app = create_app()
    monkeypatch.setattr(mcp_api, "transport", httpx.ASGITransport(app=app))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=60) as c:
        yield c


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def register(c: httpx.AsyncClient, **extra: Any) -> dict[str, Any]:
    body = {
        "client_name": "Claude Code",
        "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        **extra,
    }
    res = await c.post("/oauth/register", json=body)
    assert res.status_code == 201, res.text
    return res.json()


async def authorize(
    c: httpx.AsyncClient, client_id: str, org_id: str, *, scope: str | None = None
) -> tuple[str, str]:
    """Browser part of the flow: authorize → consent page data → approve. Returns (code, verifier)."""
    verifier, challenge = pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st4te",
        "resource": "http://localhost:8400/mcp",
    }
    if scope:
        params["scope"] = scope
    res = await c.get("/oauth/authorize", params=params)
    assert res.status_code == 302, res.text
    consent = urlsplit(res.headers["location"])
    assert consent.path == "/oauth/authorize" and consent.netloc == "localhost:3000"
    forwarded = {k: v[0] for k, v in parse_qs(consent.query).items()}
    view = await c.get("/api/v1/oauth/authorize/request", params=forwarded)
    assert view.status_code == 200, view.text
    assert view.json()["client"]["client_name"] == "Claude Code"
    assert org_id in [o["id"] for o in view.json()["orgs"]]
    decision = await c.post("/api/v1/oauth/authorize", json={**forwarded, "org_id": org_id, "approve": True})
    assert decision.status_code == 200, decision.text
    back = urlsplit(decision.json()["redirect_to"])
    query = parse_qs(back.query)
    assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
    assert query["state"] == ["st4te"] and query["iss"] == ["http://localhost:8000"]
    return query["code"][0], verifier


async def token(c: httpx.AsyncClient, **form: str) -> httpx.Response:
    return await c.post("/oauth/token", data=form)


async def signup(c: httpx.AsyncClient, email: str) -> str:
    res = await c.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123"})
    assert res.status_code == 200, res.text
    return str(res.json()["org_id"])


async def test_full_oauth_flow_for_an_mcp_client(api: httpx.AsyncClient) -> None:
    meta = (await api.get("/.well-known/oauth-authorization-server")).json()
    assert meta["issuer"] == "http://localhost:8000" and meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["registration_endpoint"].endswith("/oauth/register")

    org_id = await signup(api, "dev@acme.example")
    client = await register(api)
    assert client["client_id"].startswith("mcl_") and "client_secret" not in client
    code, verifier = await authorize(api, client["client_id"], org_id)

    # Wrong verifier fails, and burns the code (single use).
    bad = await token(
        api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
        client_id=client["client_id"], code_verifier=pkce()[0],
    )
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    code, verifier = await authorize(api, client["client_id"], org_id)
    res = await token(
        api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
        client_id=client["client_id"], code_verifier=verifier,
    )
    assert res.status_code == 200, res.text
    tokens = res.json()
    assert tokens["token_type"] == "Bearer" and tokens["expires_in"] == 3600
    assert tokens["access_token"].startswith("msr_") and tokens["refresh_token"].startswith("msrt_")
    assert res.headers["cache-control"] == "no-store"
    again = await token(
        api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
        client_id=client["client_id"], code_verifier=verifier,
    )
    assert again.json()["error"] == "invalid_grant"

    # The access token works like an API key, as the user (whoami says OAuth + client).
    api.cookies.clear()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    who = (await api.get("/api/v1/cli/whoami", headers=bearer)).json()
    assert who["auth"] == "oauth" and who["oauth"]["client_name"] == "Claude Code" and who["role"] == "builder"
    assert (await api.post("/api/v1/projects", json={"name": "Desde MCP"}, headers=bearer)).status_code == 201
    verified = await MesserTokenVerifier(BASE).verify_token(tokens["access_token"])
    assert verified is not None and verified.client_id == client["client_id"] and verified.expires_at

    # Refresh rotates both tokens; the old ones stop working.
    res = await token(api, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client["client_id"])
    assert res.status_code == 200, res.text
    fresh = res.json()
    assert fresh["access_token"] != tokens["access_token"]
    assert (await api.get("/api/v1/projects", headers=bearer)).status_code == 401
    new_bearer = {"Authorization": f"Bearer {fresh['access_token']}"}
    assert (await api.get("/api/v1/projects", headers=new_bearer)).status_code == 200
    reused = await token(api, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client["client_id"])
    assert reused.json()["error"] == "invalid_grant"

    # The grant appears in Settings → API keys and among connected applications.
    keys = (await api.get("/api/v1/api-keys", headers=new_bearer)).json()
    assert any(k["name"].startswith("OAuth · Claude Code") for k in keys)
    grants = (await api.get("/api/v1/oauth/grants", headers=new_bearer)).json()
    assert len(grants) == 1 and grants[0]["client_name"] == "Claude Code"

    # Revocation (RFC 7009) ends the grant.
    assert (await api.post("/oauth/revoke", data={"token": fresh["refresh_token"], "client_id": client["client_id"]})).status_code == 200
    assert (await api.get("/api/v1/projects", headers=new_bearer)).status_code == 401
    res = await token(api, grant_type="refresh_token", refresh_token=fresh["refresh_token"], client_id=client["client_id"])
    assert res.json()["error"] == "invalid_grant"
    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action))).scalars())
    assert {"oauth.authorized", "oauth.token_issued", "oauth.token_refreshed", "oauth.revoked"} <= actions


async def test_oauth_tokens_follow_the_users_role_and_expire(api: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    org_id = await signup(api, "owner@acme.example")
    viewer = await make_user(email="viewer@acme.example")
    async with system_session() as s:
        s.add(Membership(org_id=uuid.UUID(org_id), user_id=viewer.id, role="viewer"))
    api.cookies.clear()
    res = await api.post("/api/v1/auth/login", json={"email": "viewer@acme.example", "password": "Sup3rSecret!pass"})
    assert res.status_code == 200
    client = await register(api, scope="projects:read runs:read")
    code, verifier = await authorize(api, client["client_id"], org_id)
    tokens = (
        await token(
            api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=client["client_id"], code_verifier=verifier,
        )
    ).json()
    assert tokens["scope"] == "projects:read runs:read"
    api.cookies.clear()
    bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
    who = (await api.get("/api/v1/cli/whoami", headers=bearer)).json()
    assert who["role"] == "viewer"
    assert (await api.get("/api/v1/projects", headers=bearer)).status_code == 200
    denied = await api.post("/api/v1/projects", json={"name": "No"}, headers=bearer)
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "insufficient_role"

    # Removed from the organization → the token stops working; expired tokens too.
    async with system_session() as s:
        await s.execute(update(ApiKey).where(ApiKey.oauth_grant_id.is_not(None)).values(
            expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    expired = await api.get("/api/v1/projects", headers=bearer)
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "token_expired"
    res = await token(api, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client["client_id"])
    assert res.status_code == 200
    bearer = {"Authorization": f"Bearer {res.json()['access_token']}"}
    async with system_session() as s:
        await s.execute(Membership.__table__.delete().where(Membership.user_id == viewer.id))
    assert (await api.get("/api/v1/projects", headers=bearer)).status_code == 401


async def test_registration_and_authorization_errors(api: httpx.AsyncClient) -> None:
    for body in (
        {"redirect_uris": ["http://evil.example/cb"], "token_endpoint_auth_method": "none"},
        {"redirect_uris": ["javascript:alert(1)"]},
        {"redirect_uris": []},
        {"redirect_uris": [REDIRECT], "grant_types": ["client_credentials"]},
    ):
        res = await api.post("/oauth/register", json=body)
        assert res.status_code == 400, body
        assert res.json()["error"] in ("invalid_redirect_uri", "invalid_client_metadata")
    confidential = await register(api, token_endpoint_auth_method="client_secret_post", client_name="Cursor")
    assert confidential["client_secret"]
    # Native app schemes and loopback with any port are accepted.
    native = await register(api, redirect_uris=["cursor://anysphere.cursor-retrieval/oauth/callback"])
    assert native["redirect_uris"] == ["cursor://anysphere.cursor-retrieval/oauth/callback"]

    public = await register(api)
    _verifier, challenge = pkce()
    base = {
        "response_type": "code", "client_id": public["client_id"], "code_challenge": challenge,
        "code_challenge_method": "S256", "state": "x",
    }
    # Unknown client or unregistered redirect: shown by Messer, never redirected to the client.
    res = await api.get("/oauth/authorize", params={**base, "client_id": "mcl_unknown", "redirect_uri": REDIRECT})
    assert res.status_code == 302 and res.headers["location"].startswith("http://localhost:3000/oauth/authorize?error=")
    res = await api.get("/oauth/authorize", params={**base, "redirect_uri": "http://localhost:9/other"})
    assert res.headers["location"].startswith("http://localhost:3000/oauth/authorize?error=invalid_request")
    # Loopback redirect on another port is fine; missing PKCE goes back to the client with an error.
    res = await api.get("/oauth/authorize", params={**base, "redirect_uri": "http://localhost:51000/callback"})
    assert res.headers["location"].startswith("http://localhost:3000/oauth/authorize?response_type=code")
    no_pkce = {k: v for k, v in base.items() if k != "code_challenge"}
    res = await api.get("/oauth/authorize", params={**no_pkce, "redirect_uri": REDIRECT})
    location = res.headers["location"]
    assert location.startswith(REDIRECT) and "error=invalid_request" in location and "state=x" in location

    # The consent endpoints need a browser session.
    res = await api.get("/api/v1/oauth/authorize/request", params={**base, "redirect_uri": REDIRECT})
    assert res.status_code == 401
    # Confidential clients must authenticate at the token endpoint.
    res = await token(api, grant_type="authorization_code", code="x", client_id=confidential["client_id"])
    assert res.status_code == 401 and res.json()["error"] == "invalid_client"
    res = await token(api, grant_type="password", client_id=public["client_id"])
    assert res.json()["error"] == "unsupported_grant_type"


async def test_denied_consent_and_grant_revocation_from_settings(api: httpx.AsyncClient) -> None:
    org_id = await signup(api, "dev@acme.example")
    client = await register(api)
    _verifier, challenge = pkce()
    params = {
        "response_type": "code", "client_id": client["client_id"], "redirect_uri": REDIRECT,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    }
    denied = await api.post("/api/v1/oauth/authorize", json={**params, "approve": False})
    location = denied.json()["redirect_to"]
    assert "error=access_denied" in location and "state=s" in location
    other_org = str(uuid.uuid4())
    res = await api.post("/api/v1/oauth/authorize", json={**params, "approve": True, "org_id": other_org})
    assert res.status_code == 403

    code, verifier = await authorize(api, client["client_id"], org_id)
    tokens = (
        await token(
            api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
            client_id=client["client_id"], code_verifier=verifier,
        )
    ).json()
    grant_id = (await api.get("/api/v1/oauth/grants")).json()[0]["id"]
    assert (await api.delete(f"/api/v1/oauth/grants/{grant_id}")).status_code == 204
    api.cookies.clear()
    res = await api.get("/api/v1/projects", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert res.status_code == 401
