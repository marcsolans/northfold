"""Model gateway — every model call in Messer passes through here.

Anthropic Messages API compatible (`POST /internal/v1/orgs/{org}/proxies/anthropic/v1/messages`, JSON or
SSE). Responsibilities:

* Authentication: sandbox token (agents running in the runtime) or service token (control-plane features).
* Credits and budgets checked **before every call**; a refusal flags the run as ``budget_exceeded``.
* Model policy per organization (allow/deny patterns).
* Routing: strict-EU organizations only ever reach Claude on AWS Bedrock in an EU region; others use the
  direct Anthropic API, falling back to Bedrock (and vice versa) on overload or provider errors.
* Without any provider key, the deterministic demo model answers (nothing leaves the platform).
* Cost accounting per call (model prices from ``model_prices``), accumulated per run in Redis.
"""

from __future__ import annotations

import fnmatch
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import select

from messer_common.db import system_session
from messer_common.db.models import ModelPolicy, ModelPrice, Org
from messer_common.events import get_redis
from messer_common.logging import get_logger
from messer_common.models_config import DEMO_MODEL, bedrock_model_id, bedrock_region, request_defaults
from messer_common.pricing import MTOK
from messer_common.settings import get_settings

from . import demo_model

log = get_logger("messer.runtime.gateway")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}
_CACHE_TTL_S = 15.0
_org_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_price_cache: tuple[float, dict[str, ModelPrice]] | None = None

# Test hooks: replace the transports to simulate providers.
anthropic_transport: httpx.AsyncBaseTransport | None = None
bedrock_client_factory: Any = None


class GatewayRefusal(Exception):
    def __init__(self, status: int, error_type: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.message = message


@dataclass(slots=True)
class CallContext:
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    run_id: str | None
    environment: str


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse({"type": "error", "error": {"type": error_type, "message": message}}, status_code=status)


async def _org_info(org_id: uuid.UUID) -> dict[str, Any]:
    key = str(org_id)
    cached = _org_cache.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    async with system_session() as s:
        org = await s.get(Org, org_id)
        if org is None:
            raise GatewayRefusal(404, "not_found_error", "organization not found")
        policy = (await s.execute(select(ModelPolicy).where(ModelPolicy.org_id == org_id))).scalar_one_or_none()
        info = {
            "residency": org.data_residency,
            "region": org.region,
            "blocked": org.status == "blocked",
            "policy": policy.rules if policy else {},
        }
    _org_cache[key] = (time.monotonic(), info)
    return info


async def _prices() -> dict[str, ModelPrice]:
    global _price_cache
    if _price_cache and time.monotonic() - _price_cache[0] < 60:
        return _price_cache[1]
    async with system_session() as s:
        rows = (await s.execute(select(ModelPrice))).scalars().all()
    prices = {r.model: r for r in rows}
    _price_cache = (time.monotonic(), prices)
    return prices


def invalidate_caches() -> None:
    global _price_cache
    _org_cache.clear()
    _price_cache = None


def _policy_allows(rules: dict[str, Any], model: str) -> bool:
    deny = [str(p) for p in rules.get("deny", []) or []]
    allow = [str(p) for p in rules.get("allow", []) or []]
    if any(fnmatch.fnmatch(model, p) for p in deny):
        return False
    return not allow or any(fnmatch.fnmatch(model, p) for p in allow)


_SPEND_MESSAGES = {
    "credits_exhausted": "No quedan créditos de IA. Compra un paquete o mejora el plan.",
    "budget_exceeded": "Se ha alcanzado el presupuesto configurado para este proyecto u organización.",
    "runs_limit": "Se ha alcanzado el límite de ejecuciones del plan este mes.",
    "read_only": "La organización está en modo solo lectura: actualiza el método de pago.",
    "org_blocked": "La organización está bloqueada.",
}


async def check_spend(ctx: CallContext) -> None:
    """Refuse when credits are exhausted, a plan limit is hit or a hard-stop budget is reached (cached briefly)."""
    from messer_common import budgets

    r = get_redis()
    cache_key = f"gw:spend_ok:{ctx.org_id}:{ctx.project_id}"
    if await r.get(cache_key):
        return
    async with system_session() as s:
        status = await budgets.check_budget(s, ctx.org_id, ctx.project_id)
    if not status.allowed:
        reason = status.reason or "budget_exceeded"
        raise GatewayRefusal(402, reason, status.message or _SPEND_MESSAGES.get(reason, "Gasto no permitido."))
    await r.set(cache_key, "1", ex=5)


async def _record(ctx: CallContext, *, model: str, provider: str, usage: dict[str, Any]) -> Decimal:
    prices = await _prices()
    priced_model = DEMO_MODEL if provider == "demo" else model
    price = prices.get(priced_model)
    cost = Decimal("0")
    if price is not None:
        cost = (
            Decimal(int(usage.get("input_tokens") or 0)) * price.input_per_mtok_usd
            + Decimal(int(usage.get("output_tokens") or 0)) * price.output_per_mtok_usd
            + Decimal(int(usage.get("cache_read_input_tokens") or 0)) * price.cache_read_per_mtok_usd
            + Decimal(int(usage.get("cache_creation_input_tokens") or 0)) * price.cache_write_per_mtok_usd
        ) / MTOK
    if ctx.run_id:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incrbyfloat(f"run:{ctx.run_id}:cost_usd", float(cost))
        pipe.sadd(f"run:{ctx.run_id}:providers", provider)
        pipe.rpush(
            f"run:{ctx.run_id}:calls",
            json.dumps(
                {
                    "model": model,
                    "provider": provider,
                    "usage": usage,
                    "cost_usd": str(cost),
                    "t": int(time.time() * 1000),
                }
            ),
        )
        for k in (f"run:{ctx.run_id}:cost_usd", f"run:{ctx.run_id}:providers", f"run:{ctx.run_id}:calls"):
            pipe.expire(k, 86400)
        await pipe.execute()
    return cost


def _route(info: dict[str, Any]) -> list[str]:
    s = get_settings()
    if info["residency"] == "eu_strict":
        return ["bedrock"] if s.has_bedrock else ["demo"]
    order: list[str] = []
    if s.has_anthropic:
        order.append("anthropic")
    if s.has_bedrock:
        order.append("bedrock")
    return order or ["demo"]


def _prepare_body(body: dict[str, Any]) -> tuple[dict[str, Any], str]:
    model_id = str(body.get("model", ""))
    full_model = model_id if "/" in model_id else f"anthropic/{model_id}"
    prepared = dict(body)
    defaults = request_defaults(full_model)
    if defaults.get("effort") and "output_config" not in prepared:
        prepared["output_config"] = {"effort": defaults["effort"]}
    return prepared, full_model


def _merge_usage(usage: dict[str, Any], update: dict[str, Any] | None) -> None:
    for k, v in (update or {}).items():
        if isinstance(v, int):
            if k == "output_tokens":
                usage[k] = v  # message_delta carries the cumulative output count
            else:
                usage[k] = max(int(usage.get(k) or 0), v)


async def _anthropic(body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
    s = get_settings()
    client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10), transport=anthropic_transport)
    req_headers = {
        "x-api-key": s.anthropic_api_key,
        "anthropic-version": headers.get("anthropic-version", "2023-06-01"),
        "content-type": "application/json",
    }
    if headers.get("anthropic-beta"):
        req_headers["anthropic-beta"] = headers["anthropic-beta"]
    request = client.build_request("POST", ANTHROPIC_URL, json=body, headers=req_headers)
    response = await client.send(request, stream=True)
    response.extensions["messer_client"] = client
    return response


