"""Triggers: CRUD (``/api/v1``), signed webhooks (``/api/hooks/{id}``) and inbound email (``/api/inbound/email``)."""

from __future__ import annotations

import base64
import hmac
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit, triggers
from messer_common.db import Principal, system_session
from messer_common.db.models import Trigger
from messer_common.settings import get_settings

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, NotFound, RateLimited, Unauthorized
from ..ratelimit import hit
from ..services import channels as channels_svc
from ..services import projects as svc

router = APIRouter(tags=["triggers"])
public_router = APIRouter(tags=["triggers"])

TriggerKind = Literal["manual", "cron", "webhook", "email", "file", "connector_event"]


class TriggerIn(BaseModel):
    workforce: str = Field(min_length=1, max_length=80)
    kind: TriggerKind
    name: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    environment: Literal["development", "production"] = "production"
    enabled: bool = True


class TriggerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None
    environment: Literal["development", "production"] | None = None
    enabled: bool | None = None


def _apply_schedule(trigger: Trigger) -> None:
    if trigger.kind == "cron" and trigger.enabled:
        cfg = trigger.config or {}
        trigger.next_fire_at = triggers.next_cron(cfg["expression"], cfg.get("timezone", "Europe/Madrid"))
    else:
        trigger.next_fire_at = None


