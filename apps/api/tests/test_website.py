"""Public website endpoints: contact form, public status page and credit pricing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from messer_api.services.service_health import HISTORY_DAYS, public_summary, record_check
from messer_common.db import system_session
from messer_common.db.models import ContactRequest
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import get_settings

CONTACT = {
    "name": "Lucía Ferrer",
    "email": "lucia@clinicanorte.es",
    "company": "Clínica Norte",
    "message": "Queremos automatizar la clasificación de facturas de proveedores.\nSomos 40 personas.",
    "topic": "enterprise",
    "locale": "es",
}


async def _contacts() -> list[ContactRequest]:
    async with system_session() as s:
        return list((await s.execute(select(ContactRequest).order_by(ContactRequest.created_at))).scalars())


@pytest.fixture(autouse=True)
def _clear_outbox() -> None:
    ConsoleEmailAdapter.sent.clear()


# ---------------------------------------------------------------- contact


async def test_contact_stores_request_and_emails_sales(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/v1/contact", json=CONTACT)
    assert res.status_code == 202, res.text
    assert res.json() == {"ok": True}

    rows = await _contacts()
    assert len(rows) == 1
    row = rows[0]
    assert (row.name, row.email, row.company, row.topic, row.status) == (
        "Lucía Ferrer",
        "lucia@clinicanorte.es",
        "Clínica Norte",
        "enterprise",
        "new",
    )
    assert "40 personas" in row.message

    sent = [e for e in ConsoleEmailAdapter.sent if "contact_received" in e.tags]
    assert len(sent) == 1
    email = sent[0]
    assert email.to == get_settings().sales_email
    assert email.reply_to == "lucia@clinicanorte.es"
    assert "Lucía Ferrer" in email.subject and "Clínica Norte" in email.subject
    assert "plan Enterprise" in email.text
    assert "clasificación de facturas" in email.text
    assert email.headers["X-Messer-Contact-Id"] == str(row.id)


async def test_contact_validation(client: httpx.AsyncClient) -> None:
    cases = [
        {**CONTACT, "email": "not-an-email"},
        {**CONTACT, "name": "   "},
        {**CONTACT, "message": "corto"},
        {**CONTACT, "message": "x" * 5001},
        {**CONTACT, "topic": "free-pizza"},
        {**CONTACT, "name": "Eve\r\nBcc: victim@example.com"},
        {k: v for k, v in CONTACT.items() if k != "message"},
    ]
    for i, body in enumerate(cases):
        # Invalid attempts also count towards the rate limit, so each case comes from its own address.
        res = await client.post("/api/v1/contact", json=body, headers={"X-Forwarded-For": f"198.51.100.{i + 1}"})
        assert res.status_code == 422, (body, res.text)
        assert res.json()["error"]["code"] == "validation_error"
    assert await _contacts() == []
    assert ConsoleEmailAdapter.sent == []


async def test_contact_strips_whitespace_and_optional_company(client: httpx.AsyncClient) -> None:
    body = {**CONTACT, "name": "  Ana  ", "company": "   ", "topic": "support"}
    res = await client.post("/api/v1/contact", json=body)
    assert res.status_code == 202
    [row] = await _contacts()
    assert row.name == "Ana"
    assert row.company is None
    assert "—" in ConsoleEmailAdapter.sent[-1].subject


async def test_contact_honeypot_is_silently_dropped(client: httpx.AsyncClient) -> None:
    res = await client.post("/api/v1/contact", json={**CONTACT, "website": "https://spam.example"})
    assert res.status_code == 202
    assert res.json() == {"ok": True}
    assert await _contacts() == []
    assert ConsoleEmailAdapter.sent == []


async def test_contact_is_rate_limited_per_ip(client: httpx.AsyncClient) -> None:
    for _ in range(5):
        assert (await client.post("/api/v1/contact", json=CONTACT)).status_code == 202
    blocked = await client.post("/api/v1/contact", json=CONTACT)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.json()["error"]["details"]["retry_after"] > 0
    assert len(await _contacts()) == 5
    # Another client IP is not affected.
    other = await client.post("/api/v1/contact", json=CONTACT, headers={"X-Forwarded-For": "203.0.113.7"})
    assert other.status_code == 202


# ---------------------------------------------------------------- status


async def test_public_status_without_data_is_unknown(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/status/public")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "unknown"
    assert [s["key"] for s in body["services"]] == ["web", "api", "runtime", "worker", "scheduler", "voice", "mcp"]
    for service in body["services"]:
        assert service["status"] == "unknown"
        assert len(service["days"]) == HISTORY_DAYS
        assert {d["status"] for d in service["days"]} == {"no_data"}
        assert service["uptime_90d"] is None
    assert res.headers["cache-control"] == "public, max-age=30"


async def test_public_status_reports_history_and_incidents(client: httpx.AsyncClient) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    yesterday = now - timedelta(days=1)
    async with system_session() as s:
        for service in ("web", "api", "runtime", "worker", "scheduler", "voice", "mcp"):
            await record_check(s, service=service, status="operational", latency_ms=40, detail=None, now=yesterday)
        # API outage yesterday: 2 failed checks out of 4 → red bar; recovered.
        await record_check(
            s,
            service="api",
            status="down",
            latency_ms=None,
            detail="ConnectError api.internal",
            now=yesterday + timedelta(minutes=1),
        )
        await record_check(
            s,
            service="api",
            status="down",
            latency_ms=None,
            detail="ConnectError api.internal",
            now=yesterday + timedelta(minutes=2),
        )
        await record_check(
            s, service="api", status="operational", latency_ms=35, detail=None, now=yesterday + timedelta(minutes=3)
        )
        for service in ("web", "api", "runtime", "worker", "scheduler", "voice", "mcp"):
            await record_check(s, service=service, status="operational", latency_ms=30, detail=None, now=now)
        # Voice is degraded right now.
        await record_check(s, service="voice", status="degraded", latency_ms=2500, detail="slow", now=now)

    res = await client.get("/api/v1/status/public")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "degraded"
    services = {s["key"]: s for s in body["services"]}
    assert services["voice"]["status"] == "degraded"
    assert services["web"]["status"] == "operational"
    api = services["api"]
    assert api["days"][-1]["status"] == "operational"
    assert api["days"][-2]["status"] == "down"
    assert api["days"][-2]["uptime"] == 50.0
    assert api["days"][0]["status"] == "no_data"
    assert api["uptime_90d"] == pytest.approx(60.0)

    incidents = body["incidents"]
    assert incidents[0]["service"] == "voice" and incidents[0]["resolved_at"] is None
    api_incident = next(i for i in incidents if i["service"] == "api")
    assert api_incident["status"] == "down"
    assert api_incident["resolved_at"] is not None
    # Internal details never leave the API.
    assert "api.internal" not in res.text
    assert "detail" not in api


async def test_stale_checks_are_reported_as_unknown() -> None:
    now = datetime.now(UTC)
    async with system_session() as s:
        for service in ("web", "api", "runtime", "worker", "scheduler", "voice", "mcp"):
            await record_check(
                s, service=service, status="operational", latency_ms=10, detail=None, now=now - timedelta(minutes=30)
            )
        summary = await public_summary(s, now=now)
    assert summary["status"] == "unknown"
    assert all(svc["status"] == "unknown" for svc in summary["services"])
    # The history still counts.
    assert any(d["status"] == "operational" for d in summary["services"][0]["days"])


async def test_history_keeps_ninety_days() -> None:
    start = datetime(2026, 1, 1, 12, tzinfo=UTC)
    async with system_session() as s:
        for offset in range(100):
            await record_check(
                s, service="api", status="operational", latency_ms=5, detail=None, now=start + timedelta(days=offset)
            )
        from messer_common.db.models import ServiceHealth

        row = await s.get(ServiceHealth, "api")
        assert row is not None
        assert len(row.history) == HISTORY_DAYS
        assert row.history[0]["date"] == (start + timedelta(days=10)).date().isoformat()
        assert row.history[-1]["date"] == (start + timedelta(days=99)).date().isoformat()


# ---------------------------------------------------------------- credit pricing


async def test_credit_pricing_is_public_and_derived_from_settings(client: httpx.AsyncClient) -> None:
    res = await client.get("/api/v1/site/credits")
    assert res.status_code == 200
    body = res.json()
    settings = get_settings()
    assert float(body["credit_usd"]) == pytest.approx(settings.messer_credit_usd)
    assert float(body["margin_pct"]) == pytest.approx(settings.messer_credit_margin * 100)
    tiers = {m["tier"]: m for m in body["models"]}
    assert set(tiers) == {"fast", "standard", "powerful"}
    standard = tiers["standard"]
    expected = float(standard["input_usd_per_mtok"]) * (1 + settings.messer_credit_margin) / settings.messer_credit_usd
    assert float(standard["input_credits_per_mtok"]) == pytest.approx(expected, rel=1e-6)
    assert "E" not in standard["output_credits_per_mtok"]
