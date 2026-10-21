from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from messer_common.testing import configure_test_env

configure_test_env()

import httpx  # noqa: E402

pytest_plugins = ["messer_common.testing.fixtures"]


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from messer_api.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
async def login(client: httpx.AsyncClient):  # type: ignore[no-untyped-def]
    async def do(email: str, password: str = "Sup3rSecret!pass") -> httpx.AsyncClient:
        res = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert res.status_code == 200, res.text
        return client

    return do