def _validated(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    try:
        return triggers.validate_config(kind, config)
    except (triggers.TriggerConfigError, ValueError) as exc:
        raise ApiError(str(exc), code="invalid_trigger") from exc


@router.get("/projects/{project_id}/triggers")
async def list_triggers(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    ensure_project_access(principal, project_id)
    rows = (
        (await session.execute(select(Trigger).where(Trigger.project_id == project_id).order_by(Trigger.created_at)))
        .scalars()
        .all()
    )
    return [triggers.describe(t) for t in rows]


@router.post("/projects/{project_id}/triggers", status_code=201)
async def create_trigger(
    project_id: uuid.UUID,
    body: TriggerIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    ensure_project_access(principal, project_id)
    project = await svc.get_project(session, project_id)
    member = await svc.get_member(session, project, body.workforce)
    trigger = Trigger(
        org_id=project.org_id,
        project_id=project.id,
        workforce_id=member.id,
        kind=body.kind,
        name=body.name or f"{body.kind} · {member.name}",
        config=_validated(body.kind, body.config),
        environment=body.environment,
        enabled=body.enabled,
    )
    plain_secret: str | None = None
    if body.kind == "webhook":
        plain_secret, trigger.secret = triggers.new_secret()
    _apply_schedule(trigger)
    session.add(trigger)
    await session.flush()
    await audit.record(
        session,
        action="trigger.created",
        principal=principal,
        entity_type="trigger",
        entity_id=trigger.id,
        diff={"kind": body.kind, "workforce": member.name},
    )
    out = triggers.describe(trigger)
    if plain_secret:
        out["secret"] = plain_secret  # shown once
    return out


async def _get(session: AsyncSession, principal: Principal, trigger_id: uuid.UUID) -> Trigger:
    trigger = await session.get(Trigger, trigger_id)
    if trigger is None or trigger.org_id != principal.org_id:
        raise NotFound("Disparador no encontrado")
    ensure_project_access(principal, trigger.project_id)
    return trigger


@router.patch("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: uuid.UUID,
    body: TriggerPatch,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    trigger = await _get(session, principal, trigger_id)
    if body.name is not None:
        trigger.name = body.name
    if body.config is not None:
        merged = {**(trigger.config or {}), **body.config}
        trigger.config = _validated(trigger.kind, merged)
    if body.environment is not None:
        trigger.environment = body.environment
    if body.enabled is not None:
        trigger.enabled = body.enabled
    _apply_schedule(trigger)
    await audit.record(
        session,
        action="trigger.updated",
        principal=principal,
        entity_type="trigger",
        entity_id=trigger.id,
        diff=body.model_dump(exclude_none=True),
    )
    return triggers.describe(trigger)


@router.delete("/triggers/{trigger_id}", status_code=204)
async def delete_trigger(
    trigger_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    trigger = await _get(session, principal, trigger_id)
    await audit.record(
        session,
        action="trigger.deleted",
        principal=principal,
        entity_type="trigger",
        entity_id=trigger.id,
        diff={"kind": trigger.kind},
    )
    await session.delete(trigger)


@router.post("/triggers/{trigger_id}/rotate-secret")
async def rotate_secret(
    trigger_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    trigger = await _get(session, principal, trigger_id)
    if trigger.kind != "webhook":
        raise ApiError("Solo los webhooks tienen secreto", code="not_webhook")
    plain, trigger.secret = triggers.new_secret()
    await audit.record(
        session, action="trigger.secret_rotated", principal=principal, entity_type="trigger", entity_id=trigger.id
    )
    return {**triggers.describe(trigger), "secret": plain}


class FireIn(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/triggers/{trigger_id}/fire", status_code=202)
async def fire_now(
    trigger_id: uuid.UUID,
    body: FireIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fire manually (test the flow with a sample payload, or the 'manual' trigger kind)."""
    trigger = await _get(session, principal, trigger_id)
    payload = {
        "type": trigger.kind if trigger.kind != "manual" else "manual",
        **body.payload,
        "fired_by": str(principal.user_id) if principal.user_id else None,
    }
    job = await triggers.fire(trigger, payload)
    await audit.record(
        session, action="trigger.fired_manually", principal=principal, entity_type="trigger", entity_id=trigger.id
    )
    return {"accepted": True, "job_id": job}


# ------------------------------------------------------------------------------------------ webhooks


@public_router.post("/api/hooks/{trigger_id}", status_code=202)
@public_router.post("/hooks/{trigger_id}", status_code=202, include_in_schema=False)
async def receive_webhook(
    trigger_id: uuid.UUID,
    request: Request,
    x_messer_signature: str | None = Header(default=None),
    x_messer_event_id: str | None = Header(default=None),
) -> JSONResponse:
    """Signed webhook: ``X-Messer-Signature: t=<unix>,v1=<hex hmac_sha256(secret, "<t>.<body>")>``."""
    allowed, retry_after = await hit(f"hook:{trigger_id}", limit=120, window_s=60)
    if not allowed:
        raise RateLimited("Demasiadas solicitudes a este webhook", details={"retry_after": retry_after})
    body = await request.body()
    if len(body) > 1_000_000:
        raise ApiError("El cuerpo supera 1 MB", code="payload_too_large", status_code=413)
    async with system_session() as s:
        trigger = await s.get(Trigger, trigger_id)
        if trigger is None or trigger.kind != "webhook":
            raise NotFound("Webhook no encontrado")
        if not triggers.verify_signature(trigger, body, x_messer_signature):
            raise Unauthorized("Firma no válida", code="invalid_signature")
        if not trigger.enabled:
            raise ApiError("El disparador está desactivado", code="trigger_disabled", status_code=409)
        try:
            data: Any = json.loads(body) if body else {}
        except json.JSONDecodeError:
            data = {"raw": body.decode(errors="replace")[:100_000]}
        payload = {
            "type": "webhook",
            "body": data,
            "received_at": datetime.now(UTC).isoformat(),
            "headers": {
                k: v
                for k, v in request.headers.items()
                if k.lower() in ("content-type", "user-agent", "x-messer-event-id")
            },
        }
        event_id = x_messer_event_id or x_messer_signature or uuid.uuid4().hex
        job = await triggers.fire(trigger, payload, event_id=f"webhook:{event_id}")
    return JSONResponse({"accepted": True, "job_id": job}, status_code=202)


# -------------------------------------------------------------------------------------- inbound email

_ADDRESS = re.compile(r"wf-([0-9a-f]{16})@", re.IGNORECASE)


class InboundEmail(BaseModel):
    """Normalized inbound email. Postmark's inbound JSON (``From``, ``To``, ``Subject``, ``TextBody``) is accepted too."""

    to: str = ""
    sender: str = Field(default="", alias="from")
    subject: str = ""
    text: str = ""
    html: str | None = None
    message_id: str | None = None

    model_config = {"populate_by_name": True}


def _normalize(raw: dict[str, Any]) -> InboundEmail:
    if "From" in raw or "TextBody" in raw:
        return InboundEmail.model_validate(
            {
                "to": str(raw.get("OriginalRecipient") or raw.get("To") or ""),
                "from": str(raw.get("From") or ""),
                "subject": str(raw.get("Subject") or ""),
                "text": str(raw.get("TextBody") or raw.get("StrippedTextReply") or ""),
                "html": raw.get("HtmlBody"),
                "message_id": raw.get("MessageID"),
            }
        )
    return InboundEmail.model_validate(raw)


@public_router.post("/api/inbound/email", status_code=202)
@public_router.post("/inbound-email", status_code=202, include_in_schema=False)
async def inbound_email(
    request: Request, token: str | None = None, authorization: str | None = Header(default=None)
) -> JSONResponse:
    """Inbound email webhook from the provider (secret as ``?token=`` or HTTP Basic/Bearer).

    The single provider URL for the inbound domain: ``wf-<token>@`` addresses fire email triggers and
    ``ch-<token>@`` addresses reach email channels.
    """
    secret = get_settings().messer_inbound_email_secret
    header = authorization or ""
    supplied = token or header.split(" ", 1)[-1]
    if not token and header.lower().startswith("basic "):
        try:
            supplied = base64.b64decode(header[6:]).decode().split(":", 1)[-1]
        except (ValueError, UnicodeDecodeError):
            supplied = ""
    if not secret or not supplied or not hmac.compare_digest(secret, supplied):
        raise Unauthorized("Firma no válida", code="invalid_signature")
    raw = await request.json()
    if not isinstance(raw, dict):
        raise ApiError("El cuerpo debe ser un objeto JSON", code="invalid_body")
    fired = await dispatch_inbound_email(_normalize(raw))
    routed = await channels_svc.route_inbound_email(raw)
    return JSONResponse({"accepted": True, "fired": fired, "routed": routed}, status_code=202)


async def dispatch_inbound_email(email: InboundEmail) -> int:
    tokens = {m.group(1).lower() for m in _ADDRESS.finditer(email.to)}
    if not tokens:
        return 0
    fired = 0
    async with system_session() as s:
        rows = (
            (await s.execute(select(Trigger).where(Trigger.kind == "email", Trigger.enabled.is_(True)))).scalars().all()
        )
        for trigger in rows:
            if str((trigger.config or {}).get("address_token", "")).lower() not in tokens:
                continue
            payload = {
                "type": "email",
                "from": email.sender,
                "to": email.to,
                "subject": email.subject,
                "text": email.text[:200_000],
                "html": (email.html or "")[:200_000] or None,
                "message_id": email.message_id,
            }
            await triggers.fire(trigger, payload, event_id=f"email:{email.message_id or uuid.uuid4().hex}")
            fired += 1
    return fired


@router.post("/triggers/{trigger_id}/simulate-email", status_code=202)
async def simulate_email(
    trigger_id: uuid.UUID,
    body: InboundEmail,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Send a test email to the trigger's address without an inbound provider (local and demo mode)."""
    trigger = await _get(session, principal, trigger_id)
    address = triggers.inbound_address(trigger)
    if address is None:
        raise ApiError("Este disparador no es de email", code="not_email")
    fired = await dispatch_inbound_email(body.model_copy(update={"to": address}))
    return {"accepted": True, "fired": fired, "address": address}
