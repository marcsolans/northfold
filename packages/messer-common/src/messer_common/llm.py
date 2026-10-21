"""Model calls for platform features (Composer, Guard, eval judges, playbooks) — always through the runtime gateway.

The gateway enforces the organization's residency, model policy, credits and budgets, falls back between
providers, and serves the deterministic demo model when no provider key is configured. The cost of each call
is charged to the organization's credits (idempotent per call id).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import httpx

from . import credits
from .db import system_session
from .events import get_redis
from .logging import get_logger
from .models_config import resolve_model
from .pricing import usd_to_credits
from .settings import get_settings

log = get_logger("messer.llm")

# Test hook: route gateway calls through a custom transport.
transport: httpx.AsyncBaseTransport | None = None

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LlmError(Exception):
    def __init__(self, message: str, *, error_type: str = "api_error", status: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.status = status


class LlmRefused(LlmError):
    """Refused by policy: credits exhausted, budget reached, model not allowed, organization blocked."""


class LlmUnavailable(LlmError):
    """No provider could serve the call."""


@dataclass(slots=True)
class Completion:
    text: str
    content: list[dict[str, Any]]
    model: str
    usage: dict[str, Any]
    stop_reason: str | None
    call_id: str
    cost_usd: Decimal = Decimal("0")
    credits: Decimal = Decimal("0")
    providers: list[str] = field(default_factory=list)

    @property
    def demo(self) -> bool:
        return self.providers == ["demo"]

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]

    def json(self) -> Any:
        """Parse the reply as JSON (tolerates code fences and leading prose before the first brace)."""
        raw = _FENCE.sub("", self.text.strip())
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
            if start < 0:
                raise
            return json.loads(raw[start:])


async def complete(
    *,
    org_id: uuid.UUID,
    messages: list[dict[str, Any]] | str,
    system: str | None = None,
    model: str | None = None,
    tier: str = "standard",
    project_id: uuid.UUID | None = None,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: dict[str, Any] | None = None,
    purpose: str = "platform",
    charge: bool = True,
    timeout_s: float = 300,
) -> Completion:
    full_model = resolve_model(model or tier)
    body: dict[str, Any] = {
        "model": full_model.split("/", 1)[1] if full_model.startswith("anthropic/") else full_model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": messages}] if isinstance(messages, str) else messages,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    call_id = uuid.uuid4().hex
    s = get_settings()
    headers = {
        "Authorization": f"Bearer {s.service_token}",
        "x-messer-run-id": call_id,
        "anthropic-version": "2023-06-01",
    }
    if project_id is not None:
        headers["x-messer-project-id"] = str(project_id)
    url = f"{s.messer_runtime_url.rstrip('/')}/internal/v1/orgs/{org_id}/proxies/anthropic/v1/messages"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=10), transport=transport) as c:
            res = await c.post(url, json=body, headers=headers)
    except httpx.HTTPError as exc:
        raise LlmUnavailable(f"El gateway de modelos no responde: {exc}", error_type="unavailable", status=503) from exc
    payload: dict[str, Any]
    try:
        payload = res.json()
    except ValueError as exc:
        raise LlmUnavailable(f"Respuesta no válida del gateway ({res.status_code})", status=502) from exc
    if res.status_code != 200:
        err = payload.get("error") or {}
        message = str(err.get("message") or payload)
        kind = str(err.get("type") or "api_error")
        if res.status_code in (402, 403):
            raise LlmRefused(message, error_type=kind, status=res.status_code)
        raise LlmUnavailable(message, error_type=kind, status=res.status_code)

    content = [b for b in payload.get("content") or [] if isinstance(b, dict)]
    completion = Completion(
        text="".join(str(b.get("text", "")) for b in content if b.get("type") == "text"),
        content=content,
        model=full_model,
        usage=payload.get("usage") or {},
        stop_reason=payload.get("stop_reason"),
        call_id=call_id,
    )
    r = get_redis()
    completion.cost_usd = Decimal(str(await r.get(f"run:{call_id}:cost_usd") or "0"))
    completion.providers = sorted(await r.smembers(f"run:{call_id}:providers") or [])  # type: ignore[misc]
    if charge and completion.cost_usd > 0:
        completion.credits = usd_to_credits(completion.cost_usd)
        async with system_session() as session:
            await credits.charge_usage(
                session,
                org_id=org_id,
                run_id=uuid.UUID(hex=call_id),
                project_id=project_id,
                cost_usd=completion.cost_usd,
                credits=completion.credits,
                note=purpose,
            )
            await credits.maybe_auto_topup(session, org_id)
    log.info(
        "llm.complete",
        purpose=purpose,
        model=full_model,
        providers=completion.providers,
        cost_usd=str(completion.cost_usd),
    )
    return completion
