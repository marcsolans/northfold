"""Browser voice sessions over WebSocket: ``WS /v1/session?ticket=…``.

The ticket comes from ``POST /api/v1/voice/sessions``. The wire protocol is the engine's voice WebSocket
protocol (``messer/server/README.md``) with two modes:

* **audio** (hosted STT/TTS configured): binary PCM16 mono 16 kHz up (or ``{"type": "audio", "data": b64}``),
  ``{"type": "audio", "data": b64}`` PCM down, ``{"type": "playback", "played_ms": n}`` acks up.
* **text** (demo mode, no STT/TTS keys): the browser transcribes and speaks. Up: ``{"type": "user_text", "text",
  "final": bool}``; down: ``{"type": "speak", "segment", "text", "duration_ms"}`` for every segment to say, and
  playback acks in the same unit as audio mode (milliseconds of those segments actually spoken).

Both modes receive the same session events (``session_started`` with ``mode``, ``transcript_partial`` /
``transcript_committed``, ``agent_text_delta`` / ``agent_text_done`` with ``run_id``, ``filler``, ``agent_status``,
``agent_approval``, ``metrics``, ``interrupted``, ``error``, ``session_transcript``, ``session_ended``) and a final
``call_summary``. ``{"type": "hangup"}`` ends the call.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from messer.server.voice import event_to_payloads
from messer.voice import AudioOutput, VoiceUsageEvent
from messer_common.logging import get_logger

from . import calls, tickets
from .calls import CallLog, CallUnavailable
from .context import CallContext
from .providers import SpokenPlaybackTracker, select_pipeline
from .runner import drive, mark_answered, new_bundle

log = get_logger("messer.voice.browser")
router = APIRouter()

MAX_TEXT_CHARS = 4000


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason[:120])


async def _reject(ws: WebSocket, code: int, error_code: str, message: str) -> None:
    with contextlib.suppress(Exception):
        await ws.send_json({"type": "error", "code": error_code, "message": message})
    await _close(ws, code, error_code)


@router.websocket("/v1/session")
async def browser_session(ws: WebSocket) -> None:
    await ws.accept()
    try:
        ticket = await tickets.redeem(ws.query_params.get("ticket", ""), "session")
        if ticket.call_id is None:
            raise tickets.TicketError("ticket without call")
    except tickets.TicketError as exc:
        log.info("voice.browser.ticket_rejected", reason=str(exc))
        await _reject(ws, 4401, "invalid_ticket", "La sesión de voz ha caducado. Vuelve a intentarlo.")
        return
    call_id = ticket.call_id
    try:
        call = await calls.load_call(call_id)
        if call.transport != "browser" or (ticket.org_id is not None and ticket.org_id != call.org_id):
            raise CallUnavailable("La llamada no es de navegador", code="wrong_transport")
        ctx = await calls.call_context(call)
    except CallUnavailable as exc:
        await calls.fail_call(call_id, code=exc.code, message=str(exc))
        await _reject(ws, 4409, exc.code, str(exc))
        return
    await serve_browser(ws, ctx)


async def serve_browser(ws: WebSocket, ctx: CallContext) -> None:
    pipeline = select_pipeline(ctx.residency) if ctx.mode == "audio" else None
    if pipeline is None:
        ctx.mode = "text"
    call_log = CallLog(ctx)
    outbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    bundle = new_bundle(ctx, call_log, pipeline=pipeline, on_text_segment=outbox.put_nowait)
    session = bundle.session
    meta: dict[str, Any] = {"playback_acks": "recommended", **bundle.meta}
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
    closed = asyncio.Event()

    async def _sender() -> None:
        while True:
            payload = await outbox.get()
            if payload is None:
                return
            try:
                await ws.send_json(payload)
            except Exception as exc:
                log.debug("voice.browser.send_skipped", type=payload.get("type"), error=str(exc))

    async def _receiver() -> None:
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                data = msg.get("bytes")
                if data:
                    if ctx.mode == "audio":
                        await audio_queue.put(data)
                    continue
                raw = msg.get("text")
                if not raw:
                    continue
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(frame, dict):
                    continue
                kind = frame.get("type")
                if kind == "audio" and ctx.mode == "audio":
                    try:
                        await audio_queue.put(base64.b64decode(str(frame.get("data") or "")))
                    except ValueError:
                        continue
                elif kind == "playback":
                    with contextlib.suppress(KeyError, TypeError, ValueError):
                        session.playback.on_playback_ack(float(frame["played_ms"]))
                elif kind == "speech_done" and isinstance(session.playback, SpokenPlaybackTracker):
                    session.playback.on_speech_done()
                elif kind == "user_text" and bundle.browser_stt is not None:
                    text = str(frame.get("text") or "")[:MAX_TEXT_CHARS]
                    bundle.browser_stt.feed(text, final=bool(frame.get("final", True)))
                elif kind == "hangup":
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("voice.browser.receive_failed", error=str(exc))
        finally:
            closed.set()
            await audio_queue.put(b"")
            await session.close()

    async def _audio_in() -> AsyncIterator[bytes]:
        if ctx.mode == "audio":
            while True:
                chunk = await audio_queue.get()
                if not chunk:
                    return
                yield chunk
        else:
            await closed.wait()

    async def _on_event(event: Any) -> None:
        if isinstance(event, AudioOutput):
            if ctx.mode == "audio":
                outbox.put_nowait({"type": "audio", "data": base64.b64encode(event.data).decode("ascii")})
            return
        if isinstance(event, VoiceUsageEvent):
            return
        for payload in event_to_payloads(event, session, meta):
            outbox.put_nowait(payload)

    await mark_answered(ctx, bundle)
    sender = asyncio.create_task(_sender())
    receiver = asyncio.create_task(_receiver())
    status = await drive(bundle, call_log, _audio_in(), _on_event)
    receiver.cancel()
    await asyncio.gather(receiver, return_exceptions=True)
    final = await call_log.finalize(status=status)
    if final is not None:
        outbox.put_nowait(
            {
                "type": "call_summary",
                "call_id": str(final.id),
                "conversation_id": str(final.conversation_id) if final.conversation_id else None,
                "status": final.status,
                "duration_ms": final.duration_ms,
                "voice_cost_usd": str(final.voice_cost_usd),
                "model_cost_usd": str(final.model_cost_usd),
                "turns": len(final.turns or []),
                "recording": bool(final.recording_key),
            }
        )
    outbox.put_nowait(None)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(sender, timeout=5)
    await _close(ws, 1000, "call ended")
