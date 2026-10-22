"""Messages the platform itself sends on a channel (not written by the agent), per channel locale.

Builders can override them per channel with the ``approval_message`` and ``error_message`` config keys.
"""

from __future__ import annotations

from typing import Any, Literal

NoticeKind = Literal["approval_pending", "error"]

LOCALES = ("es", "en")
# Config keys every provider accepts.
COMMON_CONFIG = ("locale", "approval_message", "error_message")
MAX_NOTICE = 1000

DEFAULT_NOTICES: dict[str, dict[NoticeKind, str]] = {
    "es": {
        "approval_pending": (
            "Tu solicitud necesita la aprobación de una persona del equipo. Te responderé aquí en cuanto se decida."
        ),
        "error": "Lo siento, ahora mismo no puedo responder. Inténtalo de nuevo en unos minutos.",
    },
    "en": {
        "approval_pending": (
            "Your request needs approval from someone on the team. I will reply here as soon as it is decided."
        ),
        "error": "Sorry, I cannot answer right now. Please try again in a few minutes.",
    },
}


def notice(config: dict[str, Any], kind: NoticeKind) -> str:
    custom = config.get("approval_message" if kind == "approval_pending" else "error_message")
    if isinstance(custom, str) and custom.strip():
        return custom.strip()
    locale = config.get("locale") if config.get("locale") in LOCALES else "es"
    return DEFAULT_NOTICES[str(locale)][kind]


def normalize_common(config: dict[str, Any]) -> dict[str, Any]:
    """Validate the common keys; raises ValueError with a user-facing message."""
    out: dict[str, Any] = {}
    locale = config.get("locale")
    if locale not in (None, ""):
        if locale not in LOCALES:
            raise ValueError("El idioma del canal debe ser «es» o «en»")
        out["locale"] = locale
    for key in ("approval_message", "error_message"):
        value = config.get(key)
        if value in (None, ""):
            continue
        if not isinstance(value, str) or len(value) > MAX_NOTICE:
            raise ValueError(f"«{key}» debe ser un texto de como máximo {MAX_NOTICE} caracteres")
        out[key] = value.strip()
    return out
