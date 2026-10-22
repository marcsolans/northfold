"""Channels (control plane): connect providers to an agent, test, simulate, and receive provider webhooks.

Data-plane pieces (adapters, processing, delivery) live in ``messer_common.channels``; this module validates
requests, stores encrypted credentials and turns webhook calls into recorded inbound messages.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.channels import (
    PROVIDERS,
    ChannelAdapter,
    ChannelError,
    InboundMessage,
    InboundRequest,
    InvalidConfig,
    InvalidSignature,
    WebhookReply,
    get_adapter,
)
from messer_common.channels import email as email_channel
from messer_common.channels.context import (
    channel_context,
    credential_source,
    inbound_address,
    stored_credentials,
    webhook_url,
)
from messer_common.channels.processing import record_inbound
from messer_common.db import Principal, system_session
from messer_common.db.models import Channel, Conversation, Environment, Project, Workforce
from messer_common.db.models.channels import ChannelMessage
from messer_common.logging import get_logger
from messer_common.security import encrypt, encrypt_json, random_token
from messer_common.settings import get_settings

from ..deps import ensure_project_access
from ..errors import ApiError, Conflict, NotFound, RateLimited, Unauthorized
from ..ratelimit import hit
from . import limits
from . import projects as projects_svc

log = get_logger("messer.api.channels")

Provider = Literal["whatsapp", "slack", "teams", "telegram", "email"]
EnvironmentName = Literal["production", "development"]
MAX_WEBHOOK_BODY = 1_000_000
WEBHOOK_RATE = (600, 60)  # requests per channel per minute
DEMO_TOKEN_HEADER = "x-messer-channel-token"  # noqa: S105 (header name)


# ============================================================================================== schemas


class ChannelIn(BaseModel):
    provider: Provider
    workforce: str = Field(min_length=1, max_length=80, description="Agent that answers on the channel")
    name: str = Field(default="", max_length=200)
    environment: EnvironmentName = "production"
    demo: bool | None = Field(
        default=None, description="true: demo mode; false: live (credentials required); omitted: demo if missing"
    )
    credentials: dict[str, str] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ChannelPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    workforce: str | None = Field(default=None, min_length=1, max_length=80)
    environment: EnvironmentName | None = None
    enabled: bool | None = None
    demo: bool | None = None
    credentials: dict[str, str] | None = Field(default=None, description="Keys to set; an empty value removes it")
    config: dict[str, Any] | None = Field(default=None, description="Keys to set; null removes it")


class ChannelStats(BaseModel):
    conversations: int = 0
    messages_24h: int = 0
    failed_24h: int = 0
    last_message_at: datetime | None = None


class ChannelOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    name: str
    workforce_id: uuid.UUID
    workforce_name: str | None
    status: str
    demo: bool
    environment: str
    development_fallback: bool
    error: str | None
    config: dict[str, Any]
    credentials_set: list[str]
    credential_source: str
    missing_credentials: list[str]
    webhook_url: str
    inbound_address: str | None
    supported: bool
    stats: ChannelStats
    created_at: datetime
    updated_at: datetime


class ChannelCreated(ChannelOut):
    webhook_secret: str = Field(description="Shown once: WhatsApp verify token, email webhook token, demo token")


class SecretOut(BaseModel):
    webhook_secret: str
    webhook_url: str


class CredentialFieldOut(BaseModel):
    key: str
    required: bool
    secret: bool
    platform_available: bool


class ProviderOut(BaseModel):
    provider: str
    label: str
    max_text: int
    credential_fields: list[CredentialFieldOut]
    config_keys: list[str]
    required_config: list[CredentialFieldOut]
    platform_ready: bool


class TestOut(BaseModel):
    ok: bool
    status: str
    demo: bool
    details: dict[str, Any]
    error: str | None
    checked_at: datetime


class SimulateIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    sender: str = Field(default="", max_length=120, alias="from", description="Simulated user id")
    name: str | None = Field(default=None, max_length=120)

    model_config = {"populate_by_name": True}


class SimulateOut(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    sender: str
    duplicate: bool


class ChannelMessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID | None
    direction: str
    kind: str
    status: str
    sender_id: str | None
    sender_name: str | None
    text: str
    error: str | None
    error_code: str | None
    run_id: uuid.UUID | None
    simulated: bool
    parts: int | None
    created_at: datetime
    processed_at: datetime | None


class ChannelMessagePage(BaseModel):
    items: list[ChannelMessageOut]
    next_cursor: str | None


# ============================================================================================ describing


def _adapter(provider: str) -> ChannelAdapter | None:
    try:
        return get_adapter(provider)
    except InvalidConfig:
        return None


async def _production_deployed(session: AsyncSession, project_ids: set[uuid.UUID]) -> dict[uuid.UUID, bool]:
    if not project_ids:
        return {}
    rows = (
        await session.execute(
            select(Environment.project_id, Environment.deployed_version_id).where(
                Environment.project_id.in_(project_ids), Environment.name == "production"
            )
        )
    ).all()
    deployed = {pid: vid is not None for pid, vid in rows}
    return {pid: deployed.get(pid, False) for pid in project_ids}


async def _stats(session: AsyncSession, channel_ids: list[uuid.UUID]) -> dict[uuid.UUID, ChannelStats]:
    out = {cid: ChannelStats() for cid in channel_ids}
    if not channel_ids:
        return out
    since = datetime.now(UTC) - timedelta(hours=24)
    conv_rows = (
        await session.execute(
            select(Conversation.channel_id, func.count())
            .where(Conversation.channel_id.in_(channel_ids))
            .group_by(Conversation.channel_id)
        )
    ).all()
    for cid, count in conv_rows:
        if cid is not None and cid in out:
            out[cid].conversations = int(count)
    msg_rows = (
        await session.execute(
            select(
                ChannelMessage.channel_id,
                func.count().filter(ChannelMessage.created_at >= since),
                func.count().filter(ChannelMessage.created_at >= since, ChannelMessage.status == "failed"),
                func.max(ChannelMessage.created_at),
            )
            .where(ChannelMessage.channel_id.in_(channel_ids))
            .group_by(ChannelMessage.channel_id)
        )
    ).all()
    for cid, recent, failed, last in msg_rows:
        stats = out[cid]
        stats.messages_24h, stats.failed_24h, stats.last_message_at = int(recent), int(failed), last
    return out


async def describe_many(session: AsyncSession, channels: list[Channel]) -> list[ChannelOut]:
    member_ids = {c.workforce_id for c in channels}
    names = (
        dict((await session.execute(select(Workforce.id, Workforce.name).where(Workforce.id.in_(member_ids)))).all())
        if member_ids
        else {}
    )
    deployed = await _production_deployed(session, {c.project_id for c in channels})
    stats = await _stats(session, [c.id for c in channels])
    settings = get_settings()
    out: list[ChannelOut] = []
    for c in channels:
        adapter = _adapter(c.provider)
        stored = {k for k, v in stored_credentials(c).items() if v}
        missing: list[str] = []
        if adapter is not None:
            creds = {**adapter.platform_credentials(settings), **dict.fromkeys(stored, "set")}
            cfg = {**adapter.platform_defaults(settings), **(c.config or {})}
            missing = [*adapter.missing_credentials(creds), *adapter.missing_config(cfg)]
        out.append(
            ChannelOut(
                id=c.id,
                project_id=c.project_id,
                provider=c.provider,
                name=c.name,
                workforce_id=c.workforce_id,
                workforce_name=names.get(c.workforce_id),
                status=c.status,
                demo=c.demo,
                environment=c.environment,
                development_fallback=c.demo and c.environment == "production" and not deployed.get(c.project_id),
                error=c.error,
                config=dict(c.config or {}),
                credentials_set=sorted(stored),
                credential_source=credential_source(c),
                missing_credentials=missing,
                webhook_url=webhook_url(c),
                inbound_address=inbound_address(c),
                supported=adapter is not None,
                stats=stats[c.id],
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return out


async def describe(session: AsyncSession, channel: Channel) -> ChannelOut:
    return (await describe_many(session, [channel]))[0]


def providers() -> list[ProviderOut]:
    settings = get_settings()
    out: list[ProviderOut] = []
    for provider in PROVIDERS:
        adapter = get_adapter(provider)
        platform = adapter.platform_credentials(settings)
        defaults = adapter.platform_defaults(settings)
        fields = [
            CredentialFieldOut(key=f.key, required=f.required, secret=f.secret, platform_available=f.key in platform)
            for f in adapter.credential_fields
        ]
        required = [
            CredentialFieldOut(key=k, required=True, secret=False, platform_available=k in defaults)
            for k in adapter.required_config
        ]
        out.append(
            ProviderOut(
                provider=provider,
                label=adapter.label,
                max_text=adapter.max_text,
                credential_fields=fields,
                config_keys=list(adapter.config_keys),
                required_config=required,
                platform_ready=not adapter.missing_credentials(platform) and not adapter.missing_config(defaults),
            )
        )
    return out


# ============================================================================================ lifecycle


async def get_channel(session: AsyncSession, principal: Principal, channel_id: uuid.UUID) -> Channel:
    channel = await session.get(Channel, channel_id)
    if channel is None or channel.org_id != principal.org_id:
        raise NotFound("Canal no encontrado")
    ensure_project_access(principal, channel.project_id)
    return channel


async def list_channels(session: AsyncSession, project: Project) -> list[ChannelOut]:
    rows = (
        (
            await session.execute(
                select(Channel).where(Channel.project_id == project.id).order_by(Channel.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return await describe_many(session, list(rows))


async def _agent(session: AsyncSession, project: Project, name: str) -> Workforce:
    member = await projects_svc.get_member(session, project, name)
    if member.kind != "agent":
        raise ApiError("Solo los agentes pueden atender un canal", code="not_agent")
    return member


def _clean_credentials(adapter: ChannelAdapter, raw: dict[str, str]) -> dict[str, str]:
    known = {f.key for f in adapter.credential_fields}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise ApiError(
            f"Credenciales no reconocidas para {adapter.label}: {', '.join(unknown)}",
            code="unknown_credentials",
            status_code=422,
            details={"unknown": unknown, "accepted": sorted(known)},
        )
    for key, value in raw.items():
        if len(value) > 4096:
            raise ApiError(f"«{key}» es demasiado largo", code="invalid_credentials", status_code=422)
    return {k: v.strip() for k, v in raw.items()}


def _config(adapter: ChannelAdapter, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return adapter.normalize_config(config)
    except InvalidConfig as exc:
        raise ApiError(exc.message, code="invalid_config", status_code=422) from exc


def _missing(adapter: ChannelAdapter, credentials: dict[str, Any], config: dict[str, Any]) -> list[str]:
    settings = get_settings()
    creds = {**adapter.platform_credentials(settings), **{k: v for k, v in credentials.items() if v}}
    cfg = {**adapter.platform_defaults(settings), **config}
    return [*adapter.missing_credentials(creds), *adapter.missing_config(cfg)]


async def _go_live(channel: Channel) -> None:
    """Register the webhook / verify credentials with the provider; failures leave the channel in error."""
    adapter = get_adapter(channel.provider)
    try:
        result = await adapter.on_connect(channel_context(channel))
    except ChannelError as exc:
        channel.status = "error"
        channel.error = exc.message
        return
    channel.config = {**(channel.config or {}), **result.config_updates}
    channel.status = "active"
    channel.error = None


async def connect(session: AsyncSession, principal: Principal, project: Project, body: ChannelIn) -> ChannelCreated:
    await limits.require_feature(session, project.org_id, "channels")
    member = await _agent(session, project, body.workforce)
    adapter = get_adapter(body.provider)
    credentials = {k: v for k, v in _clean_credentials(adapter, body.credentials).items() if v}
    config = {**adapter.initial_config(), **_config(adapter, body.config)}
    missing = _missing(adapter, credentials, config)
    if body.demo is True:
        demo = True
    elif missing:
        if body.demo is False:
            raise ApiError(
                f"Faltan datos para conectar {adapter.label}: {', '.join(missing)}",
                code="missing_credentials",
                status_code=422,
                details={"missing": missing},
            )
        demo = True
    else:
        demo = False
    secret = random_token(32)
    channel = Channel(
        org_id=project.org_id,
        project_id=project.id,
        workforce_id=member.id,
        provider=body.provider,
        name=body.name.strip() or f"{adapter.label} · {member.name}",
        credentials=encrypt_json(credentials) if credentials else None,
        config=config,
        webhook_secret=encrypt(secret),
        status="demo" if demo else "active",
        demo=demo,
        environment=body.environment,
    )
    session.add(channel)
    await session.flush()
    if not demo:
        await _go_live(channel)
    await audit.record(
        session,
        action="channel.connected",
        principal=principal,
        entity_type="channel",
        entity_id=channel.id,
        diff={
            "provider": channel.provider,
            "workforce": member.name,
            "demo": demo,
            "environment": channel.environment,
            "credentials": sorted(credentials),
            "status": channel.status,
        },
    )
    await session.flush()
    await session.refresh(channel)
    out = await describe(session, channel)
    return ChannelCreated(**out.model_dump(), webhook_secret=secret)


async def update(session: AsyncSession, principal: Principal, channel: Channel, body: ChannelPatch) -> ChannelOut:
    adapter = _adapter(channel.provider)
    if adapter is None:
        raise ApiError("Este canal lo gestiona otra sección (voz)", code="unsupported_provider")
    changed: dict[str, Any] = {}
    reconnect = False
    if body.name is not None and body.name.strip() != channel.name:
        channel.name = body.name.strip() or channel.name
        changed["name"] = channel.name
    if body.workforce is not None:
        project = await projects_svc.get_project(session, channel.project_id)
        member = await _agent(session, project, body.workforce)
        if member.id != channel.workforce_id:
            channel.workforce_id = member.id
            changed["workforce"] = member.name
    if body.environment is not None and body.environment != channel.environment:
        channel.environment = body.environment
        changed["environment"] = body.environment
    if body.config is not None:
        current = dict(channel.config or {})
        for key, value in body.config.items():
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        normalized = _config(adapter, current)
        generated = {k: v for k, v in (channel.config or {}).items() if k == "address_token"}
        channel.config = {**normalized, **generated}
        changed["config"] = sorted(body.config)
    if body.credentials is not None:
        updates = _clean_credentials(adapter, body.credentials)
        stored = stored_credentials(channel)
        for key, value in updates.items():
            if value:
                stored[key] = value
            else:
                stored.pop(key, None)
        channel.credentials = encrypt_json(stored) if stored else None
        changed["credentials"] = sorted(updates)
        reconnect = True
    if body.demo is not None and body.demo != channel.demo:
        if not body.demo:
            missing = _missing(adapter, stored_credentials(channel), channel.config or {})
            if missing:
                raise ApiError(
                    f"Faltan datos para salir del modo demo: {', '.join(missing)}",
                    code="missing_credentials",
                    status_code=422,
                    details={"missing": missing},
                )
            reconnect = True
        channel.demo = body.demo
        changed["demo"] = body.demo
    if body.enabled is not None:
        enabled = channel.status != "disabled"
        if body.enabled != enabled:
            changed["enabled"] = body.enabled
            reconnect = reconnect or body.enabled
    disabled = channel.status == "disabled" if body.enabled is None else not body.enabled
    if disabled:
        channel.status = "disabled"
    elif channel.demo:
        channel.status, channel.error = "demo", None
    elif reconnect:
        await _go_live(channel)
    elif channel.status in ("disabled", "demo"):
        channel.status = "active"
    if changed:
        await audit.record(
            session,
            action="channel.updated",
            principal=principal,
            entity_type="channel",
            entity_id=channel.id,
            diff=changed,
        )
    await session.flush()
    await session.refresh(channel)
    return await describe(session, channel)


async def disconnect(session: AsyncSession, principal: Principal, channel: Channel) -> None:
    adapter = _adapter(channel.provider)
    if adapter is not None and not channel.demo:
        try:
            await adapter.on_disconnect(channel_context(channel))
        except ChannelError as exc:
            log.warning("channel.unregister_failed", channel_id=str(channel.id), error=exc.message)
    await audit.record(
        session,
        action="channel.disconnected",
        principal=principal,
        entity_type="channel",
        entity_id=channel.id,
        diff={"provider": channel.provider, "name": channel.name},
    )
    await session.delete(channel)


async def rotate_secret(session: AsyncSession, principal: Principal, channel: Channel) -> SecretOut:
    if _adapter(channel.provider) is None:
        raise ApiError("Este canal lo gestiona otra sección (voz)", code="unsupported_provider")
    secret = random_token(32)
    channel.webhook_secret = encrypt(secret)
    if channel.provider == "telegram" and not channel.demo and channel.status != "disabled":
        await _go_live(channel)  # Telegram must learn the new secret token
    await audit.record(
        session, action="channel.secret_rotated", principal=principal, entity_type="channel", entity_id=channel.id
    )
    return SecretOut(webhook_secret=secret, webhook_url=webhook_url(channel))


async def test(session: AsyncSession, principal: Principal, channel: Channel) -> TestOut:
    adapter = _adapter(channel.provider)
    if adapter is None:
        raise ApiError("Este canal lo gestiona otra sección (voz)", code="unsupported_provider")
    checked = datetime.now(UTC)
    if channel.demo:
        return TestOut(
            ok=True,
            status=channel.status,
            demo=True,
            details={"webhook_url": webhook_url(channel), "address": inbound_address(channel)},
            error=None,
            checked_at=checked,
        )
    ctx = channel_context(channel)
    missing = [*adapter.missing_credentials(ctx.credentials), *adapter.missing_config(ctx.config)]
    ok, error, details = True, None, {}
    if missing:
        ok, error = False, f"Faltan datos: {', '.join(missing)}"
    else:
        try:
            result = await adapter.check(ctx)
            details = result.details
            channel.config = {**(channel.config or {}), **result.config_updates}
        except ChannelError as exc:
            ok, error = False, exc.message
    if channel.status != "disabled":
        channel.status = "active" if ok else "error"
    channel.error = error
    await audit.record(
        session,
        action="channel.tested",
        principal=principal,
        entity_type="channel",
        entity_id=channel.id,
        diff={"ok": ok, "error": error},
    )
    return TestOut(ok=ok, status=channel.status, demo=False, details=details, error=error, checked_at=checked)


# ============================================================================================ simulator


def simulated_message(provider: str, sender: str, name: str | None, text: str) -> InboundMessage:
    key = sender if sender.startswith("sim:") else f"sim:{sender}"
    return InboundMessage(
        external_id=f"sim:{uuid.uuid4().hex}",
        conversation_key=key[:255],
        sender_id=key[:255],
        sender_name=name,
        text=text.strip(),
        reply={"simulated": True, "provider": provider},
        sent_at=datetime.now(UTC),
    )


async def simulate(principal: Principal, channel: Channel, body: SimulateIn) -> SimulateOut:
    if _adapter(channel.provider) is None:
        raise ApiError("El simulador no está disponible para este canal", code="unsupported_provider")
    if channel.status == "disabled":
        raise Conflict("El canal está pausado: reactívalo para simularlo", code="channel_disabled")
    default = f"sim:{principal.user_id.hex[:8]}" if principal.user_id else "sim:builder"
    sender = body.sender.strip() or default
    message = simulated_message(channel.provider, sender, body.name, body.text)
    recorded = await record_inbound(channel, [message], simulated=True)
    if not recorded or recorded[0].conversation_id is None:
        raise ApiError("No se pudo registrar el mensaje simulado", code="simulate_failed", status_code=500)
    item = recorded[0]
    assert item.conversation_id is not None
    return SimulateOut(
        message_id=item.message_id,
        conversation_id=item.conversation_id,
        sender=message.sender_id,
        duplicate=not item.new,
    )


async def messages(
    session: AsyncSession, channel: Channel, *, cursor: str | None, limit: int, direction: str | None
) -> ChannelMessagePage:
    q = select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
    if direction in ("inbound", "outbound"):
        q = q.where(ChannelMessage.direction == direction)
    if cursor:
        try:
            raw_ts, raw_id = cursor.split("|", 1)
            ts, last_id = datetime.fromisoformat(raw_ts), uuid.UUID(raw_id)
        except ValueError as exc:
            raise ApiError("Cursor no válido", code="invalid_cursor") from exc
        q = q.where(
            (ChannelMessage.created_at < ts) | ((ChannelMessage.created_at == ts) & (ChannelMessage.id < last_id))
        )
    rows = list(
        (await session.execute(q.order_by(ChannelMessage.created_at.desc(), ChannelMessage.id.desc()).limit(limit + 1)))
        .scalars()
        .all()
    )
    page = rows[:limit]
    items = [
        ChannelMessageOut(
            id=m.id,
            conversation_id=m.conversation_id,
            direction=m.direction,
            kind=m.kind,
            status=m.status,
            sender_id=m.sender_id,
            sender_name=m.sender_name,
            text=m.text,
            error=m.error,
            error_code=m.error_code,
            run_id=m.run_id,
            simulated=m.simulated,
            parts=(m.payload or {}).get("parts") if m.direction == "outbound" else None,
            created_at=m.created_at,
            processed_at=m.processed_at,
        )
        for m in page
    ]
    next_cursor = f"{page[-1].created_at.isoformat()}|{page[-1].id}" if len(rows) > limit and page else None
    return ChannelMessagePage(items=items, next_cursor=next_cursor)


# ============================================================================================== webhooks


def _response(reply: WebhookReply) -> Response:
    if reply.media_type == "application/json":
        return JSONResponse(reply.body if reply.body is not None else {"ok": True}, status_code=reply.status_code)
    return PlainTextResponse(str(reply.body or ""), status_code=reply.status_code, media_type=reply.media_type)


async def _inbound_request(request: Request) -> InboundRequest:
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BODY:
        raise ApiError("La petición es demasiado grande", code="payload_too_large", status_code=413)
    return InboundRequest(
        method=request.method.upper(),
        headers={k.lower(): v for k, v in request.headers.items()},
        query=dict(request.query_params),
        body=body,
    )


def _verify_demo(secret: str | None, req: InboundRequest) -> None:
    supplied = req.query.get("token") or req.header(DEMO_TOKEN_HEADER) or ""
    if not secret or not supplied or not hmac.compare_digest(supplied, secret):
        raise InvalidSignature("Los canales en modo demo aceptan llamadas con ?token=<secreto del canal>")


async def _rate_limit(key: str) -> None:
    limit, window = WEBHOOK_RATE
    allowed, retry_after = await hit(f"channel-webhook:{key}", limit, window)
    if not allowed:
        raise RateLimited("Demasiadas peticiones al webhook del canal", details={"retry_after": retry_after})


async def receive_webhook(channel_id: uuid.UUID, provider: str, request: Request) -> Response:
    """Public provider webhook: verify, parse, record (idempotent) and acknowledge fast."""
    if provider not in PROVIDERS:
        raise NotFound("Canal no encontrado")
    await _rate_limit(str(channel_id))
    req = await _inbound_request(request)
    async with system_session() as s:
        channel = await s.get(Channel, channel_id)
    if channel is None or channel.provider != provider:
        raise NotFound("Canal no encontrado")
    adapter = get_adapter(provider)
    ctx = channel_context(channel)
    if req.method == "GET":
        reply = adapter.handshake(ctx, req)
        if reply is None:
            raise ApiError("Método no permitido", code="method_not_allowed", status_code=405)
        return _response(reply)
    try:
        if channel.demo:
            _verify_demo(ctx.webhook_secret, req)
        else:
            await adapter.verify(ctx, req)
    except InvalidSignature as exc:
        log.warning("channel.webhook_rejected", channel_id=str(channel_id), provider=provider, reason=exc.message)
        raise Unauthorized(exc.message, code="invalid_signature") from exc
    try:
        immediate = adapter.immediate_reply(ctx, req)
        if immediate is not None:
            return _response(immediate)
        parsed = [] if channel.status == "disabled" else adapter.parse(ctx, req)
    except ChannelError as exc:
        raise ApiError(exc.message, code=exc.code) from exc
    recorded = await record_inbound(channel, parsed)
    log.info(
        "channel.webhook",
        channel_id=str(channel_id),
        provider=provider,
        parsed=len(parsed),
        queued=len(recorded),
    )
    return _response(adapter.ack(ctx, req))


async def receive_shared_email(request: Request) -> Response:
    """Shared inbound email webhook: routes mail sent to ``ch-<token>@<inbound domain>`` to its channel."""
    secret = get_settings().messer_inbound_email_secret
    req = await _inbound_request(request)
    header = req.header("authorization") or ""
    supplied = req.query.get("token") or header.split(" ", 1)[-1]
    if header.lower().startswith("basic ") and not req.query.get("token"):
        try:
            supplied = base64.b64decode(header[6:]).decode().split(":", 1)[-1]
        except (ValueError, UnicodeDecodeError):
            supplied = ""
    if not secret or not supplied or not hmac.compare_digest(secret, supplied):
        raise Unauthorized("Firma no válida", code="invalid_signature")
    await _rate_limit("shared-email")
    raw = req.json()
    if not isinstance(raw, dict):
        raise ApiError("El cuerpo debe ser un objeto JSON", code="invalid_body")
    email = email_channel.normalize(raw)
    tokens = email_channel.address_tokens(str(email.get("to") or ""))
    if not tokens:
        return JSONResponse({"accepted": True, "routed": 0}, status_code=202)
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(Channel).where(
                        Channel.provider == "email",
                        Channel.status != "disabled",
                        Channel.config["address_token"].astext.in_(sorted(tokens)),
                    )
                )
            )
            .scalars()
            .all()
        )
    adapter = email_channel.EmailAdapter()
    message = adapter.message_from(email)
    routed = 0
    for channel in rows:
        if message is not None:
            routed += len(await record_inbound(channel, [message]))
    return JSONResponse({"accepted": True, "routed": routed}, status_code=202)


async def receive_shared_whatsapp(request: Request) -> Response:
    """Webhook of the platform's own Meta app (``WHATSAPP_*``): routes events to the channel of each number.

    Only live channels that use the platform's WhatsApp credentials are candidates; when several share a phone
    number, the oldest one answers.
    """
    settings = get_settings()
    req = await _inbound_request(request)
    if req.method == "GET":
        token = req.query.get("hub.verify_token") or ""
        expected = settings.whatsapp_verify_token
        if req.query.get("hub.mode") == "subscribe" and expected and hmac.compare_digest(token, expected):
            return PlainTextResponse(req.query.get("hub.challenge") or "")
        return PlainTextResponse("invalid verify token", status_code=403)
    secret = settings.whatsapp_app_secret
    if not secret:
        raise NotFound("WhatsApp de la plataforma no configurado")
    header = req.header("x-hub-signature-256") or ""
    expected_sig = hmac.new(secret.encode(), req.body, hashlib.sha256).hexdigest()
    if not header.startswith("sha256=") or not hmac.compare_digest(expected_sig, header[7:].strip().lower()):
        raise Unauthorized("Firma de WhatsApp no válida", code="invalid_signature")
    await _rate_limit("shared-whatsapp")
    async with system_session() as s:
        rows = (
            (
                await s.execute(
                    select(Channel)
                    .where(Channel.provider == "whatsapp", Channel.demo.is_(False), Channel.status != "disabled")
                    .order_by(Channel.created_at)
                )
            )
            .scalars()
            .all()
        )
    adapter = get_adapter("whatsapp")
    routed = 0
    numbers: set[str] = set()
    for channel in rows:
        if credential_source(channel) not in ("platform", "mixed"):
            continue
        ctx = channel_context(channel)
        number = str(ctx.config.get("phone_number_id") or "")
        if not number or number in numbers:
            continue
        numbers.add(number)
        try:
            parsed = adapter.parse(ctx, req)
        except ChannelError as exc:
            raise ApiError(exc.message, code=exc.code) from exc
        routed += len(await record_inbound(channel, parsed))
    return JSONResponse({"ok": True, "routed": routed})
