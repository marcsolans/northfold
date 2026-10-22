"""Lines the voice gateway itself says on a call (not the agent): fillers, check-ins, notices, apologies.

Keyed by language (``es`` first, ``en`` second); any other language falls back to Spanish, the product
language. The agent's own words always come from the agent.
"""

from __future__ import annotations

from typing import Literal

PhraseKey = Literal[
    "fillers",
    "idle",
    "timeout_fallback",
    "turn_failed",
    "recording_notice",
    "max_duration",
    "not_available",
]

_PHRASES: dict[str, dict[str, list[str]]] = {
    "es": {
        "fillers": ["Un momento, lo compruebo.", "Déjame mirarlo.", "Dame un segundo.", "Lo consulto ahora mismo."],
        "idle": ["¿Sigues ahí?", "¿Puedo ayudarte en algo más?"],
        "timeout_fallback": ["Perdona, se me ha cortado. ¿Puedes repetirlo?"],
        "turn_failed": ["Lo siento, ahora mismo no puedo responder. Inténtalo de nuevo en unos segundos."],
        "recording_notice": ["Te informamos de que esta llamada se graba."],
        "max_duration": ["Hemos llegado a la duración máxima de la llamada. Gracias por llamar, hasta pronto."],
        "not_available": ["Este asistente no está disponible en este momento. Inténtalo más tarde."],
    },
    "en": {
        "fillers": ["One moment, let me check.", "Let me look that up.", "Give me a second.", "Checking that now."],
        "idle": ["Are you still there?", "Is there anything else I can help with?"],
        "timeout_fallback": ["Sorry, I lost that for a moment. Could you say it again?"],
        "turn_failed": ["Sorry, I can't answer right now. Please try again in a few seconds."],
        "recording_notice": ["Please note that this call is being recorded."],
        "max_duration": ["We've reached the maximum call length. Thanks for calling, goodbye."],
        "not_available": ["This assistant isn't available right now. Please try again later."],
    },
}


def language_key(language: str | None) -> str:
    key = (language or "").strip().lower().replace("_", "-").split("-")[0]
    return key if key in _PHRASES else "es"


def phrases(key: PhraseKey, language: str | None) -> list[str]:
    return list(_PHRASES[language_key(language)][key])


def phrase(key: PhraseKey, language: str | None) -> str:
    return _PHRASES[language_key(language)][key][0]


def filler_phrases() -> dict[str, list[str]]:
    """``FillerConfig.phrases`` (per language, ``*`` → Spanish)."""
    table = {lang: list(values["fillers"]) for lang, values in _PHRASES.items()}
    table["*"] = list(_PHRASES["es"]["fillers"])
    return table
