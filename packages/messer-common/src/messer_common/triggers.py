"""Workflow and agent triggers: cron schedules, signed webhooks, inbound email, knowledge files, connector events.

Every firing becomes a worker job (``Jobs.FIRE_TRIGGER``) that runs the member through the runtime with the
trigger's payload. Firing is idempotent per event id, so retried webhooks and duplicated provider events run once.

Input convention: a workflow receives ``{"event": <payload>, **config.static_input}``; an agent receives a
``prompt`` built from the payload (the email text, the file name, …).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import Trigger, Workforce
from .execution import NotDeployed, resolve_target
from .logging import get_logger
from .queue import Jobs, enqueue
from .security import decrypt, encrypt
from .settings import get_settings

log = get_logger("messer.triggers")

TRIGGER_KINDS = ("manual", "cron", "webhook", "email", "file", "connector_event")
EVENT_KINDS = {"file": "kb.file_uploaded", "connector_event": "connector.event"}
SIGNATURE_HEADER = "X-Messer-Signature"
SIGNATURE_TOLERANCE_S = 300
MIN_CRON_INTERVAL_S = 60


class TriggerConfigError(ValueError):
    pass


# ------------------------------------------------------------------------------------------------ cron


def _zone(tz: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TriggerConfigError(f"Zona horaria desconocida: {tz}") from exc


def next_cron(expression: str, timezone: str = "Europe/Madrid", after: datetime | None = None) -> datetime:
    """Next firing time (UTC) of a 5-field cron expression evaluated in ``timezone``."""
    zone = _zone(timezone)
    base = (after or datetime.now(UTC)).astimezone(zone)
    if not croniter.is_valid(expression):
        raise TriggerConfigError(f"Expresión cron no válida: {expression}")
    nxt = croniter(expression, base).get_next(datetime)
    return nxt.astimezone(UTC)


def _check_cron(expression: str, timezone: str) -> None:
    first = next_cron(expression, timezone)
    second = next_cron(expression, timezone, first)
    if (second - first).total_seconds() < MIN_CRON_INTERVAL_S:
        raise TriggerConfigError("La frecuencia mínima es de un minuto")


# --------------------------------------------------------------------------------------------- config


def validate_config(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """Normalize and validate a trigger's configuration; raises :class:`TriggerConfigError`."""
    if kind not in TRIGGER_KINDS:
        raise TriggerConfigError(f"Tipo de disparador desconocido: {kind}")
    cfg = dict(config or {})
    static = cfg.get("static_input") or {}
    if not isinstance(static, dict):
        raise TriggerConfigError("static_input debe ser un objeto")
    cfg["static_input"] = static
    if kind == "cron":
        expression = str(cfg.get("expression") or "").strip()
        timezone = str(cfg.get("timezone") or "Europe/Madrid")
        _check_cron(expression, timezone)
        cfg.update(expression=expression, timezone=timezone)
    elif kind == "file":
        if not cfg.get("kb_id"):
            raise TriggerConfigError("Elige la base de conocimiento que dispara el flujo")
        cfg["kb_id"] = str(uuid.UUID(str(cfg["kb_id"])))
    elif kind == "connector_event":
        if not cfg.get("connection_id") or not cfg.get("event"):
            raise TriggerConfigError("Elige la conexión y el evento")
        cfg["connection_id"] = str(uuid.UUID(str(cfg["connection_id"])))
        cfg["event"] = str(cfg["event"])
    elif kind == "email":
        cfg.setdefault("address_token", secrets.token_hex(8))
    return cfg


def new_secret() -> tuple[str, str]:
    """(plain secret shown once, encrypted value to store)."""
    plain = "whsec_" + secrets.token_urlsafe(32)
    return plain, encrypt(plain)


def webhook_url(trigger: Trigger) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/hooks/{trigger.id}"


def inbound_address(trigger: Trigger) -> str | None:
    token = (trigger.config or {}).get("address_token")
    if trigger.kind != "email" or not token:
        return None
    return f"wf-{token}@{get_settings().messer_inbound_email_domain}"


def describe(trigger: Trigger) -> dict[str, Any]:
    """Public, secret-free view (the plain secret is only returned when created or rotated)."""
    return {
        "id": str(trigger.id),
        "kind": trigger.kind,
        "name": trigger.name,
        "config": trigger.config or {},
        "environment": trigger.environment,
        "enabled": trigger.enabled,
        "workforce_id": str(trigger.workforce_id),
        "project_id": str(trigger.project_id),
        "last_fired_at": trigger.last_fired_at.isoformat() if trigger.last_fired_at else None,
        "next_fire_at": trigger.next_fire_at.isoformat() if trigger.next_fire_at else None,
        "webhook_url": webhook_url(trigger) if trigger.kind == "webhook" else None,
        "inbound_address": inbound_address(trigger),
        "state": trigger.state or {},
    }


