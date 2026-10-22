"""Generic inbound webhooks: a URL with a secret; verified requests become connector events (``received``)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, tuple_

from messer_common.db import system_session
from messer_common.security import constant_time_equals, hmac_sha256_hex, random_token
from messer_common.settings import get_settings

from ..base import (
    ActionSpec,
    Capabilities,
    ConfigError,
    ConfigField,
    ConnectionContext,
    ConnectorAdapter,
    ConnectorAuthError,
    ConnectorSpec,
    TestResult,
    obj_schema,
)
from ..registry import register
from ..util import validate_args

SIGNATURE_HEADERS = ("x-messer-signature", "x-hub-signature-256", "x-signature-256", "x-webhook-signature")
TIMESTAMP_HEADER = "x-messer-timestamp"
MAX_SKEW_S = 300
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def inbound_url(connection_id: uuid.UUID | str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/webhooks/connections/{connection_id}"


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    """Signature a sender must put in ``X-Messer-Signature`` (``sha256=<hex>``)."""
    payload = f"{timestamp}.".encode() + body if timestamp is not None else body
    return "sha256=" + hmac_sha256_hex(secret, payload)


def verify_request(
    *,
    secret: str,
    mode: str,
    body: bytes,
    headers: Mapping[str, str],
    query: Mapping[str, str],
    now: float | None = None,
) -> None:
    """Raise :class:`ConnectorAuthError` unless the request carries a valid HMAC signature (or token)."""
    lowered = {k.lower(): v for k, v in headers.items()}
    if mode == "token":
        bearer = lowered.get("authorization", "")
        candidate = (
            lowered.get("x-messer-token")
            or (bearer[7:].strip() if bearer.lower().startswith("bearer ") else "")
            or query.get("token", "")
        )
        if candidate and constant_time_equals(candidate, secret):
            return
        raise ConnectorAuthError("Token del webhook no válido", code="webhook_token")
    signature = next((lowered[h] for h in SIGNATURE_HEADERS if lowered.get(h)), "")
    if not signature:
        raise ConnectorAuthError("Falta la firma HMAC (cabecera X-Messer-Signature)", code="webhook_signature_missing")
    provided = signature.split("=", 1)[1] if signature.lower().startswith("sha256=") else signature
    raw_ts = lowered.get(TIMESTAMP_HEADER)
    if raw_ts:
        try:
            ts = int(raw_ts)
        except ValueError as exc:
            raise ConnectorAuthError("Marca de tiempo del webhook no válida", code="webhook_timestamp") from exc
        if abs((now if now is not None else time.time()) - ts) > MAX_SKEW_S:
            raise ConnectorAuthError("La petición del webhook ha caducado", code="webhook_timestamp")
        expected = hmac_sha256_hex(secret, f"{ts}.".encode() + body)
    else:
        expected = hmac_sha256_hex(secret, body)
    if not constant_time_equals(provided.strip().lower(), expected):
        raise ConnectorAuthError("Firma HMAC no válida", code="webhook_signature")


def make_cursor(created_at: datetime, event_id: uuid.UUID | str) -> str:
    return f"{created_at.astimezone(UTC).isoformat()}|{event_id}"


def parse_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    stamp, _, ident = cursor.partition("|")
    parsed = datetime.fromisoformat(stamp)
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)), uuid.UUID(ident or ZERO_UUID)


def event_out(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "event": row.event,
        "occurred_at": row.created_at.isoformat() if row.created_at else None,
        "data": {"payload": row.payload, "headers": row.headers, "query": row.query, "source_ip": row.source_ip},
    }


@register
class WebhooksAdapter(ConnectorAdapter):
    spec = ConnectorSpec(
        key="webhooks",
        name="Webhooks",
        category="developer",
        auth_type="none",
        description="URL de entrada con secreto y verificación HMAC: cada petición genera un evento para tus flujos.",
        description_en="Inbound URL with a secret and HMAC verification: each request becomes an event for workflows.",
        icon="webhook",
        capabilities=Capabilities(actions=["list_events"], events=["received"]),
        config_fields=[ConfigField(key="verification", kind="select", options=["hmac", "token"], default="hmac")],
    )

    def actions(self) -> list[ActionSpec]:
        return [
            ActionSpec(
                name="list_events",
                title="Últimos eventos",
                description="Eventos recibidos por el webhook, del más reciente al más antiguo.",
                input_schema=obj_schema({"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}}),
            )
        ]

    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        if config.get("verification", "hmac") not in ("hmac", "token"):
            raise ConfigError("La verificación debe ser «hmac» o «token»", details={"field": "verification"})

    def prepare(self, config: dict[str, Any], credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        config = {**config, "verification": config.get("verification") or "hmac"}
        credentials = dict(credentials)
        if not credentials.get("secret"):
            credentials["secret"] = random_token(32)
        return config, credentials

    async def test(self, ctx: ConnectionContext) -> TestResult:
        return TestResult(
            ok=True, message="URL lista para recibir eventos", details={"url": inbound_url(ctx.connection_id)}
        )

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        from messer_common.db.models.connectors import ConnectorEvent

        data = validate_args(self.action(action), args)
        async with system_session() as s:
            rows = (
                (
                    await s.execute(
                        select(ConnectorEvent)
                        .where(ConnectorEvent.org_id == ctx.org_id, ConnectorEvent.connection_id == ctx.connection_id)
                        .order_by(ConnectorEvent.created_at.desc(), ConnectorEvent.id.desc())
                        .limit(int(data["limit"]))
                    )
                )
                .scalars()
                .all()
            )
        return [event_out(r) for r in rows]

    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        from messer_common.db.models.connectors import ConnectorEvent

        self._check_event(event)
        if cursor is None:
            return [], make_cursor(datetime.now(UTC), ZERO_UUID)
        stamp, ident = parse_cursor(cursor)
        async with system_session() as s:
            rows = (
                (
                    await s.execute(
                        select(ConnectorEvent)
                        .where(
                            ConnectorEvent.org_id == ctx.org_id,
                            ConnectorEvent.connection_id == ctx.connection_id,
                            tuple_(ConnectorEvent.created_at, ConnectorEvent.id) > tuple_(stamp, ident),
                        )
                        .order_by(ConnectorEvent.created_at, ConnectorEvent.id)
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
        if not rows:
            return [], cursor
        return [event_out(r) for r in rows], make_cursor(rows[-1].created_at, rows[-1].id)
