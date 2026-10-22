"""The gateway's Guard extension point: route the model, short-circuit, validate after, re-stream as SSE."""

from __future__ import annotations

import sys
import types
import uuid
from typing import Any

import pytest

from messer_runtime.guard_bridge import BeforeOutcome
from messer_runtime.testing import Harness

BODY: dict[str, Any] = {
    "model": "claude-sonnet-5-5",
    "max_tokens": 128,
    "stream": True,
    "messages": [{"role": "user", "content": "Hola"}],
}


class _Session:
    def __init__(self, short_circuit: bool) -> None:
        self.short_circuit = short_circuit
        self.seen: list[dict[str, Any]] = []

    async def before(self, body: dict[str, Any]) -> BeforeOutcome:
        if self.short_circuit:
            return BeforeOutcome(
                body=body,
                message={
                    "id": "msg_guard",
                    "type": "message",
                    "role": "assistant",
                    "model": body["model"],
                    "content": [{"type": "text", "text": "Respuesta determinista"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            )
        return BeforeOutcome(body=body, model="anthropic/claude-haiku-5-5")

    async def after(self, body: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(message)
        message["content"].append({"type": "text", "text": " [validado por Guard]"})
        return message


@pytest.fixture
def fake_guard(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    holder: dict[str, _Session] = {}
    module = types.ModuleType("messer_runtime.guard")

    async def session_for(ctx: Any, body: dict[str, Any]) -> _Session | None:
        return holder.get("session")

    module.session_for = session_for  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "messer_runtime.guard", module)
    return holder


async def test_routing_and_validation_are_restreamed(runtime: Harness, make_org, fake_guard) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.persistence import gateway_totals

    org, _ = await make_org()
    session = _Session(short_circuit=False)
    fake_guard["session"] = session
    run_id = uuid.uuid4().hex
    async with runtime.client.stream(
        "POST",
        f"/internal/v1/orgs/{org.id}/proxies/anthropic/v1/messages",
        json=BODY,
        headers={"x-messer-run-id": run_id},
    ) as res:
        assert res.status_code == 200
        raw = (await res.aread()).decode()
    assert "event: message_start" in raw and "[validado por Guard]" in raw and "event: message_stop" in raw
    assert session.seen, "after() must see the buffered model message"
    _, _, calls, _ = await gateway_totals(run_id)
    assert calls[0]["model"] == "anthropic/claude-haiku-5-5"


async def test_deterministic_answer_skips_the_model(runtime: Harness, make_org, fake_guard) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.persistence import gateway_totals

    org, _ = await make_org()
    fake_guard["session"] = _Session(short_circuit=True)
    run_id = uuid.uuid4().hex
    res = await runtime.client.post(
        f"/internal/v1/orgs/{org.id}/proxies/anthropic/v1/messages",
        json={**BODY, "stream": False},
        headers={"x-messer-run-id": run_id},
    )
    assert res.status_code == 200 and res.json()["content"][0]["text"] == "Respuesta determinista"
    _, _, calls, _ = await gateway_totals(run_id)
    assert calls == []
