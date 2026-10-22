"""SCIM 2.0 provisioning with Okta- and Microsoft Entra ID-like request flows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from enterprise_support import app_client, login, set_plan, verify_domain
from sqlalchemy import select

from messer_api.services import scim
from messer_common.db import system_session
from messer_common.db.models import AuthSession, Membership, User

SCIM = "/scim/v2"
USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
PATCH_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:Error"


async def _setup(client: httpx.AsyncClient, make_org: Any, plan: str = "enterprise") -> dict[str, Any]:
    org, owner = await make_org(name="Acme SCIM")
    await set_plan(org.id, plan)
    await verify_domain(org.id, "acme-sso.eu")
    await login(client, owner.email)
    res = await client.post(
        "/api/v1/sso/connections",
        json={
            "type": "oidc",
            "name": "Entra",
            "domain": "acme-sso.eu",
            "default_role": "viewer",
            "config": {"issuer": "https://idp.acme.test", "client_id": "c", "client_secret": "s"},
        },
    )
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    for group, role in (("Engineering", "builder"), ("Messer Admins", "admin")):
        assert (
            await client.post(f"/api/v1/sso/connections/{cid}/mappings", json={"external_group": group, "role": role})
        ).status_code == 201
    res = await client.post("/api/v1/sso/scim/tokens", json={"name": "Okta"})
    assert res.status_code == 201, res.text
    token = res.json()["token"]
    assert token.startswith("scim_")
    return {"org": org, "owner": owner, "token": token, "headers": {"Authorization": f"Bearer {token}"}}


async def _membership(org_id: uuid.UUID, user_id: str) -> Membership | None:
    async with system_session() as s:
        return (
            await s.execute(
                select(Membership).where(Membership.org_id == org_id, Membership.user_id == uuid.UUID(user_id))
            )
        ).scalar_one_or_none()


async def test_okta_flow_create_group_deactivate_reactivate_delete(client, make_org) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    h = ctx["headers"]
    async with app_client() as idp:
        res = await idp.get(
            f"{SCIM}/Users",
            params={"filter": 'userName eq "bob@acme-sso.eu"', "startIndex": 1, "count": 100},
            headers=h,
        )
        assert res.status_code == 200 and res.headers["content-type"].startswith("application/scim+json")
        assert res.json()["totalResults"] == 0

        res = await idp.post(
            f"{SCIM}/Users",
            headers=h,
            json={
                "schemas": [USER_SCHEMA],
                "userName": "bob@acme-sso.eu",
                "name": {"givenName": "Bob", "familyName": "Martín"},
                "emails": [{"primary": True, "value": "bob@acme-sso.eu", "type": "work"}],
                "displayName": "Bob Martín",
                "active": True,
                "externalId": "00u1okta",
            },
        )
        assert res.status_code == 201, res.text
        user = res.json()
        uid = user["id"]
        assert res.headers["location"].endswith(f"/scim/v2/Users/{uid}")
        assert user["active"] is True and user["userName"] == "bob@acme-sso.eu" and user["externalId"] == "00u1okta"
        membership = await _membership(ctx["org"].id, uid)
        assert membership is not None and membership.role == "viewer" and membership.source == "scim"

        dup = await idp.post(f"{SCIM}/Users", headers=h, json={"schemas": [USER_SCHEMA], "userName": "bob@acme-sso.eu"})
        assert (
            dup.status_code == 409 and dup.json()["scimType"] == "uniqueness" and ERROR_SCHEMA in dup.json()["schemas"]
        )

        res = await idp.get(f"{SCIM}/Users", params={"filter": 'userName eq "BOB@acme-sso.eu"'}, headers=h)
        assert res.json()["totalResults"] == 1 and res.json()["Resources"][0]["id"] == uid

        # Group push: membership in "Engineering" maps to builder.
        res = await idp.post(
            f"{SCIM}/Groups",
            headers=h,
            json={
                "schemas": ["urn:ietf:params:scim:schemas:core:2.0:Group"],
                "displayName": "Engineering",
                "members": [{"value": uid}],
            },
        )
        assert res.status_code == 201, res.text
        gid = res.json()["id"]
        assert [m["value"] for m in res.json()["members"]] == [uid]
        assert (await _membership(ctx["org"].id, uid)).role == "builder"  # type: ignore[union-attr]

        # Okta deactivation: {"op": "replace", "value": {"active": false}} → membership removed, sessions revoked.
        async with system_session() as s:
            s.add(
                AuthSession(
                    user_id=uuid.UUID(uid),
                    refresh_token_hash=uuid.uuid4().hex,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        res = await idp.patch(
            f"{SCIM}/Users/{uid}",
            headers=h,
            json={"schemas": [PATCH_SCHEMA], "Operations": [{"op": "replace", "value": {"active": False}}]},
        )
        assert res.status_code == 200, res.text
        assert res.json()["active"] is False
        assert await _membership(ctx["org"].id, uid) is None
        async with system_session() as s:
            sessions = (
                (await s.execute(select(AuthSession).where(AuthSession.user_id == uuid.UUID(uid)))).scalars().all()
            )
        assert sessions and all(x.revoked_at is not None for x in sessions)
        res = await idp.get(f"{SCIM}/Users/{uid}", headers=h)
        assert res.status_code == 200 and res.json()["active"] is False

        # Entra-style reactivation with a string boolean; the group-derived role comes back.
        res = await idp.patch(
            f"{SCIM}/Users/{uid}",
            headers=h,
            json={"schemas": [PATCH_SCHEMA], "Operations": [{"op": "Replace", "path": "active", "value": "True"}]},
        )
        assert res.status_code == 200 and res.json()["active"] is True
        assert (await _membership(ctx["org"].id, uid)).role == "builder"  # type: ignore[union-attr]

        # Remove from the group (Okta path filter) → back to the default role.
        res = await idp.patch(
            f"{SCIM}/Groups/{gid}",
            headers=h,
            json={"schemas": [PATCH_SCHEMA], "Operations": [{"op": "remove", "path": f'members[value eq "{uid}"]'}]},
        )
        assert res.status_code == 204, res.text
        assert (await _membership(ctx["org"].id, uid)).role == "viewer"  # type: ignore[union-attr]

        res = await idp.delete(f"{SCIM}/Users/{uid}", headers=h)
        assert res.status_code == 204
        res = await idp.get(f"{SCIM}/Users/{uid}", headers=h)
        assert res.status_code == 404 and res.json()["schemas"] == [ERROR_SCHEMA] and res.json()["status"] == "404"
        assert await _membership(ctx["org"].id, uid) is None


async def test_entra_flow_patch_attributes_and_group_membership(client, make_org) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    h = ctx["headers"]
    async with app_client() as idp:
        res = await idp.get(f"{SCIM}/Users", params={"filter": 'userName eq "carla@acme-sso.eu"'}, headers=h)
        assert res.json()["Resources"] == []
        res = await idp.post(
            f"{SCIM}/Users",
            headers=h,
            json={
                "schemas": [USER_SCHEMA, "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"],
                "externalId": "carla",
                "userName": "carla@acme-sso.eu",
                "active": True,
                "displayName": "Carla",
                "emails": [{"primary": True, "type": "work", "value": "carla@acme-sso.eu"}],
                "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User": {"department": "Finance"},
            },
        )
        assert res.status_code == 201, res.text
        uid = res.json()["id"]
        res = await idp.patch(
            f"{SCIM}/Users/{uid}",
            headers=h,
            json={
                "schemas": [PATCH_SCHEMA],
                "Operations": [
                    {"op": "Replace", "path": "name.givenName", "value": "Carla"},
                    {"op": "Replace", "path": "name.familyName", "value": "Ruiz"},
                    {"op": "Add", "path": "title", "value": "Controller"},
                    {
                        "op": "Replace",
                        "path": "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User:department",
                        "value": "Treasury",
                    },
                ],
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["name"]["familyName"] == "Ruiz" and body["title"] == "Controller"
        assert body["urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"]["department"] == "Treasury"
        async with system_session() as s:
            user = await s.get(User, uuid.UUID(uid))
        assert user is not None and user.name == "Carla"

        res = await idp.post(f"{SCIM}/Groups", headers=h, json={"displayName": "Messer Admins", "externalId": "g-1"})
        gid = res.json()["id"]
        res = await idp.get(
            f"{SCIM}/Groups",
            params={"filter": 'displayName eq "messer admins"', "excludedAttributes": "members"},
            headers=h,
        )
        assert res.json()["totalResults"] == 1 and "members" not in res.json()["Resources"][0]
        res = await idp.patch(
            f"{SCIM}/Groups/{gid}",
            headers=h,
            json={
                "schemas": [PATCH_SCHEMA],
                "Operations": [{"op": "Add", "path": "members", "value": [{"value": uid}]}],
            },
        )
        assert res.status_code == 204
        assert (await _membership(ctx["org"].id, uid)).role == "admin"  # type: ignore[union-attr]
        res = await idp.get(f"{SCIM}/Users/{uid}", headers=h)
        assert [g["display"] for g in res.json()["groups"]] == ["Messer Admins"]
        # Membership check Entra performs before updates.
        res = await idp.get(
            f"{SCIM}/Groups", params={"filter": f'id eq "{gid}" and members[value eq "{uid}"]'}, headers=h
        )
        assert res.json()["totalResults"] == 1
        res = await idp.patch(
            f"{SCIM}/Groups/{gid}",
            headers=h,
            json={
                "schemas": [PATCH_SCHEMA],
                "Operations": [{"op": "Remove", "path": "members", "value": [{"value": uid}]}],
            },
        )
        assert res.status_code == 204
        assert (await _membership(ctx["org"].id, uid)).role == "viewer"  # type: ignore[union-attr]
        assert (await idp.delete(f"{SCIM}/Groups/{gid}", headers=h)).status_code == 204


async def test_scim_auth_plan_domain_and_discovery(client, make_org) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    h = ctx["headers"]
    async with app_client() as idp:
        res = await idp.get(f"{SCIM}/Users")
        assert res.status_code == 401 and res.json()["schemas"] == [ERROR_SCHEMA]
        res = await idp.get(f"{SCIM}/Users", headers={"Authorization": "Bearer scim_wrong"})
        assert res.status_code == 401
        for path in (
            "ServiceProviderConfig",
            "ResourceTypes",
            "Schemas",
            "ResourceTypes/User",
            f"Schemas/{USER_SCHEMA}",
        ):
            assert (await idp.get(f"{SCIM}/{path}", headers=h)).status_code == 200, path
        assert (await idp.get(f"{SCIM}/ServiceProviderConfig", headers=h)).json()["patch"]["supported"] is True

        res = await idp.post(f"{SCIM}/Users", headers=h, json={"userName": "x@unverified-co.eu"})
        assert res.status_code == 400 and res.json()["scimType"] == "invalidValue"
        res = await idp.post(f"{SCIM}/Users", headers=h, content=b"not json")
        assert res.status_code == 400 and res.json()["scimType"] == "invalidSyntax"
        res = await idp.get(f"{SCIM}/Users", params={"filter": "userName eq"}, headers=h)
        assert res.status_code == 400 and res.json()["scimType"] == "invalidFilter"

        # Downgrade: SCIM stops working (403); revoked tokens stop working (401).
        await set_plan(ctx["org"].id, "business")
        assert (await idp.get(f"{SCIM}/Users", headers=h)).status_code == 403
        await set_plan(ctx["org"].id, "enterprise")
        tokens = (await client.get("/api/v1/sso/scim/tokens")).json()
        assert (await client.delete(f"/api/v1/sso/scim/tokens/{tokens[0]['id']}")).status_code == 204
        assert (await idp.get(f"{SCIM}/Users", headers=h)).status_code == 401


async def test_scim_cannot_deprovision_last_owner(client, make_org) -> None:  # type: ignore[no-untyped-def]
    ctx = await _setup(client, make_org)
    h = ctx["headers"]
    async with app_client() as idp:
        res = await idp.post(f"{SCIM}/Users", headers=h, json={"userName": ctx["owner"].email})
        assert res.status_code == 201, res.text  # existing account outside the verified domain is linked, not created
        uid = res.json()["id"]
        assert uid == str(ctx["owner"].id)
        res = await idp.patch(
            f"{SCIM}/Users/{uid}",
            headers=h,
            json={"schemas": [PATCH_SCHEMA], "Operations": [{"op": "replace", "path": "active", "value": False}]},
        )
        assert res.status_code == 400 and res.json()["scimType"] == "mutability"
        assert (await _membership(ctx["org"].id, uid)).role == "owner"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ('userName eq "Bob@acme-sso.eu"', True),
        ('emails[type eq "work" and value co "acme"]', True),
        ('name.givenName sw "B" and active eq true', True),
        ("not (active eq true)", False),
        ('externalId eq "00U1"', False),
        ("title pr", False),
        ('userName ne "x" or title pr', True),
    ],
)
def test_filter_parser(expression: str, expected: bool) -> None:
    resource = {
        "userName": "bob@acme-sso.eu",
        "externalId": "00u1",
        "name": {"givenName": "Bob"},
        "emails": [{"value": "bob@acme-sso.eu", "type": "work"}],
        "active": True,
    }
    assert scim.matches(scim.parse_filter(expression), resource) is expected
