"""``POST /api/v1/webhooks/stripe`` — Stripe events (public, authenticated by the Stripe signature).

The signature is verified with ``STRIPE_WEBHOOK_SECRET`` (5-minute tolerance). Events are processed
idempotently (``stripe_events``) inside one transaction: a failure returns 500 so Stripe retries, and
nothing is half-applied.
"""

from __future__ import annotations

import json
from typing import Any

import stripe
from fastapi import APIRouter, Request

from messer_common.db import system_session
from messer_common.logging import get_logger
from messer_common.settings import get_settings

from ..errors import ApiError
from ..services.billing import process_event

log = get_logger("messer.api.stripe_webhooks")

public_router = APIRouter(tags=["webhooks"])

SIGNATURE_TOLERANCE_S = 300


@public_router.post("/api/v1/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict[str, Any]:
    secret = get_settings().stripe_webhook_secret
    if not secret:
        raise ApiError(
            "Los webhooks de Stripe no están configurados (STRIPE_WEBHOOK_SECRET).",
            code="webhook_not_configured",
            status_code=503,
        )
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    try:
        stripe.WebhookSignature.verify_header(
            payload.decode("utf-8"), signature, secret, tolerance=SIGNATURE_TOLERANCE_S
        )
    except (stripe.SignatureVerificationError, UnicodeDecodeError) as exc:
        log.warning("stripe.webhook_bad_signature", error=str(exc))
        raise ApiError("Firma de Stripe no válida", code="invalid_signature", status_code=400) from exc
    try:
        event = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ApiError("Evento no válido", code="invalid_payload", status_code=400) from exc
    if not isinstance(event, dict) or "id" not in event or "type" not in event:
        raise ApiError("Evento no válido", code="invalid_payload", status_code=400)
    async with system_session() as s:
        processed = await process_event(s, event)
    log.info("stripe.webhook", event_id=event["id"], event_type=event["type"], duplicate=not processed)
    return {"received": True, "duplicate": not processed}
