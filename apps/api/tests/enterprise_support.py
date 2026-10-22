"""Helpers shared by the enterprise test modules (plans, verified domains, signed-in clients)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import update

from messer_common.db import system_session
from messer_common.db.models import Org, Subscription
from messer_common.db.models.enterprise import OrgDomain

PASSWORD = "Sup3rSecret!pass"


async def set_plan(org_id: uuid.UUID, plan_id: str) -> None:
    async with system_session() as s:
        await s.execute(update(Org).where(Org.id == org_id).values(plan_id=plan_id))
        await s.execute(
            update(Subscription).where(Subscription.org_id == org_id).values(plan_id=plan_id, status="active")
        )


async def verify_domain(org_id: uuid.UUID, domain: str) -> None:
    async with system_session() as s:
        s.add(
            OrgDomain(
                org_id=org_id,
                domain=domain,
                verification_token=uuid.uuid4().hex,
                verified_at=datetime.now(UTC),
                verification_method="manual",
            )
        )


async def login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> None:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text


def app_client() -> httpx.AsyncClient:
    from messer_api.main import create_app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://testserver")
