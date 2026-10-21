"""Phase 1 acceptance: sign up, create an organization, invite a viewer, roles enforced."""

from __future__ import annotations

import re

import httpx

from messer_common.email import ConsoleEmailAdapter


def _last_email_url(fragment: str) -> str:
    for email in reversed(ConsoleEmailAdapter.sent):
        m = re.search(rf"(https?://\S*{fragment}\S*)", email.text)
        if m:
            return m.group(1)
    raise AssertionError(f"no email with {fragment}")


async def test_signup_creates_org_with_trial(client: httpx.AsyncClient) -> None:
    res = await client.post(
        "/api/v1/auth/signup",
        json={"email": "ana@example.com", "password": "Contrasena123", "name": "Ana", "org_name": "Facturas SL"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["org_id"]
    assert "messer_at" in res.cookies

    me = (await client.get("/api/v1/me")).json()
    assert me["email"] == "ana@example.com"
    assert me["active_org"]["name"] == "Facturas SL"
    assert me["active_org"]["role"] == "owner"
    assert me["billing"]["status"] == "trialing"
    assert me["billing"]["plan_id"] == "pro"


async def test_signup_rejects_weak_password_and_duplicates(client: httpx.AsyncClient) -> None:
    weak = await client.post("/api/v1/auth/signup", json={"email": "x@example.com", "password": "alllowercase1"})
    assert weak.status_code == 400
    assert weak.json()["error"]["code"] == "weak_password"
    ok = await client.post("/api/v1/auth/signup", json={"email": "x@example.com", "password": "Contrasena123"})
    assert ok.status_code == 200
    dup = await client.post("/api/v1/auth/signup", json={"email": "X@example.com", "password": "Contrasena123"})
    assert dup.status_code == 409


async def test_login_logout_refresh(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user("bob@example.com")
    bad = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"})
    assert bad.status_code == 401
    ok = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "Sup3rSecret!pass"})
    assert ok.status_code == 200
    assert (await client.get("/api/v1/me")).status_code == 200
    refreshed = await client.post("/api/v1/auth/refresh")
    assert refreshed.status_code == 200
    await client.post("/api/v1/auth/logout")
    client.cookies.clear()
    assert (await client.get("/api/v1/me")).status_code == 401


async def test_create_org_and_invite_viewer_flow(make_user) -> None:  # type: ignore[no-untyped-def]
    from messer_api.main import create_app

    app = create_app()
    owner_c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    viewer_c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    async with owner_c, viewer_c:
        await owner_c.post("/api/v1/auth/signup", json={"email": "own@example.com", "password": "Contrasena123"})
        created = await owner_c.post("/api/v1/orgs", json={"name": "Segunda Org"})
        assert created.status_code == 201
        org_id = created.json()["id"]
        owner_c.headers["X-Messer-Org"] = org_id

        inv = await owner_c.post("/api/v1/invitations", json={"email": "vera@example.com", "role": "viewer"})
        assert inv.status_code == 201, inv.text
        url = _last_email_url("/invite/")
        token = url.rsplit("/", 1)[1]

        lookup = await viewer_c.get(f"/api/v1/invitations/lookup/{token}")
        assert lookup.json()["org_name"] == "Segunda Org"

        signup = await viewer_c.post(
            "/api/v1/auth/signup",
            json={"email": "vera@example.com", "password": "Contrasena123", "invitation_token": token},
        )
        assert signup.status_code == 200, signup.text
        assert signup.json()["org_id"] == org_id

        me = (await viewer_c.get("/api/v1/me")).json()
        assert me["active_org"]["role"] == "viewer"

        members = (await owner_c.get("/api/v1/members")).json()
        assert {m["email"]: m["role"] for m in members} == {"own@example.com": "owner", "vera@example.com": "viewer"}

        # Viewers are read-only: inviting or changing roles is forbidden.
        forbidden = await viewer_c.post("/api/v1/invitations", json={"email": "z@example.com", "role": "viewer"})
        assert forbidden.status_code == 403
        assert (await viewer_c.get("/api/v1/members")).status_code == 200

        # Owner promotes the viewer to builder; audit trail records it.
        vera_id = next(m["user_id"] for m in members if m["email"] == "vera@example.com")
        promoted = await owner_c.patch(f"/api/v1/members/{vera_id}", json={"role": "builder"})
        assert promoted.status_code == 200
        audit = (await owner_c.get("/api/v1/audit-log")).json()
        actions = [a["action"] for a in audit]
        assert "member.role_changed" in actions
        assert "invitation.accepted" in actions


async def test_last_owner_cannot_be_demoted(client: httpx.AsyncClient) -> None:
    await client.post("/api/v1/auth/signup", json={"email": "solo@example.com", "password": "Contrasena123"})
    me = (await client.get("/api/v1/me")).json()
    res = await client.patch(f"/api/v1/members/{me['id']}", json={"role": "admin"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "last_owner"


async def test_mfa_totp_login(client: httpx.AsyncClient) -> None:
    import pyotp

    await client.post("/api/v1/auth/signup", json={"email": "mfa@example.com", "password": "Contrasena123"})
    setup = (await client.post("/api/v1/auth/mfa/setup")).json()
    totp = pyotp.TOTP(setup["secret"])
    confirm = await client.post("/api/v1/auth/mfa/confirm", json={"code": totp.now()})
    assert confirm.status_code == 200
    assert len(confirm.json()["recovery_codes"]) == 8
    client.cookies.clear()
    step1 = (
        await client.post("/api/v1/auth/login", json={"email": "mfa@example.com", "password": "Contrasena123"})
    ).json()
    assert step1["mfa_required"] is True
    step2 = await client.post("/api/v1/auth/mfa/verify", json={"mfa_token": step1["mfa_token"], "code": totp.now()})
    assert step2.status_code == 200
    assert (await client.get("/api/v1/me")).json()["mfa_enabled"] is True


async def test_password_reset(client: httpx.AsyncClient, make_user) -> None:  # type: ignore[no-untyped-def]
    user = await make_user("reset@example.com")
    assert (await client.post("/api/v1/auth/password/forgot", json={"email": user.email})).status_code == 200
    token = _last_email_url("reset-password").split("token=")[1]
    res = await client.post("/api/v1/auth/password/reset", json={"token": token, "password": "NuevaClave2026"})
    assert res.status_code == 200
    again = await client.post("/api/v1/auth/password/reset", json={"token": token, "password": "NuevaClave2027"})
    assert again.status_code == 410
    login = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "NuevaClave2026"})
    assert login.status_code == 200
