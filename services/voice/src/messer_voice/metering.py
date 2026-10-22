"""Usage metering wrappers around the engine's STT/TTS providers.

They count what is actually sent to the provider — audio seconds streamed to STT, characters fed to TTS — which
is what both providers bill, and delegate everything else (including the engine's usage listeners).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from messer.voice.events import VoiceUsageEvent
from messer.voice.providers import (
    AudioInputConfig,
    AudioOutputConfig,
    SpeechToText,
    TextToSpeech,
    TranscriptEvent,
    TTSStream,
)

from .pricing import CallUsage


class MeteredSTT(SpeechToText):
    def __init__(self, inner: SpeechToText, usage: CallUsage) -> None:
        self.inner = inner
        self.usage = usage
        self.native_eou = inner.native_eou
        self._sample_rate = 16_000

    async def connect(self, config: AudioInputConfig) -> None:
        self._sample_rate = config.sample_rate
        await self.inner.connect(config)

    async def push_audio(self, chunk: bytes) -> None:
        self.usage.add_stt_audio(len(chunk), self._sample_rate)
        await self.inner.push_audio(chunk)

    async def commit(self) -> None:
        await self.inner.commit()

    def events(self) -> AsyncIterator[TranscriptEvent]:
        return self.inner.events()

    async def close(self) -> None:
        await self.inner.close()

    def add_usage_listener(self, listener: Callable[[VoiceUsageEvent], None]) -> None:
        self.inner.add_usage_listener(listener)

    def remove_usage_listener(self, listener: Callable[[VoiceUsageEvent], None]) -> None:
        self.inner.remove_usage_listener(listener)


class _MeteredStream(TTSStream):
    def __init__(self, inner: TTSStream, usage: CallUsage) -> None:
        self.inner = inner
        self.usage = usage

    async def feed(self, text: str) -> None:
        self.usage.add_tts_text(text)
        await self.inner.feed(text)

    async def end(self) -> None:
        await self.inner.end()

    async def abort(self) -> None:
        await self.inner.abort()

    def audio(self) -> AsyncIterator[bytes]:
        return self.inner.audio()


class MeteredTTS(TextToSpeech):
    def __init__(self, inner: TextToSpeech, usage: CallUsage) -> None:
        self.inner = inner
        self.usage = usage
        self.provider_id = inner.provider_id

    async def connect(self, config: AudioOutputConfig) -> None:
        await self.inner.connect(config)

    def synthesize(self, text: str) -> AsyncIterator[bytes]:
        self.usage.add_tts_text(text)
        return self.inner.synthesize(text)

    def open_stream(self) -> TTSStream | None:
        stream = self.inner.open_stream()
        return _MeteredStream(stream, self.usage) if stream is not None else None

    async def close(self) -> None:
        await self.inner.close()

    def add_usage_listener(self, listener: Callable[[VoiceUsageEvent], None]) -> None:
        self.inner.add_usage_listener(listener)

    def remove_usage_listener(self, listener: Callable[[VoiceUsageEvent], None]) -> None:
        self.inner.remove_usage_listener(listener)
