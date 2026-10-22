"""Speech providers for a call: hosted STT/TTS from the engine's voice module, or the browser (demo mode).

Audio mode needs both a speech-to-text and a text-to-speech provider with a configured key (first match in
``config/models.yaml`` → ``voice.stt`` / ``voice.tts``) that the organization's residency allows. Otherwise the
call runs in **text mode**: the browser transcribes (Web Speech API) and speaks (``speechSynthesis``), and the
session exchanges text with it over the same protocol — the engine's ``VoiceSession`` still drives turn taking,
barge-in, fillers, the greeting and check-ins through :class:`BrowserSTT` / :class:`BrowserTTS`.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from messer.voice.config import DEFAULT_VOICE_ID, VoiceConfig
from messer.voice.playback import BufferedPlaybackTracker
from messer.voice.providers import (
    AudioInputConfig,
    AudioOutputConfig,
    SpeechToText,
    TextToSpeech,
    TranscriptEvent,
    resolve_tts,
)
from messer_common.residency import Residency, allowed_provider, is_eu_region
from messer_common.settings import get_settings

from .phrases import language_key
from .pricing import SpeechOption, speech_options

SAMPLE_RATE = 16_000


def provider_key(provider: str) -> str:
    s = get_settings()
    return {
        "deepgram": s.deepgram_api_key,
        "elevenlabs": s.elevenlabs_api_key,
        "openai": s.openai_api_key,
    }.get(provider, "")


@dataclass(frozen=True, slots=True)
class AudioPipeline:
    stt: SpeechOption
    tts: SpeechOption


def first_available(options: list[SpeechOption], residency: Residency | None) -> SpeechOption | None:
    for option in options:
        if not provider_key(option.provider):
            continue
        if residency is not None and not allowed_provider(residency, "voice", option.provider):
            continue
        return option
    return None


def select_pipeline(residency: Residency | None) -> AudioPipeline | None:
    """Hosted STT + TTS for audio mode, or ``None`` (text mode in the browser)."""
    stt = first_available(speech_options("stt"), residency)
    tts = first_available(speech_options("tts"), residency)
    if stt is None or tts is None:
        return None
    return AudioPipeline(stt=stt, tts=tts)


def _eu() -> bool:
    return is_eu_region(get_settings().messer_voice_region)


def build_stt(option: SpeechOption, *, language: str | None) -> tuple[SpeechToText, AudioInputConfig]:
    from messer.voice.deepgram import effective_stt_model, resolve_stt

    extra: dict[str, Any] = {}
    if option.provider == "elevenlabs":
        extra.update(VoiceConfig().stt_extra)  # Scribe VAD commit tuning (engine defaults)
    if _eu() and option.eu_host:
        extra["stt_host"] = option.eu_host
    stt = resolve_stt(option.provider, model=option.model, api_key=provider_key(option.provider))
    config = AudioInputConfig(
        model=effective_stt_model(stt, option.model),
        language=language_key(language),
        sample_rate=SAMPLE_RATE,
        extra=extra,
    )
    return stt, config


def resolve_voice(option: SpeechOption, *, language: str | None, voice: str | None) -> str:
    """The voice id for ``option``: the agent's ``provider:voice`` choice when it targets this provider, else the
    configured default for the language."""
    raw = (voice or "").strip()
    if ":" in raw:
        provider, _, value = raw.partition(":")
        if provider == option.provider and value.strip():
            return value.strip()
    lang = language_key(language)
    default = option.voices.get(lang) or option.voices.get("es") or ""
    if not default and option.provider == "elevenlabs":
        default = DEFAULT_VOICE_ID
    return default


def build_tts(
    option: SpeechOption, *, language: str | None, voice: str | None
) -> tuple[TextToSpeech, AudioOutputConfig]:
    extra: dict[str, Any] = {}
    if option.provider == "elevenlabs":
        extra["auto_mode"] = True
    if _eu() and option.eu_host:
        extra["tts_host"] = option.eu_host
    tts = resolve_tts(option.provider, api_key=provider_key(option.provider))
    voice_id = resolve_voice(option, language=language, voice=voice)
    model: str | None = option.model or None
    if option.provider == "deepgram":
        model = voice_id or None  # Aura ids carry model, voice and language
    config = AudioOutputConfig(model=model, voice=voice_id or None, sample_rate=SAMPLE_RATE, extra=extra)
    return tts, config


# ----------------------------------------------------------------------------------------- text mode


class BrowserSTT(SpeechToText):
    """Text-mode STT: the browser transcribes and sends ``user_text`` frames.

    Final frames are turn boundaries (``native_eou``), interim frames are partials — the session's provider turn
    detector uses them for captions and barge-in, exactly like a hosted STT's partials.
    """

    native_eou = True

    def __init__(self) -> None:
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._closed = False

    async def connect(self, config: AudioInputConfig) -> None:
        return None

    async def push_audio(self, chunk: bytes) -> None:
        return None

    async def commit(self) -> None:
        return None

    def feed(self, text: str, *, final: bool) -> None:
        text = (text or "").strip()
        if self._closed or not text:
            return
        self._queue.put_nowait(TranscriptEvent(type="committed" if final else "partial", text=text))

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)


class BrowserTTS(TextToSpeech):
    """Text-mode TTS: each segment the session would synthesize is sent to the browser to speak.

    The segment is paced with silent PCM of its estimated speaking time, so the session's playback tracker,
    barge-in truncation and user-idle clock behave as with real audio. The browser acknowledges playback in the
    same unit (milliseconds of those segments actually spoken).
    """

    provider_id = "browser"
    CHARS_PER_SECOND = 14.0
    BASE_MS = 250
    CHUNK_MS = 250

    def __init__(self, on_segment: Callable[[dict[str, Any]], None]) -> None:
        self._on_segment = on_segment
        self._rate = SAMPLE_RATE
        self._segments = 0

    @classmethod
    def estimate_ms(cls, text: str) -> int:
        return int(cls.BASE_MS + 1000 * len(text) / cls.CHARS_PER_SECOND)

    async def connect(self, config: AudioOutputConfig) -> None:
        self._rate = config.sample_rate

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        text = text.strip()
        if not text:
            return
        self._segments += 1
        duration_ms = self.estimate_ms(text)
        self._on_segment({"type": "speak", "segment": self._segments, "text": text, "duration_ms": duration_ms})
        remaining = int(self._rate * duration_ms / 1000) * 2
        chunk = int(self._rate * self.CHUNK_MS / 1000) * 2
        while remaining > 0:
            size = min(chunk, remaining)
            remaining -= size
            yield bytes(size)

    async def close(self) -> None:
        return None


class SpokenPlaybackTracker(BufferedPlaybackTracker):
    """Text-mode playback position: the browser's speech synthesis is the clock.

    The schedule of the silent PCM is only an estimate of how long the browser takes to say each segment, so
    the client's word wins both ways: ``speech_done`` (its queue drained) ends playback at once, and acks that
    keep advancing after the estimated end keep the assistant audible for barge-in and the idle clock.
    """

    STILL_SPEAKING_S = 0.5

    def on_playback_ack(self, played_ms: float) -> None:
        previous = self._last_ack[0] if self._last_ack is not None else -1
        super().on_playback_ack(played_ms)
        ack_bytes = max(0, int(played_ms / 1000 * self._bps))
        now = self._clock()
        if ack_bytes > previous and self._playing_until <= now and ack_bytes < self._scheduled_bytes:
            self._playing_until = now + self.STILL_SPEAKING_S

    def on_speech_done(self) -> None:
        self._playing_until = min(self._playing_until, self._clock())
