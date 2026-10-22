"""Phone media bridge: a carrier media WebSocket (Twilio Media Streams / Telnyx streaming) ↔ a voice session.

Built from the engine's telephony pieces (``messer.server.telephony`` dialects, ``messer.voice.telephony`` μ-law
codec, resampler and mark-based ``TelephonyPlaybackTracker``): caller audio G.711 μ-law 8 kHz → PCM16 16 kHz into
the session; TTS audio → 8 kHz μ-law ``media`` frames batched to ≥ 20 ms, each followed by a ``mark`` whose echo
is the playback ack; barge-in sends the provider's ``clear``. The session is the platform session
(:mod:`messer_voice.session`) so the agent runs in the runtime with the call's memory and traces.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from messer.server.telephony import Dialect
from messer.voice import AgentTextDone, AudioOutput, FillerSpoken, SessionEnded, TurnMetricsEvent
from messer.voice.telephony import (
    TELEPHONY_SAMPLE_RATE,
    ULAW_SILENCE,
    PcmResampler,
    TelephonyPlaybackTracker,
    ulaw_decode,
    ulaw_encode,
)
from messer_common.logging import get_logger

from .. import calls, tickets
from ..calls import CallLog, CallUnavailable
from ..providers import SAMPLE_RATE, select_pipeline
from ..runner import drive, mark_answered, new_bundle

log = get_logger("messer.voice.telephony")

_ULAW_ENCODINGS = {"audio/x-mulaw", "pcmu"}
_MIN_MEDIA_BYTES = 160  # 20 ms of μ-law at 8 kHz (Telnyx minimum)
_FLUSH_EVENTS = (AgentTextDone, FillerSpoken, TurnMetricsEvent, SessionEnded)


async def _safe_close(ws: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason)


async def read_start(ws: WebSocket, timeout_s: float = 10.0) -> dict[str, Any] | None:
    """Providers send ``connected`` then ``start``; media only flows after it."""
    deadline = time.monotonic() + timeout_s
    try:
        while (remaining := deadline - time.monotonic()) > 0:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=remaining)
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if isinstance(frame, dict) and frame.get("event") == "start":
                return frame
    except (TimeoutError, WebSocketDisconnect, RuntimeError):
        return None
    return None


async def serve_media(ws: WebSocket, dialect: Dialect, *, query_ticket: str | None = None) -> None:
    """One phone call's media stream (the socket must already be accepted)."""
    start = await read_start(ws)
    if start is None:
        log.warning("voice.phone.no_start_frame", provider=dialect.name)
        await _safe_close(ws, 1002, "expected a start frame")
        return
    stream_id = dialect.stream_id(start) or ""
    info = dialect.start_info(start)
    custom = info.get("custom") or {}
    token = str(custom.get("ticket") or query_ticket or "")
    try:
        ticket = await tickets.redeem(token, "telephony")
        if ticket.call_id is None:
            raise tickets.TicketError("ticket without call")
        call = await calls.load_call(ticket.call_id)
        if call.transport != dialect.name:
            raise CallUnavailable("La llamada es de otro proveedor", code="wrong_transport")
        ctx = await calls.call_context(call)
    except tickets.TicketError as exc:
        log.warning("voice.phone.ticket_rejected", provider=dialect.name, reason=str(exc))
        await _safe_close(ws, 1008, "invalid ticket")
        return
    except CallUnavailable as exc:
        log.warning("voice.phone.call_unavailable", provider=dialect.name, code=exc.code)
        await _safe_close(ws, 1008, exc.code)
        return

    encoding = str(info.get("encoding") or "audio/x-mulaw").lower()
    line_rate = int(info.get("sample_rate") or TELEPHONY_SAMPLE_RATE)
    if encoding not in _ULAW_ENCODINGS:
        await calls.fail_call(ctx.call_id, code="unsupported_encoding", message=encoding)
        await _safe_close(ws, 1003, f"unsupported media encoding: {encoding}")
        return
    pipeline = select_pipeline(ctx.residency)
    if pipeline is None:
        await calls.fail_call(ctx.call_id, code="voice_unavailable", message="No hay proveedores de voz configurados")
        await _safe_close(ws, 1011, "voice providers unavailable")
        return
    if info.get("call_id") and not call.external_call_id:
        await calls.update_call(ctx.call_id, external_call_id=str(info["call_id"]))

    send_lock = asyncio.Lock()
    pending_marks: set[str] = set()
    ignored_marks: set[str] = set()
    clear_tasks: set[asyncio.Task[None]] = set()
    out_ulaw = bytearray()
    up_resampler = PcmResampler(line_rate, SAMPLE_RATE) if line_rate != SAMPLE_RATE else None
    down_resampler = PcmResampler(SAMPLE_RATE, TELEPHONY_SAMPLE_RATE)
    sent_ulaw_bytes = 0
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def _send_frame(frame: dict[str, Any]) -> None:
        try:
            async with send_lock:
                await ws.send_json(frame)
        except Exception as exc:
            log.debug("voice.phone.send_skipped", provider=dialect.name, error=str(exc))

    def _on_clear() -> None:
        ignored_marks.update(pending_marks)
        pending_marks.clear()
        out_ulaw.clear()
        down_resampler.reset()
        task = asyncio.get_running_loop().create_task(_send_frame(dialect.clear_frame(stream_id)))
        clear_tasks.add(task)
        task.add_done_callback(clear_tasks.discard)

    tracker = TelephonyPlaybackTracker(bytes_per_second=SAMPLE_RATE * 2, on_clear=_on_clear)
    call_log = CallLog(ctx)
    greeting = str((call.meta or {}).get("greeting") or "") or None
    bundle = new_bundle(ctx, call_log, pipeline=pipeline, playback_tracker=tracker, greeting=greeting)
    bundle.usage.telephony_provider = dialect.name
    session = bundle.session
    started = time.monotonic()

    async def _send_media(payload: bytes) -> None:
        nonlocal sent_ulaw_bytes
        await _send_frame(dialect.media_frame(stream_id, base64.b64encode(payload).decode("ascii")))
        sent_ulaw_bytes += len(payload)
        name = str(sent_ulaw_bytes)
        pending_marks.add(name)
        await _send_frame(dialect.mark_frame(stream_id, name))

    async def _push_downlink(pcm: bytes) -> None:
        out_ulaw.extend(ulaw_encode(down_resampler.process(pcm)))
        if len(out_ulaw) >= _MIN_MEDIA_BYTES:
            payload = bytes(out_ulaw)
            out_ulaw.clear()
            await _send_media(payload)

    async def _flush_downlink() -> None:
        if not out_ulaw:
            return
        payload = bytes(out_ulaw) + ULAW_SILENCE * max(0, _MIN_MEDIA_BYTES - len(out_ulaw))
        out_ulaw.clear()
        await _send_media(payload)

    async def _receiver() -> None:
        try:
            while True:
                msg = await ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                raw = msg.get("text")
                if not raw:
                    continue
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                event = frame.get("event")
                if event == "media":
                    payload = dialect.media_bytes(frame)
                    if payload:
                        pcm = ulaw_decode(payload)
                        if up_resampler is not None:
                            pcm = up_resampler.process(pcm)
                        if pcm:
                            await audio_queue.put(pcm)
                elif event == "mark":
                    name = dialect.mark_name(frame)
                    if not name:
                        continue
                    if name in ignored_marks:
                        ignored_marks.discard(name)
                        continue
                    pending_marks.discard(name)
                    with contextlib.suppress(ValueError):
                        session.playback.on_playback_ack(int(name) / (TELEPHONY_SAMPLE_RATE / 1000))
                elif event == "stop":
                    break
                elif event == "dtmf":
                    log.info("voice.phone.dtmf", provider=dialect.name, digit=dialect.dtmf_digit(frame))
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.warning("voice.phone.receive_failed", provider=dialect.name, error=str(exc))
        finally:
            await audio_queue.put(b"")
            await session.close()

    async def _phone_audio() -> AsyncIterator[bytes]:
        while True:
            chunk = await audio_queue.get()
            if not chunk:
                return
            yield chunk

    async def _on_event(event: Any) -> None:
        if isinstance(event, AudioOutput):
            await _push_downlink(event.data)
        elif isinstance(event, _FLUSH_EVENTS):
            await _flush_downlink()

    await mark_answered(ctx, bundle)
    receiver = asyncio.create_task(_receiver())
    status = await drive(bundle, call_log, _phone_audio(), _on_event)
    receiver.cancel()
    await asyncio.gather(receiver, *clear_tasks, return_exceptions=True)
    bundle.usage.line_seconds = time.monotonic() - started
    await call_log.finalize(status=status)
    await _safe_close(ws, 1000, "call ended")
