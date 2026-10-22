"""Telnyx: Call Control webhooks and bidirectional media streaming.

* ``POST /telephony/telnyx/webhook`` — the Call Control application's webhook (Ed25519 signature with
  ``TELNYX_PUBLIC_KEY``). ``call.initiated`` for an inbound call to an assigned number answers it with a media
  stream (``stream_url`` with a single-use ticket, RTP PCMU both ways); calls placed by the API already carry
  their stream. ``call.hangup`` ends calls that never reached the media stream.
* ``WS /telephony/telnyx/media`` — the media stream bridged into the voice session.
"""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from messer.server.telephony import TELNYX
from messer_common.logging import get_logger
from messer_common.settings import get_settings

from .. import calls, tickets
from ..calls import CallUnavailable
from ..config import get_voice_settings
from ..providers import select_pipeline
from .bridge import serve_media
from .common import (
    TELNYX_HANGUP,
    create_inbound_call,
    end_unanswered,
    find_call_by_external,
    find_number,
    parse_call_id,
    provider_allowed,
    telnyx_signature_valid,
)

log = get_logger("messer.voice.telnyx")
router = APIRouter(prefix="/telephony/telnyx", tags=["telephony"])

API_BASE = "https://api.telnyx.com/v2"
MEDIA_TICKET_TTL_S = 120
# Test hook: route Telnyx API calls through a custom transport.
transport: httpx.AsyncBaseTransport | None = None


class TelnyxError(Exception):
    pass


async def command(call_control_id: str, action: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST a Call Control command (``answer``, ``hangup``, …)."""
    key = get_settings().telnyx_api_key
    async with httpx.AsyncClient(
        base_url=API_BASE, headers={"Authorization": f"Bearer {key}"}, timeout=15, transport=transport
    ) as client:
        res = await client.post(f"/calls/{call_control_id}/actions/{action}", json=body)
    if res.status_code >= 300:
        raise TelnyxError(f"Telnyx {action} failed ({res.status_code}): {res.text[:300]}")
    return res.json() if res.content else {}


def media_url(call_id: str, ticket: str) -> str:
    query = urlencode({"call": call_id, "ticket": ticket})
    return f"{get_voice_settings().public_ws_url}/telephony/telnyx/media?{query}"


def stream_options(call_id: str, ticket: str) -> dict[str, Any]:
    return {
        "stream_url": media_url(call_id, ticket),
        "stream_track": "inbound_track",
        "stream_bidirectional_mode": "rtp",
        "stream_bidirectional_codec": "PCMU",
        "client_state": base64.b64encode(call_id.encode()).decode(),
    }


def _client_state_call(payload: dict[str, Any]) -> str | None:
    raw = payload.get("client_state")
    if not raw:
        return None
    try:
        return base64.b64decode(str(raw)).decode()
    except ValueError:
        return None


async def _verified_event(request: Request) -> dict[str, Any]:
    public_key = get_voice_settings().telnyx_public_key
    if not (get_settings().telnyx_api_key and public_key):
        raise HTTPException(status_code=503, detail="Telnyx is not configured")
    body = await request.body()
    if not telnyx_signature_valid(
        body,
        request.headers.get("telnyx-timestamp", ""),
        request.headers.get("telnyx-signature-ed25519", ""),
        public_key,
    ):
        log.warning("voice.telnyx.bad_signature")
        raise HTTPException(status_code=403, detail="Invalid Telnyx signature")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    event = data.get("data") if isinstance(data, dict) else None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Missing event")
    return event


async def _answer_inbound(payload: dict[str, Any]) -> None:
    ccid = str(payload.get("call_control_id") or "")
    number = await find_number("telnyx", str(payload.get("to") or ""))
    if number is None or not ccid:
        log.info("voice.telnyx.unknown_number", to=payload.get("to"))
        if ccid:
            await command(ccid, "hangup", {})
        return
    if not await provider_allowed(number.org_id, "telnyx"):
        log.warning("voice.telnyx.residency_blocked", org_id=str(number.org_id))
        await command(ccid, "hangup", {})
        return
    call = await create_inbound_call(
        provider="telnyx", number=number, from_number=str(payload.get("from") or ""), external_call_id=ccid
    )
    try:
        ctx = await calls.call_context(call)
        if select_pipeline(ctx.residency) is None:
            raise CallUnavailable("No hay proveedores de voz configurados", code="voice_unavailable")
    except CallUnavailable as exc:
        await calls.fail_call(call.id, code=exc.code, message=str(exc))
        await command(ccid, "hangup", {})
        return
    ticket = tickets.mint("telephony", ttl_s=MEDIA_TICKET_TTL_S, call_id=call.id, org=str(call.org_id))
    await command(ccid, "answer", stream_options(str(call.id), ticket))


@router.post("/webhook")
async def webhook(request: Request) -> Response:
    event = await _verified_event(request)
    kind = str(event.get("event_type") or "")
    payload = event.get("payload") or {}
    if not isinstance(payload, dict):
        return Response(status_code=204)
    try:
        if kind == "call.initiated" and payload.get("direction") == "incoming":
            await _answer_inbound(payload)
        elif kind == "call.answered":
            call_id = parse_call_id(_client_state_call(payload))
            if call_id is not None:
                call = await calls.load_call(call_id)
                if call.status in ("pending", "ringing"):
                    await calls.update_call(call_id, status="ringing")
        elif kind == "call.hangup":
            call_id = parse_call_id(_client_state_call(payload))
            if call_id is None and payload.get("call_control_id"):
                found = await find_call_by_external("telnyx", str(payload["call_control_id"]))
                call_id = found.id if found else None
            if call_id is not None:
                cause = str(payload.get("hangup_cause") or "")
                await end_unanswered(call_id, TELNYX_HANGUP.get(cause, "failed"), reason=cause or None)
    except (TelnyxError, httpx.HTTPError) as exc:
        log.error("voice.telnyx.command_failed", event_type=kind, error=str(exc))
    except CallUnavailable:
        pass
    return Response(status_code=204)


@router.websocket("/media")
async def media_stream(ws: WebSocket) -> None:
    await ws.accept()
    await serve_media(ws, TELNYX, query_ticket=ws.query_params.get("ticket"))
