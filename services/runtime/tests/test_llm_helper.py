"""messer_common.llm.complete — platform features call models through the gateway and pay with credits."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from messer_common import credits, llm
from messer_common.db import system_session
from messer_common.db.models import CreditLedger
from messer_common.settings import get_settings
from messer_runtime.testing import Harness, anthropic_reply


async def test_demo_completion_is_free(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    result = await llm.complete(
        org_id=org.id, messages="Resume en una frase: la factura 12 está pagada.", tier="fast", purpose="test"
    )
    assert result.text and result.demo and result.cost_usd == 0
    async with system_session() as s:
        assert (await s.execute(select(CreditLedger).where(CreditLedger.kind == "usage"))).first() is None


async def test_real_completion_charges_credits(
    runtime: Harness,
    make_org,  # type: ignore[no-untyped-def]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from messer_runtime import gateway

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    gateway.anthropic_transport = httpx.MockTransport(
        anthropic_reply('```json\n{"ok": true}\n```', {"input_tokens": 50_000, "output_tokens": 5_000})
    )
    org, _ = await make_org()
    async with system_session() as s:
        before = await credits.balance(s, org.id)
    result = await llm.complete(org_id=org.id, messages="Devuelve JSON", purpose="composer")
    assert result.json() == {"ok": True}
    assert result.providers == ["anthropic"] and result.cost_usd > 0 and result.credits > 0
    async with system_session() as s:
        after = await credits.balance(s, org.id)
        entry = (await s.execute(select(CreditLedger).where(CreditLedger.kind == "usage"))).scalar_one()
    assert before - after == result.credits and entry.note == "composer"
    assert entry.cost_usd == result.cost_usd and isinstance(entry.amount, Decimal)


async def test_refusal_is_typed(runtime: Harness, make_org) -> None:  # type: ignore[no-untyped-def]
    org, _ = await make_org()
    async with system_session() as s:
        await credits.add_entry(
            s, org_id=org.id, kind="adjustment", amount=-(await credits.balance(s, org.id)), note="test"
        )
    with pytest.raises(llm.LlmRefused) as info:
        await llm.complete(org_id=org.id, messages="Hola")
    assert info.value.error_type == "credits_exhausted"
