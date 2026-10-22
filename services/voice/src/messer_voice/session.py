"""The engine's ``VoiceSession`` wired to the platform: remote agent, provider choice, call behaviour.

``PlatformVoiceSession`` keeps every behaviour of the engine session (end-of-turn detection, barge-in with
heard-text truncation, tool-call fillers, opening greeting, silence check-ins and hang-up, turn timeouts,
per-turn ``TurnMetrics``, call recording) and changes only what assumes an in-process agent:

* the run behind a turn is the runtime run the :class:`~messer_voice.agent.RuntimeAgent` streamed (metrics and
  ``agent_text_done`` carry its id), and metrics are persisted by the call log instead of the in-process trace;
* the lines the session itself says (fillers, check-ins, greeting) are configured text in the call's language —
  the voice service never calls a model outside the runtime gateway.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from messer.voice import VoiceSession
from messer.voice.config import FillerConfig, GreetingConfig, UserIdleConfig
from messer.voice.metrics import TurnMetrics
from messer.voice.playback import PlaybackTracker
from messer.voice.providers import AudioInputConfig, AudioOutputConfig, SpeechToText, TextToSpeech
from messer.voice.turn_detection import resolve_turn_detector
from messer_common.logging import get_logger
from messer_common.settings import get_settings

from .agent import RuntimeAgent
from .config import get_voice_settings
from .context import CallContext
from .metering import MeteredSTT, MeteredTTS
from .phrases import filler_phrases, language_key, phrase, phrases
from .pricing import CallUsage
from .providers import (
    SAMPLE_RATE,
    AudioPipeline,
    BrowserSTT,
    BrowserTTS,
    SpokenPlaybackTracker,
    build_stt,
    build_tts,
)

log = get_logger("messer.voice.session")


class PlatformVoiceSession(VoiceSession):
    """``VoiceSession`` whose agent is a :class:`RuntimeAgent`."""

    agent: Any

    def _runtime_agent(self) -> RuntimeAgent | None:
        return self.agent if isinstance(self.agent, RuntimeAgent) else None

    def _turn_run_id(self) -> str | None:
        agent = self._runtime_agent()
        return agent.current_run_id if agent is not None else None

    def _build_turn_metrics(self, user_text: str, *, interrupted: bool) -> TurnMetrics:
        metrics = super()._build_turn_metrics(user_text, interrupted=interrupted)
        return metrics.model_copy(update={"run_id": self._turn_run_id()})

    def _attach_metrics_to_trace(self, metrics: TurnMetrics) -> None:
        # Persisted by the call log (a "voice" span on the turn's run), not an in-process trace.
        return None

    async def _seed_call_context(self) -> None:
        # Call identity and memory travel with each runtime run (conversation, external user id).
        return None

    def _start_llm_warmup(self) -> None:
        return None

    async def _agent_system_prompt(self) -> str | None:
        return None

    async def _generate_filler(self, tool_name: str | None, previous: list[str] | None = None) -> str | None:
        options = phrases("fillers", self.audio_input.language)
        unsaid = [p for p in options if p not in (previous or [])]
        return (unsaid or options)[0] if options else None

    async def _generate_greeting(self) -> str | None:
        return None

    async def _generate_idle_prompt(self) -> str | None:
        return phrase("idle", self.audio_input.language)

    async def say_and_close(self, text: str, *, timeout_s: float = 20.0) -> None:
        """Stop whatever is in flight, say ``text`` and end the session once it has been heard."""
        if self.closed:
            return
        await self.interrupt(truncate_completed=False)
        try:
            async with asyncio.timeout(timeout_s):
                await self._speak_idle_prompt(text)
                for _ in range(int(timeout_s * 10)):
                    if not self.playback.is_playing or self.closed:
                        break
                    await asyncio.sleep(0.1)
        except TimeoutError:
            log.warning("voice.session.goodbye_timeout", session_id=self.session_id)
        finally:
            await self.close()


@dataclass(slots=True)
class SessionBundle:
    session: PlatformVoiceSession
    agent: RuntimeAgent
    meta: dict[str, Any]
    usage: CallUsage
    browser_stt: BrowserSTT | None = None
    recording_path: Path | None = None
    outbox: list[dict[str, Any]] = field(default_factory=list)


def _greeting(ctx: CallContext, extra_greeting: str | None) -> GreetingConfig | None:
    parts: list[str] = []
    if ctx.record and ctx.transport != "browser":
        # Phone callers hear the notice; browser callers ticked the consent box before starting.
        parts.append(phrase("recording_notice", ctx.language))
    text = (extra_greeting or ctx.greeting or "").strip()
    if text:
        parts.append(text)
    if not parts:
        return None
    return GreetingConfig(text=" ".join(parts), delay_ms=400 if ctx.transport in ("twilio", "telnyx") else 0)


def _user_idle(ctx: CallContext) -> UserIdleConfig:
    s = get_voice_settings()
    phone = ctx.transport in ("twilio", "telnyx")
    return UserIdleConfig(
        timeout_secs=s.messer_voice_idle_secs,
        text=phrases("idle", ctx.language),
        max_count=2,
        hangup_after_secs=s.messer_voice_phone_idle_hangup_secs if phone else s.messer_voice_idle_hangup_secs,
    )


def _recording_path(ctx: CallContext) -> Path:
    base = get_settings().resolve_path(get_voice_settings().messer_voice_recording_dir)
    return base / f"{ctx.session_id}.mp3"


def build_session(
    ctx: CallContext,
    *,
    pipeline: AudioPipeline | None,
    agent: RuntimeAgent,
    playback_tracker: PlaybackTracker | None = None,
    on_text_segment: Callable[[dict[str, Any]], None] | None = None,
    greeting: str | None = None,
    on_recording_saved: Any = None,
) -> SessionBundle:
    """Build the session for a call: hosted audio (``pipeline``) or browser text mode (``pipeline=None``)."""
    s = get_voice_settings()
    usage = CallUsage(direction=ctx.direction)
    stt: SpeechToText
    tts: TextToSpeech
    browser_stt: BrowserSTT | None = None
    language = language_key(ctx.language)
    if pipeline is not None:
        raw_stt, audio_in = build_stt(pipeline.stt, language=ctx.language)
        raw_tts, audio_out = build_tts(pipeline.tts, language=ctx.language, voice=ctx.voice)
        usage.stt, usage.tts = pipeline.stt, pipeline.tts
        stt = MeteredSTT(raw_stt, usage)
        tts = MeteredTTS(raw_tts, usage)
        native = bool(raw_stt.native_eou)
        detector = "provider" if native else s.messer_voice_turn_detector
        vad_endpointing: bool | None = None if detector == "local" else False
    else:
        browser_stt = BrowserSTT()
        stt = browser_stt
        segment_sink = on_text_segment or (lambda _payload: None)
        tts = BrowserTTS(on_segment=segment_sink)
        audio_in = AudioInputConfig(language=language, sample_rate=SAMPLE_RATE)
        audio_out = AudioOutputConfig(sample_rate=SAMPLE_RATE)
        if playback_tracker is None:
            playback_tracker = SpokenPlaybackTracker(bytes_per_second=SAMPLE_RATE * 2)
        detector = "provider"
        vad_endpointing = False

    try:
        turn_detector = resolve_turn_detector(detector)
    except (TypeError, ValueError, ImportError) as exc:
        log.warning("voice.session.turn_detector_fallback", requested=detector, error=str(exc))
        turn_detector = resolve_turn_detector("lexical")

    recorder = None
    recording_path: Path | None = None
    if ctx.record and pipeline is not None:
        try:
            from messer.voice.recording import CallRecorder

            recording_path = _recording_path(ctx)
            recorder = CallRecorder(
                recording_path,
                sample_rate=SAMPLE_RATE,
                layout="mixed",
                bitrate_kbps=32,
                on_saved=on_recording_saved,
                meta={
                    "org_id": str(ctx.org_id),
                    "project_id": str(ctx.project_id),
                    "call_id": str(ctx.call_id),
                    "workforce": ctx.workforce,
                },
            )
        except Exception as exc:  # a broken recorder must never take the call down
            log.error("voice.session.recorder_unavailable", error=str(exc))
            recorder = None
            recording_path = None

    session = PlatformVoiceSession(
        agent=agent,  # type: ignore[arg-type]  # duck-typed remote agent
        stt=stt,
        tts=tts,
        audio_input=audio_in,
        audio_output=audio_out,
        turn_detector=turn_detector,
        playback_tracker=playback_tracker,
        recorder=recorder,
        session_id=ctx.session_id,
        turn_timeout_secs=s.messer_voice_turn_timeout_secs,
        turn_timeout_fallback=phrase("timeout_fallback", ctx.language),
        vad_endpointing=vad_endpointing,
        filler=FillerConfig(enabled=True, phrases=filler_phrases(), delay_secs=s.messer_voice_filler_delay_secs),
        greeting=_greeting(ctx, greeting),
        user_idle=_user_idle(ctx),
    )
    meta: dict[str, Any] = {
        "session_id": ctx.session_id,
        "call_id": str(ctx.call_id),
        "conversation_id": str(ctx.conversation_id) if ctx.conversation_id else None,
        "mode": ctx.mode,
        "transport": ctx.transport,
        "language": language,
        "stt_provider": pipeline.stt.provider if pipeline else "browser",
        "stt_model": pipeline.stt.model if pipeline else None,
        "tts_provider": pipeline.tts.provider if pipeline else "browser",
        "tts_model": pipeline.tts.model if pipeline else None,
        "voice": ctx.voice or None,
        "turn_detector": type(session.turn_detector).__name__,
        "sample_rate": SAMPLE_RATE,
        "recording": recorder is not None,
        "max_call_secs": s.messer_voice_max_call_secs,
        "workforce": ctx.workforce,
        "environment": ctx.environment,
    }
    session.recording_meta = dict(meta)
    return SessionBundle(
        session=session,
        agent=agent,
        meta=meta,
        usage=usage,
        browser_stt=browser_stt,
        recording_path=recording_path,
    )
