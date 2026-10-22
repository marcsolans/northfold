"""Helpers shared by the business tests (billing, budgets, backoffice)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from messer_common.db import system_session
from messer_common.db.models import Run

PASSWORD = "Sup3rSecret!pass"


@asynccontextmanager
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    from messer_api.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def login(client: httpx.AsyncClient, email: str, org_id: uuid.UUID | None = None) -> httpx.AsyncClient:
    res = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.text
    if org_id is not None:
        client.headers["X-Messer-Org"] = str(org_id)
    return client


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    ts = timestamp or int(time.time())
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def event(event_type: str, obj: dict[str, Any], *, event_id: str | None = None) -> dict[str, Any]:
    return {
        "id": event_id or f"evt_{uuid.uuid4().hex[:24]}",
        "object": "event",
        "type": event_type,
        "livemode": False,
        "created": int(time.time()),
        "data": {"object": obj},
    }


async def post_event(client: httpx.AsyncClient, evt: dict[str, Any], secret: str) -> httpx.Response:
    body = json.dumps(evt).encode()
    return await client.post(
        "/api/v1/webhooks/stripe",
        content=body,
        headers={"Stripe-Signature": sign(body, secret), "Content-Type": "application/json"},
    )


async def add_run(
    org_id: uuid.UUID, project_id: uuid.UUID, cost_usd: str, *, started_at: datetime | None = None
) -> None:
    async with system_session() as s:
        s.add(
            Run(
                id=uuid.uuid4(),
                org_id=org_id,
                project_id=project_id,
                status="success",
                cost_usd=Decimal(cost_usd),
                started_at=started_at or datetime.now(UTC),
            )
        )