# ------------------------------------------------------------------------------------------- webhooks


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Header value ``t=<unix>,v1=<hex hmac-sha256 of "<t>.<body>">`` (what senders must compute)."""
    ts = int(timestamp if timestamp is not None else time.time())
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_signature(trigger: Trigger, body: bytes, header: str | None, *, now: float | None = None) -> bool:
    if not trigger.secret or not header:
        return False
    try:
        parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
        ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    if abs((now if now is not None else time.time()) - ts) > SIGNATURE_TOLERANCE_S:
        return False
    expected = sign(decrypt(trigger.secret), body, ts).split("v1=", 1)[1]
    return hmac.compare_digest(expected, parts.get("v1", ""))


# --------------------------------------------------------------------------------------------- firing


async def fire(trigger: Trigger, payload: dict[str, Any], *, event_id: str | None = None) -> str:
    """Queue one firing. Returns the job id (stable per event id, so duplicates are dropped by the queue)."""
    key = event_id or uuid.uuid4().hex
    job_id = f"trigger:{trigger.id}:{hashlib.sha256(key.encode()).hexdigest()[:24]}"
    await enqueue(Jobs.FIRE_TRIGGER, str(trigger.id), payload, key, _job_id=job_id)
    return job_id


async def emit(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    event: str,
    payload: dict[str, Any],
    event_id: str,
    kb_id: uuid.UUID | None = None,
    connection_id: uuid.UUID | None = None,
) -> int:
    """Platform event (knowledge file uploaded, connector event): fire every matching enabled trigger.

    ``event``: ``kb.file_uploaded`` (with ``kb_id``) or a connector event name such as ``gmail.new_email``
    (with ``connection_id``). Returns the number of triggers fired.
    """
    q = select(Trigger).where(Trigger.org_id == org_id, Trigger.enabled.is_(True))
    if event == EVENT_KINDS["file"]:
        q = q.where(Trigger.kind == "file")
    else:
        q = q.where(Trigger.kind == "connector_event")
    fired = 0
    for trigger in (await session.execute(q)).scalars():
        cfg = trigger.config or {}
        if trigger.kind == "file" and cfg.get("kb_id") != str(kb_id):
            continue
        if trigger.kind == "connector_event" and (
            cfg.get("connection_id") != str(connection_id) or cfg.get("event") not in (event, "*")
        ):
            continue
        await fire(trigger, {"type": event, **payload}, event_id=f"{event}:{event_id}")
        fired += 1
    if fired:
        log.info("triggers.emitted", event_name=event, org_id=str(org_id), fired=fired)
    return fired


def _agent_prompt(payload: dict[str, Any]) -> str:
    kind = payload.get("type")
    if kind == "email":
        return (
            f"Nuevo email de {payload.get('from', '')}\nAsunto: {payload.get('subject', '')}\n\n"
            f"{payload.get('text', '')}"
        ).strip()
    if kind == EVENT_KINDS["file"]:
        return f"Se ha subido el archivo «{payload.get('filename', '')}» a la base de conocimiento."
    return "Evento recibido:\n" + json.dumps(payload, ensure_ascii=False, default=str)[:20_000]


async def run_request(
    session: AsyncSession, trigger: Trigger, payload: dict[str, Any], event_id: str
) -> dict[str, Any]:
    """Runtime request for one firing (raises NotDeployed when production has no deployed version)."""
    member = await session.get(Workforce, trigger.workforce_id)
    if member is None:
        raise LookupError("workforce member no longer exists")
    target = await resolve_target(session, trigger.project_id, trigger.environment)
    static = (trigger.config or {}).get("static_input") or {}
    if member.kind == "agent":
        run_input: dict[str, Any] = {"prompt": str(static.get("prompt") or _agent_prompt(payload))}
    else:
        run_input = {**static, "event": payload}
    return {
        "org_id": str(trigger.org_id),
        "project_id": str(trigger.project_id),
        "workforce": member.name,
        "ref": target.ref,
        "input": run_input,
        "environment": target.environment,
        "environment_id": str(target.environment_id) if target.environment_id else None,
        "version_id": str(target.version_id) if target.version_id else None,
        "channel": "trigger",
        "trigger_id": str(trigger.id),
        "external_user_id": str(payload.get("from") or "")[:255] or None,
        "run_id": uuid.uuid5(uuid.NAMESPACE_URL, f"messer:trigger:{trigger.id}:{event_id}").hex,
    }


__all__ = [
    "SIGNATURE_HEADER",
    "TRIGGER_KINDS",
    "NotDeployed",
    "TriggerConfigError",
    "describe",
    "emit",
    "fire",
    "inbound_address",
    "new_secret",
    "next_cron",
    "run_request",
    "sign",
    "validate_config",
    "verify_signature",
    "webhook_url",
]
