"""Twilio: voice webhook (TwiML), status callback and Media Streams WebSocket.

* ``POST /telephony/twilio/voice`` — the number's *A call comes in* webhook (inbound) and the ``Url`` of calls the
  API places (outbound, ``?call=<id>``). Signature-validated (``X-Twilio-Signature``, HMAC-SHA1 with
  ``TWILIO_AUTH_TOKEN``). Answers with TwiML that connects the call to the media stream below, carrying a
  single-use ticket for the call as a ``<Parameter>``.
* ``POST /telephony/twilio/status`` — status callback; ends calls that never reached the media stream.
* ``WS /telephony/twilio/media`` — bidirectional Media Streams bridged into the voice session.
"""

from __future__ import annotations

from urllib.parse import parse_qsl
from xml.sax.saxutils import escape, quoteattr

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket

from messer.server.telephony import TWILIO
from messer_common.logging import get_logger
from messer_common.settings import get_settings

from .. import calls, tickets
from ..calls import CallUnavailable
from ..config import get_voice_settings
from ..phrases import phrase
from ..providers import select_pipeline
from .bridge import serve_media
from .common import (
    TWILIO_STATUS,
    create_inbound_call,
    end_unanswered,
    find_number,
    parse_call_id,
    provider_allowed,
    twilio_signature_valid,
)

log = get_logger("messer.voice.twilio")
router = APIRouter(prefix="/telephony/twilio", tags=["telephony"])

MEDIA_TICKET_TTL_S = 120
_TWIML_LANG = {"es": "es-ES", "en": "en-US"}


def _twiml(body: str) -> Response:
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>', media_type="application/xml"
    )


def say_and_hangup(text: str, language: str) -> Response:
    lang = _TWIML_LANG.get(language[:2], "es-ES")
    return _twiml(f"<Say language={quoteattr(lang)}>{escape(text)}</Say><Hangup/>")


def stream_twiml(call_id: str, ticket: str) -> Response:
    url = f"{get_voice_settings().public_ws_url}/telephony/twilio/media"
    params = "".join(
        f"<Parameter name={quoteattr(k)} value={quoteattr(v)} />" for k, v in (("call_id", call_id), ("ticket", ticket))
    )
    return _twiml(f"<Connect><Stream url={quoteattr(url)}>{params}</Stream></Connect>")


async def _verified_form(request: Request) -> dict[str, str]:
    """Parse the form body and enforce the Twilio signature (telephony is off without credentials)."""
    token = get_settings().twilio_auth_token
    if not token:
        raise HTTPException(status_code=503, detail="Twilio is not configured")
    body = await request.body()
    params = dict(parse_qsl(body.decode("utf-8", "replace"), keep_blank_values=True))
    suffix = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    candidates = [f"{get_voice_settings().public_url}{suffix}", f"{proto}://{host}{suffix}"]
    if not twilio_signature_valid(candidates, params, request.headers.get("x-twilio-signature", ""), token):
        log.warning("voice.twilio.bad_signature", path=request.url.path)
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")
    return params


@router.post("/voice")
async def voice_webhook(request: Request) -> Response:
    form = await _verified_form(request)
    call_sid = form.get("CallSid", "")
    outbound_id = parse_call_id(request.query_params.get("call"))
    if outbound_id is not None:
        try:
            call = await calls.load_call(outbound_id)
        except CallUnavailable:
            return say_and_hangup(phrase("not_available", "es"), "es")
        if call.transport != "twilio" or (call.external_call_id and call.external_call_id != call_sid):
            raise HTTPException(status_code=403, detail="Call mismatch")
        if not call.external_call_id:
            await calls.update_call(call.id, external_call_id=call_sid)
    else:
        number = await find_number("twilio", form.get("To", ""))
        if number is None:
            log.info("voice.twilio.unknown_number", to=form.get("To"))
            return say_and_hangup(phrase("not_available", "es"), "es")
        if not await provider_allowed(number.org_id, "twilio"):
            log.warning("voice.twilio.residency_blocked", org_id=str(number.org_id))
            return say_and_hangup(phrase("not_available", "es"), "es")
        call = await create_inbound_call(
            provider="twilio", number=number, from_number=form.get("From", ""), external_call_id=call_sid or None
        )
    try:
        ctx = await calls.call_context(call)
    except CallUnavailable as exc:
        await calls.fail_call(call.id, code=exc.code, message=str(exc))
        return say_and_hangup(phrase("not_available", call.language), call.language)
    if select_pipeline(ctx.residency) is None:
        await calls.fail_call(call.id, code="voice_unavailable", message="No hay proveedores de voz configurados")
        return say_and_hangup(phrase("not_available", ctx.language), ctx.language)
    ticket = tickets.mint("telephony", ttl_s=MEDIA_TICKET_TTL_S, call_id=call.id, org=str(call.org_id))
    return stream_twiml(str(call.id), ticket)


@router.post("/status")
async def status_callback(request: Request) -> Response:
    form = await _verified_form(request)
    call_id = parse_call_id(request.query_params.get("call"))
    status = TWILIO_STATUS.get(form.get("CallStatus", ""))
    if call_id is not None and status is not None:
        try:
            await end_unanswered(call_id, status, reason=form.get("CallStatus"))
        except CallUnavailable:
            pass
    return Response(status_code=204)


@router.websocket("/media")
async def media_stream(ws: WebSocket) -> None:
    await ws.accept()
    await serve_media(ws, TWILIO)