def _bedrock_client() -> Any:
    if bedrock_client_factory is not None:
        return bedrock_client_factory()
    from anthropic import AsyncAnthropicBedrock

    s = get_settings()
    return AsyncAnthropicBedrock(
        aws_region=s.aws_region or bedrock_region(),
        aws_access_key=s.aws_access_key_id,
        aws_secret_key=s.aws_secret_access_key,
    )


def _bedrock_body(body: dict[str, Any], full_model: str) -> dict[str, Any]:
    target = bedrock_model_id(full_model)
    if target is None:
        raise GatewayRefusal(400, "invalid_request_error", f"El modelo {full_model} no está disponible en Bedrock UE")
    out = {k: v for k, v in body.items() if k not in ("stream", "output_config")}
    out["model"] = target
    return out


async def handle(request: Request, ctx: CallContext) -> Response:
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _error(400, "invalid_request_error", "invalid JSON body")
    try:
        info = await _org_info(ctx.org_id)
        if info["blocked"]:
            raise GatewayRefusal(403, "permission_error", "Organización bloqueada")
        prepared, full_model = _prepare_body(body)
        if not _policy_allows(info.get("policy") or {}, full_model):
            raise GatewayRefusal(
                403, "permission_error", f"La política de modelos de la organización no permite {full_model}"
            )
        await check_spend(ctx)
    except GatewayRefusal as exc:
        if exc.error_type in ("budget_exceeded", "credits_exhausted") and ctx.run_id:
            await get_redis().set(f"run:{ctx.run_id}:budget_exceeded", exc.message, ex=86400)
        return _error(exc.status, exc.error_type, exc.message)

    streaming = bool(prepared.get("stream"))
    headers = {k.lower(): v for k, v in request.headers.items()}
    last_error: str = "no provider available"
    for provider in _route(info):
        try:
            if provider == "demo":
                return await _serve_demo(prepared, full_model, ctx, streaming)
            if provider == "anthropic":
                response = await _anthropic(prepared, headers)
                if response.status_code in RETRYABLE and len(_route(info)) > 1:
                    last_error = f"anthropic {response.status_code}"
                    await _close(response)
                    continue
                return await _relay_anthropic(response, full_model, ctx, streaming)
            return await _serve_bedrock(prepared, full_model, ctx, streaming)
        except GatewayRefusal as exc:
            return _error(exc.status, exc.error_type, exc.message)
        except (httpx.HTTPError, ConnectionError) as exc:
            last_error = f"{provider}: {type(exc).__name__}"
            log.warning("gateway.provider_failed", provider=provider, error=str(exc))
            continue
        except Exception as exc:
            last_error = f"{provider}: {exc}"
            log.warning("gateway.provider_error", provider=provider, error=str(exc))
            continue
    return _error(529, "overloaded_error", f"Ningún proveedor de modelos disponible ({last_error})")


