"""Drive one voice session to the end, whatever the transport: events out, call log, maximum call duration."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, Awaitable, Callable
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any, cast

from messer.voice import SessionError
from messer_common.logging import get_logger

from . import calls
from .agent import RuntimeAgent
from .calls import CallLog
from .config import get_voice_settings
from .context import CallContext
from .phrases import phrase
from .providers import AudioPipeline
from .session import SessionBundle, build_session

log = get_logger("messer.voice.runner")

# Live sessions of this process, by call id (diagnostics and graceful shutdown).
ACTIVE: dict[str, SessionBundle] = {}


def new_bundle(
    ctx: CallContext,
    call_log: CallLog,
    *,
    pipeline: AudioPipeline | None,
    playback_tracker: Any = None,
    on_text_segment: Callable[[dict[str, Any]], None] | None = None,
    greeting: str | None = None,
) -> SessionBundle:
    agent = RuntimeAgent(ctx, on_turn_finished=call_log.on_turn_finished)
    bundle = build_session(
        ctx,
        pipeline=pipeline,
        agent=agent,
        playback_tracker=playback_tracker,
        on_text_segment=on_text_segment,
        greeting=greeting,
        on_recording_saved=call_log.on_recording_saved,
    )
    call_log.attach(bundle)
    return bundle


async def mark_answered(ctx: CallContext, bundle: SessionBundle) -> None:
    now = datetime.now(UTC)
    call = await calls.load_call(ctx.call_id)
    await calls.update_call(
        ctx.call_id,
        status="active",
        started_at=call.started_at or now,
        answered_at=now,
        mode=ctx.mode,
        stt_provider=str(bundle.meta.get("stt_provider") or "") or None,
        tts_provider=str(bundle.meta.get("tts_provider") or "") or None,
        meta={**(call.meta or {}), "session": {k: v for k, v in bundle.meta.items() if k != "conversation_id"}},
    )


async def drive(
    bundle: SessionBundle,
    call_log: CallLog,
    audio_in: AsyncIterable[bytes],
    on_event: Callable[[Any], Awaitable[None]],
) -> str:
    """Run the session until it ends. Returns the call's final status (``completed`` | ``failed``)."""
    session = bundle.session
    key = str(call_log.ctx.call_id)
    ACTIVE[key] = bundle
    max_secs = get_voice_settings().messer_voice_max_call_secs

    async def _max_duration() -> None:
        await asyncio.sleep(max_secs)
        log.info("voice.call.max_duration", call_id=key, seconds=max_secs)
        await session.say_and_close(phrase("max_duration", call_log.ctx.language))

    watchdog = asyncio.create_task(_max_duration(), name=f"voice-max-duration-{key}")
    status = "completed"
    try:
        async with aclosing(cast(AsyncGenerator[Any, None], session.run(audio_in))) as events:
            async for event in events:
                if isinstance(event, SessionError):
                    call_log.note_error(event.message)
                await call_log.on_event(event)
                await on_event(event)
    except Exception as exc:
        status = "failed"
        call_log.note_error(str(exc))
        log.exception("voice.call.session_failed", call_id=key)
    finally:
        watchdog.cancel()
        await asyncio.gather(watchdog, return_exceptions=True)
        try:
            await session.close()
        except Exception as exc:
            log.debug("voice.call.close_suppressed", error=str(exc))
        ACTIVE.pop(key, None)
    return status
