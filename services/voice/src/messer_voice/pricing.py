"""Speech providers and voice prices from ``config/models.yaml`` (``voice:`` section) and call costing.

STT is priced per audio minute streamed to the provider, TTS per 1,000 characters synthesized and telephony per
call minute (by provider and direction). Browser speech (demo mode) costs nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from messer_common.models_config import load_models_config

SpeechKind = Literal["stt", "tts"]
_SIX = Decimal("0.000001")


def _dec(value: Any) -> Decimal:
    return Decimal(str(value if value is not None else 0))


@dataclass(frozen=True, slots=True)
class SpeechOption:
    kind: SpeechKind
    provider: str
    model: str
    price: Decimal  # USD per minute (stt) or per 1,000 characters (tts)
    eu_host: str | None = None
    voices: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}"


def _voice_config() -> dict[str, Any]:
    raw = load_models_config().get("voice") or {}
    return raw if isinstance(raw, dict) else {}


def speech_options(kind: SpeechKind) -> list[SpeechOption]:
    out: list[SpeechOption] = []
    for item in _voice_config().get(kind) or []:
        if not isinstance(item, dict) or not item.get("provider"):
            continue
        out.append(
            SpeechOption(
                kind=kind,
                provider=str(item["provider"]),
                model=str(item.get("model") or ""),
                price=_dec(item.get("per_minute") if kind == "stt" else item.get("per_1k_chars")),
                eu_host=str(item["eu_host"]) if item.get("eu_host") else None,
                voices={str(k): str(v) for k, v in (item.get("voices") or {}).items()},
            )
        )
    return out


def telephony_rate(provider: str, direction: str) -> Decimal:
    table = (_voice_config().get("telephony") or {}).get(provider) or {}
    key = "outbound_per_minute" if direction == "outbound" else "inbound_per_minute"
    return _dec(table.get(key))


@dataclass(slots=True)
class CallUsage:
    """Speech and line usage of one call, accumulated by the session while it runs."""

    stt: SpeechOption | None = None
    tts: SpeechOption | None = None
    stt_seconds: float = 0.0
    tts_characters: int = 0
    telephony_provider: str | None = None
    direction: str = "inbound"
    line_seconds: float = 0.0
    provider_events: list[dict[str, Any]] = field(default_factory=list)

    def add_stt_audio(self, num_bytes: int, sample_rate: int) -> None:
        if self.stt is not None and sample_rate > 0:
            self.stt_seconds += num_bytes / (2 * sample_rate)

    def add_tts_text(self, text: str) -> None:
        if self.tts is not None:
            self.tts_characters += len(text)

    def costs(self) -> dict[str, Decimal]:
        stt = (Decimal(str(self.stt_seconds)) / 60 * self.stt.price) if self.stt else Decimal("0")
        tts = (Decimal(self.tts_characters) / 1000 * self.tts.price) if self.tts else Decimal("0")
        line = (
            Decimal(str(self.line_seconds)) / 60 * telephony_rate(self.telephony_provider, self.direction)
            if self.telephony_provider
            else Decimal("0")
        )
        parts = {"stt": stt, "tts": tts, "telephony": line}
        parts = {k: v.quantize(_SIX, rounding=ROUND_HALF_UP) for k, v in parts.items()}
        parts["total"] = sum(parts.values(), Decimal("0"))
        return parts

    def as_dict(self) -> dict[str, Any]:
        costs = self.costs()
        return {
            "stt": {
                "provider": self.stt.provider if self.stt else "browser",
                "model": self.stt.model if self.stt else None,
                "seconds": round(self.stt_seconds, 2),
                "cost_usd": str(costs["stt"]),
            },
            "tts": {
                "provider": self.tts.provider if self.tts else "browser",
                "model": self.tts.model if self.tts else None,
                "characters": self.tts_characters,
                "cost_usd": str(costs["tts"]),
            },
            "telephony": {
                "provider": self.telephony_provider,
                "direction": self.direction,
                "seconds": round(self.line_seconds, 2),
                "cost_usd": str(costs["telephony"]),
            },
            "total_usd": str(costs["total"]),
            # Raw provider counters (engine VoiceUsageEvent) for reconciliation.
            "provider_events": self.provider_events[-200:],
        }
