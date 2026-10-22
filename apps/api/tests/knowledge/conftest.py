"""Fixtures for the knowledge tests: organizations with members, knowledge bases, generated documents.

Knowledge bases create cluster-wide reader roles; they are dropped after every test (before the shared
truncation) so repeated runs do not accumulate roles.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from messer_common.db import Principal, system_session
from messer_common.db.models import ApiKey, KnowledgeBase, User
from messer_common.security import generate_api_key, hash_token

PASSWORD = "Sup3rSecret!pass"


@pytest.fixture(autouse=True)
async def _drop_kb_roles(clean_database: None) -> AsyncIterator[None]:
    yield
    async with system_session() as s:
        rows = await s.execute(text("SELECT schema_name, reader_role FROM public.knowledge_bases"))
        for schema, role in rows.all():
            await s.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            exists = (await s.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role})).first()
            if exists:
                await s.execute(text(f'DROP ROLE "{role}"'))


@dataclass
class Team:
    org_id: uuid.UUID
    owner: User
    admin: User
    builder: User
    viewer: User

    def principal(self, who: str = "owner") -> Principal:
        user: User = getattr(self, who)
        role = "owner" if who == "owner" else who
        return Principal(user_id=user.id, org_id=self.org_id, role=role, email=user.email)


@pytest.fixture
async def team(make_user, make_org) -> Team:  # type: ignore[no-untyped-def]
    admin = await make_user(name="Admin")
    builder = await make_user(name="Builder")
    viewer = await make_user(name="Viewer")
    org, owner = await make_org(
        name=f"Org {uuid.uuid4().hex[:6]}",
        members={str(admin.id): "admin", str(builder.id): "builder", str(viewer.id): "viewer"},
    )
    return Team(org_id=org.id, owner=owner, admin=admin, builder=builder, viewer=viewer)


ClientFactory = Callable[[User], Awaitable[httpx.AsyncClient]]


@pytest.fixture
async def as_user() -> AsyncIterator[ClientFactory]:
    """Logged-in API client per user (separate cookie jars)."""
    from messer_api.main import create_app

    app = create_app()
    clients: list[httpx.AsyncClient] = []

    async def factory(user: User) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=60)
        res = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
        assert res.status_code == 200, res.text
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
async def api_key_client() -> AsyncIterator[Callable[[Team], Awaitable[httpx.AsyncClient]]]:
    from messer_api.main import create_app

    app = create_app()
    clients: list[httpx.AsyncClient] = []

    async def factory(team: Team) -> httpx.AsyncClient:
        key, prefix = generate_api_key()
        async with system_session() as s:
            s.add(
                ApiKey(
                    org_id=team.org_id,
                    name="agent",
                    prefix=prefix,
                    hashed_key=hash_token(key),
                    created_by=team.owner.id,
                )
            )
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": f"Bearer {key}"},
            timeout=60,
        )
        clients.append(client)
        return client

    yield factory
    for client in clients:
        await client.aclose()


@pytest.fixture
async def make_kb() -> Callable[..., Awaitable[KnowledgeBase]]:
    from messer_api.services.knowledge import create_kb

    async def factory(team: Team, name: str = "Base", **kwargs: Any) -> KnowledgeBase:
        kwargs.setdefault("embedding_model", "hash-384")
        return await create_kb(team.principal("owner"), name=name, **kwargs)

    return factory
