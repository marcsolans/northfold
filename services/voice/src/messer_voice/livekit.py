"""LiveKit rooms: the agent joins a room as a participant and talks with whoever publishes a microphone there.

The API creates the call and the caller's room token (``POST /api/v1/voice/livekit/sessions``) and asks this
service to join (``POST /internal/v1/livekit/join``). The agent publishes a server-paced audio track (the engine's
``LkPacedSource``, so barge-in truncation is exact without playback acks) and sends the session events as JSON on
the data channel (topic ``messer.voice.events``, the same payloads as the WebSocket protocol). Requires
``LIVEKIT_URL`` / ``LIVEKIT_API_KEY`` / ``LIVEKIT_API_SECRET`` and hosted STT/TTS.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import jwt

from messer.server.livekit_session import chunk_data_payloads
from messer.server.voice import event_to_payloads
from messer.voice import AudioOutput, VoiceUsageEvent
from messer_common.logging import get_logger
from messer_common.settings import get_settings

from . import calls
from .calls import CallLog, CallUnavailable
from .context import CallContext
from .providers import SAMPLE_RATE, select_pipeline
from .runner import drive, mark_answered, new_bundle
from .status import livekit_configured

log = get_logger("messer.voice.livekit")

EVENTS_TOPIC = "messer.voice.events"
JOIN_TIMEOUT_S = 20.0
CALLER_WAIT_S = 120.0
_ROOMS: dict[str, asyncio.Task[None]] = {}


class LivekitError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


def room_name(call_id: uuid.UUID) -> str:
    return f"messer-{call_id.hex}"


def access_token(identity: str, room: str, *, name: str, ttl_s: int = 3600, agent: bool = False) -> str:
    """LiveKit access token (HS256 JWT signed with the API secret, video grant for one room)."""
    s = get_settings()
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": s.livekit_api_key,
        "sub": identity,
        "name": name,
        "nbf": now - 5,
        "exp": now + ttl_s,
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
        "metadata": json.dumps({"messer": {"role": "agent" if agent else "caller"}}),
    }
    if agent:
        claims["kind"] = "agent"
    return jwt.encode(claims, s.livekit_api_secret, algorithm="HS256")


async def join(call_id: uuid.UUID) -> dict[str, Any]:
    if not livekit_configured():
        raise LivekitError("LiveKit no está configurado", status=503)
    try:
        call = await calls.load_call(call_id)
        if call.transport != "livekit":
            raise CallUnavailable("La llamada no es de LiveKit", code="wrong_transport")
        ctx = await calls.call_context(call)
    except CallUnavailable as exc:
        raise LivekitError(str(exc), status=409) from exc
    if select_pipeline(ctx.residency) is None:
        raise LivekitError("No hay proveedores de voz configurados", status=409)
    room = room_name(call_id)
    live = _ROOMS.get(room)
    if live is not None and not live.done():
        raise LivekitError("El agente ya está en la sala", status=409)
    joined: asyncio.Future[None] = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(_run_room(ctx, room, joined), name=f"voice-livekit-{room}")
    _ROOMS[room] = task
    task.add_done_callback(lambda finished: _ROOMS.pop(room, None) if _ROOMS.get(room) is finished else None)
    try:
        await asyncio.wait_for(asyncio.shield(joined), timeout=JOIN_TIMEOUT_S)
    except TimeoutError as exc:
        task.cancel()
        raise LivekitError("El agente no ha podido entrar en la sala a tiempo", status=504) from exc
    except Exception as exc:
        raise LivekitError(f"El agente no ha podido entrar en la sala: {exc}") from exc
    return {"room": room, "status": "joined"}


async def shutdown() -> None:
    for task in list(_ROOMS.values()):
        task.cancel()
    if _ROOMS:
        await asyncio.gather(*_ROOMS.values(), return_exceptions=True)


async def _run_room(ctx: CallContext, room: str, joined: asyncio.Future[None]) -> None:
    from livekit import rtc

    from messer.voice.livekit import LkPacedSource, audio_stream_to_pcm

    s = get_settings()
    lk_room = rtc.Room()
    mic_tracks: asyncio.Queue[Any] = asyncio.Queue()
    caller_ready = asyncio.Event()
    caller: dict[str, str] = {}
    holder: dict[str, Any] = {}
    send_q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    background: set[asyncio.Task[None]] = set()

    def _on_track(track: Any, _pub: Any, participant: Any) -> None:
        if getattr(track, "kind", None) != getattr(rtc.TrackKind, "KIND_AUDIO", 1):
            return
        identity = str(getattr(participant, "identity", "") or "")
        if caller and caller.get("identity") != identity:
            return
        caller["identity"] = identity
        mic_tracks.put_nowait(track)
        caller_ready.set()

    def _on_left(participant: Any) -> None:
        if caller.get("identity") == str(getattr(participant, "identity", "") or ""):
            bundle = holder.get("bundle")
            if bundle is not None:
                task = asyncio.create_task(bundle.session.close())
                background.add(task)
                task.add_done_callback(background.discard)

    def _on_data(packet: Any) -> None:
        bundle = holder.get("bundle")
        if bundle is None:
            return
        with contextlib.suppress(ValueError, TypeError, KeyError):
            data = json.loads(bytes(packet.data))
            if isinstance(data, dict) and data.get("type") == "playback":
                bundle.session.playback.on_playback_ack(float(data["played_ms"]))

    lk_room.on("track_subscribed", _on_track)
    lk_room.on("participant_disconnected", _on_left)
    lk_room.on("data_received", _on_data)

    async def _sender() -> None:
        while True:
            payload = await send_q.get()
            if payload is None:
                return
            with contextlib.suppress(Exception):
                await lk_room.local_participant.publish_data(
                    json.dumps(payload, default=str).encode(), reliable=True, topic=EVENTS_TOPIC
                )

    sender = asyncio.create_task(_sender())
    downlink: Any = None
    call_log = CallLog(ctx)
    try:
        token = access_token(f"agent-{ctx.call_id.hex}", room, name=ctx.workforce, agent=True)
        await lk_room.connect(s.livekit_url, token)
        if not joined.done():
            joined.set_result(None)
        try:
            await asyncio.wait_for(caller_ready.wait(), timeout=CALLER_WAIT_S)
        except TimeoutError:
            await calls.fail_call(ctx.call_id, code="no_caller", message="Nadie entró en la sala", status="no_answer")
            return
        pipeline = select_pipeline(ctx.residency)
        if pipeline is None:
            await calls.fail_call(ctx.call_id, code="voice_unavailable", message="No hay proveedores de voz")
            return
        downlink = LkPacedSource(sample_rate=SAMPLE_RATE)
        bundle = new_bundle(ctx, call_log, pipeline=pipeline, playback_tracker=downlink.tracker)
        bundle.usage.telephony_provider = "livekit"
        holder["bundle"] = bundle
        session = bundle.session
        meta = {"playback_acks": "native", **bundle.meta}
        track = rtc.LocalAudioTrack.create_audio_track("agent", downlink.source)
        await lk_room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        await downlink.start()

        async def _mic() -> AsyncIterator[bytes]:
            while True:
                remote = await mic_tracks.get()
                stream = rtc.AudioStream(remote, sample_rate=SAMPLE_RATE, num_channels=1)
                async for chunk in audio_stream_to_pcm(stream):
                    yield chunk

        async def _on_event(event: Any) -> None:
            if isinstance(event, AudioOutput):
                downlink.write(event.data)
                return
            if isinstance(event, VoiceUsageEvent):
                return
            for payload in chunk_data_payloads(event_to_payloads(event, session, meta)):
                send_q.put_nowait(payload)

        await mark_answered(ctx, bundle)
        started = time.monotonic()
        status = await drive(bundle, call_log, _mic(), _on_event)
        bundle.usage.line_seconds = time.monotonic() - started
        await call_log.finalize(status=status)
    except Exception as exc:
        if not joined.done():
            joined.set_exception(exc)
        log.exception("voice.livekit.room_failed", room=room)
        await calls.fail_call(ctx.call_id, code="livekit_failed", message=str(exc)[:300])
    finally:
        send_q.put_nowait(None)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(sender, timeout=5)
        if downlink is not None:
            with contextlib.suppress(BaseException):
                await asyncio.wait_for(downlink.aclose(), timeout=5)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(lk_room.disconnect(), timeout=5)