async def _close(response: httpx.Response) -> None:
    await response.aclose()
    client = response.extensions.get("messer_client")
    if client is not None:
        await client.aclose()


async def _relay_anthropic(response: httpx.Response, model: str, ctx: CallContext, streaming: bool) -> Response:
    if not streaming or response.status_code != 200:
        data = await response.aread()
        await _close(response)
        if response.status_code == 200:
            payload = json.loads(data)
            await _record(ctx, model=model, provider="anthropic", usage=payload.get("usage", {}))
        return Response(content=data, status_code=response.status_code, media_type="application/json")

    async def relay() -> AsyncIterator[bytes]:
        usage: dict[str, Any] = {}
        buffer = b""
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.startswith(b"data:"):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "message_start":
                        _merge_usage(usage, event.get("message", {}).get("usage"))
                    elif event.get("type") == "message_delta":
                        _merge_usage(usage, event.get("usage"))
        finally:
            await _close(response)
            await _record(ctx, model=model, provider="anthropic", usage=usage)

    return StreamingResponse(relay(), media_type="text/event-stream")


async def _serve_bedrock(body: dict[str, Any], model: str, ctx: CallContext, streaming: bool) -> Response:
    client = _bedrock_client()
    request_body = _bedrock_body(body, model)
    if not streaming:
        message = await client.messages.create(**request_body)
        payload = message.model_dump(mode="json")
        payload["model"] = body.get("model", payload.get("model"))
        await _record(ctx, model=model, provider="bedrock", usage=payload.get("usage", {}))
        return JSONResponse(payload)

    stream = await client.messages.create(**request_body, stream=True)

    async def relay() -> AsyncIterator[bytes]:
        usage: dict[str, Any] = {}
        try:
            async for event in stream:
                data = event.model_dump(mode="json")
                if data.get("type") == "message_start":
                    data.setdefault("message", {})["model"] = body.get("model")
                    _merge_usage(usage, data["message"].get("usage"))
                elif data.get("type") == "message_delta":
                    _merge_usage(usage, data.get("usage"))
                yield f"event: {data.get('type')}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
        finally:
            await _record(ctx, model=model, provider="bedrock", usage=usage)

    return StreamingResponse(relay(), media_type="text/event-stream")


async def _serve_demo(body: dict[str, Any], model: str, ctx: CallContext, streaming: bool) -> Response:
    if not streaming:
        message = demo_model.respond(body)
        await _record(ctx, model=model, provider="demo", usage=message["usage"])
        return JSONResponse(message)

    async def relay() -> AsyncIterator[bytes]:
        usage: dict[str, Any] = {}
        async for chunk in demo_model.stream(body):
            yield chunk
            text = chunk.decode()
            if '"message_start"' in text or '"message_delta"' in text:
                payload = json.loads(text.split("data: ", 1)[1])
                _merge_usage(usage, payload.get("usage") or payload.get("message", {}).get("usage"))
        await _record(ctx, model=model, provider="demo", usage=usage)

    return StreamingResponse(relay(), media_type="text/event-stream")


def context_from_headers(
    request: Request, org_id: uuid.UUID, project_id: uuid.UUID | None, environment: str
) -> CallContext:
    run_id = request.headers.get("x-messer-run-id")
    return CallContext(org_id=org_id, project_id=project_id, run_id=run_id, environment=environment)


def ensure(condition: bool, status: int, detail: str) -> None:
    if not condition:
        raise HTTPException(status_code=status, detail=detail)
