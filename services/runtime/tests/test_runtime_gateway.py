"""Model gateway: demo fallback, provider routing (EU strict → Bedrock only), failover, cost and spend checks."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from messer_common import credits
from messer_common.db import system_session
from messer_common.db.models import ModelPrice, Org
from messer_common.models_config import bedrock_model_id
from messer_common.settings import get_settings
from messer_runtime.testing import Harness, anthropic_reply

BODY: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 256,
    "messages": [{"role": "user", "content": "Hola, ¿qué tal?"}],
}


def _url(org_id: uuid.UUID) -> str:
    return f"/internal/v1/orgs/{org_id}/proxies/anthropic/v1/messages"


class _FakeMessage:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        return self._payload


class FakeBedrock:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.messages = self

    async def create(self, **kwargs: Any) -> _FakeMessage:
        self.calls.append(kwargs)
        return _FakeMessage(
            {
                "id": "msg_bedrock",
                "type": "message",
                "role": "assistant",
                "model": kwargs["model"],
                "content": [{"type": "text", "text": "Hola desde Bedrock"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 20, "output_tokens": 10},
            }
        )


@pytest.fixture
def provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(settings, "aws_access_key_id", "AKIATEST")
    monkeypatch.setattr(settings, "aws_secret_access_key", "secret")


async def test_demo_model_without_keys(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    run_id = uuid.uuid4().hex
    res = await runtime.client.post(_url(org.id), json=BODY, headers={"x-messer-run-id": run_id})
    assert res.status_code == 200, res.text
    message = res.json()
    assert message["type"] == "message" and message["content"][0]["type"] == "text"
    assert message["content"][0]["text"]

    from messer_runtime.persistence import gateway_totals

    cost, providers, calls, _ = await gateway_totals(run_id)
    assert providers == {"demo"} and cost == 0 and len(calls) == 1

    async with runtime.client.stream("POST", _url(org.id), json={**BODY, "stream": True}) as streamed:
        assert streamed.status_code == 200
        raw = (await streamed.aread()).decode()
    assert "event: message_start" in raw and "event: message_stop" in raw


async def test_eu_strict_uses_bedrock_only(runtime: Harness, make_org, provider_keys: None) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    org, _ = await make_org()
    async with system_session() as s:
        row = await s.get(Org, org.id)
        assert row is not None
        row.data_residency = "eu_strict"

    def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("EU strict organizations must never reach the Anthropic API")

    gateway.anthropic_transport = httpx.MockTransport(forbidden)
    fake = FakeBedrock()
    gateway.bedrock_client_factory = lambda: fake
    run_id = uuid.uuid4().hex
    res = await runtime.client.post(_url(org.id), json=BODY, headers={"x-messer-run-id": run_id})
    assert res.status_code == 200, res.text
    assert res.json()["content"][0]["text"] == "Hola desde Bedrock"
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == bedrock_model_id("anthropic/claude-sonnet-5-5")

    from messer_runtime.persistence import gateway_totals

    cost, providers, _, _ = await gateway_totals(run_id)
    assert providers == {"bedrock"} and cost > 0


async def test_failover_from_anthropic_to_bedrock(runtime: Harness, make_org, provider_keys: None) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime import gateway

    org, _ = await make_org()
    attempts: list[int] = []

    def overloaded(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})

    gateway.anthropic_transport = httpx.MockTransport(overloaded)
    fake = FakeBedrock()
    gateway.bedrock_client_factory = lambda: fake
    res = await runtime.client.post(_url(org.id), json=BODY)
    assert res.status_code == 200, res.text
    assert attempts and len(fake.calls) == 1


async def test_anthropic_cost_is_recorded(runtime: Harness, make_org, provider_keys: None) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime import gateway
    from messer_runtime.persistence import gateway_totals

    org, _ = await make_org()
    gateway.anthropic_transport = httpx.MockTransport(
        anthropic_reply("Respuesta real", {"input_tokens": 1_000_000, "output_tokens": 100_000})
    )
    run_id = uuid.uuid4().hex
    res = await runtime.client.post(_url(org.id), json={**BODY, "stream": True}, headers={"x-messer-run-id": run_id})
    assert res.status_code == 200
    assert "Respuesta real" in res.text
    cost, providers, calls, _ = await gateway_totals(run_id)
    assert providers == {"anthropic"}
    async with system_session() as s:
        price = await s.get(ModelPrice, "anthropic/claude-sonnet-5-5")
    assert price is not None
    assert cost == price.input_per_mtok_usd + price.output_per_mtok_usd / 10, (cost, calls)
    assert json.loads(json.dumps(calls[0]))["usage"]["output_tokens"] == 100_000


async def test_refuses_when_credits_are_exhausted(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    async with system_session() as s:
        current = await credits.balance(s, org.id)
        await credits.add_entry(s, org_id=org.id, kind="adjustment", amount=-current, note="test: agotar créditos")
    run_id = uuid.uuid4().hex
    res = await runtime.client.post(_url(org.id), json=BODY, headers={"x-messer-run-id": run_id})
    assert res.status_code == 402
    assert res.json()["error"]["type"] == "credits_exhausted"


async def test_sandbox_token_is_scoped(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.tokens import issue_sandbox_token

    org, _ = await make_org()
    other, _ = await make_org(name="Otra")
    token = issue_sandbox_token(org_id=org.id, project_id=uuid.uuid4(), commit="a" * 40, environment="development")
    async with httpx.AsyncClient(base_url=runtime.base_url) as anon:
        ok = await anon.post(_url(org.id), json=BODY, headers={"x-api-key": f"Bearer {token}"})
        assert ok.status_code == 200
        denied = await anon.post(_url(other.id), json=BODY, headers={"x-api-key": f"Bearer {token}"})
        assert denied.status_code == 403
        anonymous = await anon.post(_url(org.id), json=BODY)
        assert anonymous.status_code == 401
