"""Dictation (speech-to-text only) for the Composer microphone: ``WS /v1/transcribe?ticket=…``.

Ticket from ``POST /api/v1/voice/transcriptions``. Up: binary PCM16 mono 16 kHz, then ``{"type": "stop"}``.
Down: ``transcript_partial`` / ``transcript_committed`` with ``text`` and a final ``{"type": "done", "text"}``.
The audio seconds are priced like call STT and charged to the organization's credits. Without a hosted STT the
API tells the browser to use the Web Speech API instead, and this endpoint refuses (``4409``).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from decimal import Decimal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from messer_common import credits
from messer_common.db import system_session
from messer_common.logging import get_logger
from messer_common.pricing import usd_to_credits
from messer_common.residency import org_residency

from . import tickets
from .metering import MeteredSTT
from .pricing import CallUsage, speech_options
from .providers import build_stt, first_available

log = get_logger("messer.voice.transcribe")
router = APIRouter()

MAX_SECONDS = 300
FINAL_WAIT_S = 2.5


async def _close(ws: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(Exception):
        await ws.close(code=code, reason=reason)


@router.websocket("/v1/transcribe")
async def transcribe(ws: WebSocket) -> None:
    await ws.accept()
    try:
        ticket = await tickets.redeem(ws.query_params.get("ticket", ""), "transcribe")
    except tickets.TicketError:
        await _close(ws, 4401, "invalid ticket")
        return
    org_id = ticket.org_id
    if org_id is None:
        await _close(ws, 4401, "invalid ticket")
        return
    async with system_session() as s:
        residency = await org_residency(s, org_id)
    option = first_available(speech_options("stt"), residency)
    if option is None:
        await _close(ws, 4409, "browser_stt")
        return
    usage = CallUsage(stt=option)
    raw_stt, config = build_stt(option, language=str(ticket.claims.get("language") or "es"))
    stt = MeteredSTT(raw_stt, usage)
    committed: list[str] = []
    last_partial = ""
    stopped = asyncio.Event()
    settled = asyncio.Event()

    async def _events() -> None:
        nonlocal last_partial
        async for event in stt.events():
            if event.type == "partial":
                last_partial = event.text
                await ws.send_json({"type": "transcript_partial", "text": event.text})
            elif event.type == "committed" and event.text.strip():
                committed.append(event.text.strip())
                last_partial = ""
                settled.set()
                await ws.send_json({"type": "transcript_committed", "text": event.text.strip()})
            elif event.type == "error":
                await ws.send_json({"type": "error", "message": event.text})

    reader: asyncio.Task[None] | None = None
    try:
        await stt.connect(config)
        reader = asyncio.create_task(_events())
        await ws.send_json({"type": "ready", "provider": option.provider, "model": option.model})
        while not stopped.is_set():
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                if usage.stt_seconds > MAX_SECONDS:
                    break
                await stt.push_audio(data)
                continue
            raw = msg.get("text")
            if raw:
                with contextlib.suppress(ValueError):
                    if json.loads(raw).get("type") == "stop":
                        stopped.set()
        settled.clear()
        await stt.commit()
        if last_partial.strip():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(settled.wait(), timeout=FINAL_WAIT_S)
        if last_partial.strip():
            committed.append(last_partial.strip())
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "done", "text": " ".join(committed).strip()})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("voice.transcribe.failed", error=str(exc))
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": "transcription_failed"})
    finally:
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        with contextlib.suppress(Exception):
            await stt.close()
        cost = usage.costs()["total"]
        if cost > Decimal("0"):
            async with system_session() as s:
                await credits.charge_usage(
                    s,
                    org_id=org_id,
                    run_id=uuid.uuid4(),
                    project_id=None,
                    cost_usd=cost,
                    credits=usd_to_credits(cost),
                    note=f"voz · dictado · {option.provider}",
                )
        await _close(ws, 1000, "done")
