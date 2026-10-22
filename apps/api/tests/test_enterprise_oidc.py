"""Enterprise SSO over OpenID Connect against an in-process fake identity provider.

The IdP signs id_tokens with an RSA key generated here and serves discovery, JWKS and the token endpoint
through ``httpx.MockTransport``; the browser leg is driven by hand (authorize → callback).
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from enterprise_support import app_client, login, set_plan, verify_domain
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

from messer_api.services import sso as sso_service
from messer_api.services import sso_oidc
from messer_common.db import system_session
from messer_common.db.models import AuditLog, Membership, User
from messer_common.db.models.enterprise import OrgIdentity

ISSUER = "https://idp.acme.test"
CLIENT_ID = "messer-client"
CLIENT_SECRET = "s3cret-value"


class FakeIdp:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = "key-1"
        self.pending: dict[str, dict[str, Any]] = {}
        self.sign_with_rogue = False
        self.nonce_override: str | None = None
        self.token_requests = 0

    def jwks(self) -> dict[str, Any]:
        jwk = json.loads(RSAAlgorithm.to_jwk(self.key.public_key()))
        jwk.update({"kid": self.kid, "use": "sig", "alg": "RS256"})
        return {"keys": [jwk]}

    def authorize(self, url: str, claims: dict[str, Any]) -> tuple[str, str]:
        """Simulate the user signing in at the IdP: returns (code, state)."""
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        assert url.startswith(f"{ISSUER}/authorize")
        assert query["client_id"] == CLIENT_ID and query["response_type"] == "code"
        assert query["code_challenge_method"] == "S256"
        assert query["redirect_uri"] == "http://localhost:3000/api/v1/sso/oidc/callback"
        code = secrets.token_urlsafe(16)
        self.pending[code] = {"nonce": query["nonce"], "challenge": query["code_challenge"], "claims": claims}
        return code, query["state"]

    def id_token(self, nonce: str, claims: dict[str, Any]) -> str:
        now = int(time.time())
        body = {"iss": ISSUER, "aud": CLIENT_ID, "iat": now, "exp": now + 300, "nonce": nonce, **claims}
        key = self.rogue_key if self.sign_with_rogue else self.key
        return jwt.encode(body, key, algorithm="RS256", headers={"kid": self.kid})

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": f"{ISSUER}/authorize",
                    "token_endpoint": f"{ISSUER}/token",
                    "jwks_uri": f"{ISSUER}/jwks",
                    "userinfo_endpoint": f"{ISSUER}/userinfo",
                    "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
                },
            )
        if url == f"{ISSUER}/jwks":
            return httpx.Response(200, json=self.jwks())
        if url == f"{ISSUER}/token" and request.method == "POST":
            self.token_requests += 1
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            expected = "Basic " + base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
            if request.headers.get("authorization") != expected:
                return httpx.Response(401, json={"error": "invalid_client"})
            grant = self.pending.pop(form.get("code", ""), None)
            if grant is None:
                return httpx.Response(400, json={"error": "invalid_grant"})
            digest = hashlib.sha256(form["code_verifier"].encode()).digest()
            if base64.urlsafe_b64encode(digest).rstrip(b"=").decode() != grant["challenge"]:
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "PKCE"})
            nonce = self.nonce_override or grant["nonce"]
            return httpx.Response(
                200,
                json={
                    "access_token": "at-" + secrets.token_hex(8),
                    "token_type": "Bearer",
                    "id_token": self.id_token(nonce, grant["claims"]),
                },
            )
        if url == f"{ISSUER}/userinfo":
            return httpx.Response(200, json={})
        return httpx.Response(404, json={"error": "not_found"})


@pytest.fixture
async def idp() -> AsyncIterator[FakeIdp]:
    fake = FakeIdp()
    sso_oidc.set_http_transport(httpx.MockTransport(fake.handler))
    yield fake
    sso_oidc.set_http_transport(None)


async def _setup(
    client: httpx.AsyncClient, make_org: Any, *, verified: bool = True, jit: bool = True
) -> dict[str, Any]:
    org, owner = await make_org(name="Acme")
    await set_plan(org.id, "enterprise")
    if verified:
        await verify_domain(org.id, "acme-sso.eu")
    await login(client, owner.email)
    res = await client.post(
        "/api/v1/sso/connections",
        json={
            "type": "oidc",
            "name": "Acme Entra",
            "domain": "acme-sso.eu",
            "default_role": "viewer",
            "config": {
                "preset": "generic",
                "issuer": ISSUER,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "groups_claim": "groups",
                "jit_provisioning": jit,
            },
        },
    )
    assert res.status_code == 201, res.text
    conn = res.json()
    assert conn["config"]["client_secret_set"] is True and "client_secret" not in conn["config"]
    assert conn["service_provider"]["redirect_uri"].endswith("/api/v1/sso/oidc/callback")
    res = await client.post(
        f"/api/v1/sso/connections/{conn['id']}/mappings", json={"external_group": "Messer Admins", "role": "admin"}
    )
    assert res.status_code == 201, res.text
    return {"org": org, "owner": owner, "conn": conn}


async def _browser_login(idp: FakeIdp, claims: dict[str, Any], *, start: str | None = None) -> httpx.Response:
    async with app_client() as browser:
        if start is None:
            res = await browser.post("/api/v1/sso/discover", json={"email": claims["email"], "next": "/app/projects"})
            assert res.status_code == 200, res.text
            start = str(res.json()["redirect_url"])
        res = await browser.get(start)
        assert res.status_code == 302, res.text
        code, state = idp.authorize(res.headers["location"], claims)
        res = await browser.get("/api/v1/sso/oidc/callback", params={"code": code, "state": state})
        res.extensions["browser_cookies"] = dict(browser.cookies)
        res.extensions["state"] = state
        if res.status_code == 303 and "messer_at" in browser.cookies:
            me = await browser.get("/api/v1/me")
            res.extensions["me"] = me.json()
        return res


async def test_oidc_login_creates_user_with_mapped_role_and_session(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    claims = {"sub": "entra-oid-123", "email": "ana@acme-sso.eu", "name": "Ana Pérez", "groups": ["Messer Admins", "x"]}
    res = await _browser_login(idp, claims)
    assert res.status_code == 303, res.text
    assert res.headers["location"] == "http://localhost:3000/app/projects"
    assert "messer_at" in res.extensions["browser_cookies"]
    me = res.extensions["me"]
    assert me["email"] == "ana@acme-sso.eu"
    assert me["active_org"]["id"] == str(ctx["org"].id) and me["active_org"]["role"] == "admin"

    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == "ana@acme-sso.eu"))).scalar_one()
        membership = (
            await s.execute(select(Membership).where(Membership.org_id == ctx["org"].id, Membership.user_id == user.id))
        ).scalar_one()
        ident = (await s.execute(select(OrgIdentity).where(OrgIdentity.user_id == user.id))).scalar_one()
        actions = {a for (a,) in await s.execute(select(AuditLog.action).where(AuditLog.org_id == ctx["org"].id))}
    assert membership.role == "admin" and membership.source == "sso"
    assert ident.sso_subject == "entra-oid-123" and ident.sso_groups == ["Messer Admins", "x"]
    assert {"sso.login", "sso.user_provisioned", "member.provisioned"} <= actions

    # Second login: same subject, groups changed → role follows the mapping (IdP-managed membership).
    res = await _browser_login(idp, {**claims, "groups": ["x"]})
    assert res.status_code == 303
    assert res.extensions["me"]["active_org"]["role"] == "viewer"


async def test_oidc_rejects_forged_token_nonce_and_foreign_domain(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    await _setup(client, make_org)
    idp.sign_with_rogue = True
    res = await _browser_login(idp, {"sub": "1", "email": "ana@acme-sso.eu"})
    assert res.status_code == 303 and res.headers["location"].endswith("/sso/error?code=invalid_id_token")
    assert "messer_at" not in res.extensions["browser_cookies"]

    idp.sign_with_rogue = False
    idp.nonce_override = "replayed-nonce"
    res = await _browser_login(idp, {"sub": "1", "email": "ana@acme-sso.eu"})
    assert res.headers["location"].endswith("/sso/error?code=nonce_mismatch")

    idp.nonce_override = None
    async with app_client() as browser:
        start = (await browser.post("/api/v1/sso/discover", json={"email": "ana@acme-sso.eu"})).json()["redirect_url"]
    res = await _browser_login(idp, {"sub": "2", "email": "mallory@evil-corp.eu"}, start=start)
    assert res.headers["location"].endswith("/sso/error?code=domain_mismatch")
    async with system_session() as s:
        assert (await s.execute(select(User).where(User.email == "mallory@evil-corp.eu"))).first() is None
        failures = (await s.execute(select(AuditLog).where(AuditLog.action == "sso.login_failed"))).scalars().all()
    assert len(failures) == 3


async def test_oidc_state_is_single_use(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    await _setup(client, make_org)
    res = await _browser_login(idp, {"sub": "s1", "email": "ana@acme-sso.eu"})
    assert res.status_code == 303
    async with app_client() as browser:
        replay = await browser.get("/api/v1/sso/oidc/callback", params={"code": "x", "state": res.extensions["state"]})
    assert replay.headers["location"].endswith("/sso/error?code=state_expired")


async def test_unverified_domain_is_not_discoverable_and_cannot_log_in(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org, verified=False)
    async with app_client() as browser:
        res = await browser.post("/api/v1/sso/discover", json={"email": "ana@acme-sso.eu"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "sso_not_configured"
    res = await _browser_login(
        idp, {"sub": "1", "email": "ana@acme-sso.eu"}, start=f"/api/v1/sso/connections/{ctx['conn']['id']}/start"
    )
    assert res.headers["location"].endswith("/sso/error?code=domain_not_verified")
    # Enforcing SSO requires the verified domain.
    res = await client.patch(f"/api/v1/sso/connections/{ctx['conn']['id']}", json={"enforce": True})
    assert res.status_code == 409 and res.json()["error"]["code"] == "domain_not_verified"


async def test_jit_disabled_refuses_unknown_users(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    await _setup(client, make_org, jit=False)
    res = await _browser_login(idp, {"sub": "1", "email": "new@acme-sso.eu"})
    assert res.headers["location"].endswith("/sso/error?code=jit_disabled")


async def test_domain_verification_and_enforced_sso_blocks_password_login(
    client, make_org, make_user, idp, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    org, owner = await make_org(name="Acme")
    await set_plan(org.id, "enterprise")
    await login(client, owner.email)
    res = await client.post("/api/v1/sso/domains", json={"domain": "ACME-sso.eu"})
    assert res.status_code == 201, res.text
    domain = res.json()
    assert domain["domain"] == "acme-sso.eu" and domain["verified_at"] is None
    record = domain["record"]
    assert record["name"] == "_messer-challenge.acme-sso.eu"

    async def no_record(name: str) -> list[str]:
        return []

    monkeypatch.setattr(sso_service, "lookup_txt", no_record)
    res = await client.post(f"/api/v1/sso/domains/{domain['id']}/verify")
    assert res.status_code == 409 and res.json()["error"]["code"] == "domain_unverified"

    async def with_record(name: str) -> list[str]:
        return [record["value"]] if name == record["name"] else []

    monkeypatch.setattr(sso_service, "lookup_txt", with_record)
    res = await client.post(f"/api/v1/sso/domains/{domain['id']}/verify")
    assert res.status_code == 200 and res.json()["verified_at"] and res.json()["verification_method"] == "dns"

    employee = await make_user("emp@acme-sso.eu")
    res = await client.post(
        "/api/v1/sso/connections",
        json={
            "type": "oidc",
            "name": "Okta",
            "domain": "acme-sso.eu",
            "enforce": True,
            "config": {"preset": "okta", "issuer": ISSUER, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET},
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["domain_verified"] is True and res.json()["config"]["groups_claim"] == "groups"
    async with app_client() as anon:
        res = await anon.post("/api/v1/auth/login", json={"email": employee.email, "password": "Sup3rSecret!pass"})
        assert res.status_code == 403 and res.json()["error"]["code"] == "sso_required"
        # Other domains are not affected.
        res = await anon.post("/api/v1/auth/login", json={"email": owner.email, "password": "Sup3rSecret!pass"})
        assert res.status_code == 200
    # The domain cannot be removed while SSO is enforced on it.
    res = await client.delete(f"/api/v1/sso/domains/{domain['id']}")
    assert res.status_code == 409


async def test_sso_requires_plan_feature(client, make_org) -> None:  # type: ignore[no-untyped-def]
    _, owner = await make_org(name="Small")
    await login(client, owner.email)  # trial on Pro: no SSO
    res = await client.get("/api/v1/sso/overview")
    assert res.status_code == 200
    assert res.json()["sso_available"] is False and res.json()["sso_upgrade_to"] == "business"
    res = await client.post(
        "/api/v1/sso/connections",
        json={
            "type": "oidc",
            "name": "x",
            "domain": "small-co.eu",
            "config": {"issuer": ISSUER, "client_id": "a", "client_secret": "b"},
        },
    )
    assert res.status_code == 402 and res.json()["error"]["details"]["feature"] == "sso"
    res = await client.post("/api/v1/sso/scim/tokens", json={"name": "Okta"})
    assert res.status_code == 402 and res.json()["error"]["details"]["feature"] == "scim"


async def test_admin_test_login_is_a_dry_run(client, make_org, idp) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    res = await client.get(f"/api/v1/sso/connections/{ctx['conn']['id']}/start", params={"test": "true"})
    assert res.status_code == 302
    code, state = idp.authorize(
        res.headers["location"], {"sub": "t1", "email": "tester@acme-sso.eu", "groups": ["Messer Admins"]}
    )
    async with app_client() as browser:
        res = await browser.get("/api/v1/sso/oidc/callback", params={"code": code, "state": state})
    assert res.status_code == 303 and "test_result=" in res.headers["location"]
    key = parse_qs(urlsplit(res.headers["location"]).query)["test_result"][0]
    result = (await client.get(f"/api/v1/sso/test-results/{key}")).json()
    assert result["ok"] is True and result["role"] == "admin" and result["user_exists"] is False
    assert result["matched_groups"] == ["Messer Admins"]
    async with system_session() as s:
        assert (await s.execute(select(User).where(User.email == "tester@acme-sso.eu"))).first() is None
    # Anonymous users cannot run a test login.
    async with app_client() as anon:
        res = await anon.get(f"/api/v1/sso/connections/{ctx['conn']['id']}/start", params={"test": "true"})
    assert res.headers["location"].endswith("/sso/error?code=not_authenticated")


async def test_connection_crud_and_mappings(client, make_org) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    cid = ctx["conn"]["id"]
    res = await client.patch(
        f"/api/v1/sso/connections/{cid}", json={"name": "Renamed", "config": {"scopes": ["openid", "email"]}}
    )
    assert res.status_code == 200, res.text
    assert res.json()["name"] == "Renamed" and res.json()["config"]["client_secret_set"] is True
    mappings = (await client.get(f"/api/v1/sso/connections/{cid}/mappings")).json()
    assert [m["external_group"] for m in mappings] == ["Messer Admins"]
    dup = await client.post(
        f"/api/v1/sso/connections/{cid}/mappings", json={"external_group": "messer admins", "role": "viewer"}
    )
    assert dup.status_code == 409
    owner_map = await client.post(
        f"/api/v1/sso/connections/{cid}/mappings", json={"external_group": "o", "role": "owner"}
    )
    assert owner_map.status_code == 422
    assert (await client.delete(f"/api/v1/sso/connections/{cid}/mappings/{mappings[0]['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/sso/connections/{cid}")).status_code == 204
    assert (await client.get("/api/v1/sso/connections")).json() == []
