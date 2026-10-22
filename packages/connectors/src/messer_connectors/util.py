"""Small shared helpers: argument validation, identifiers, text extraction."""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .base import ActionSpec, InvalidArguments


def validate_args(spec: ActionSpec, args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate action arguments against the action's JSON Schema; applies top-level defaults."""
    data = dict(args or {})
    props = spec.input_schema.get("properties", {})
    for name, prop in props.items():
        if name not in data and isinstance(prop, dict) and "default" in prop:
            data[name] = prop["default"]
    validator = Draft202012Validator(spec.input_schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        first: ValidationError = errors[0]
        where = ".".join(str(p) for p in first.path) or "args"
        raise InvalidArguments(
            f"Argumentos no válidos para «{spec.name}»: {where}: {first.message}",
            details={"errors": [{"path": [str(p) for p in e.path], "message": e.message} for e in errors[:10]]},
        )
    return data


_IDENT_RE = re.compile(r"[^a-z0-9_]+")


def kb_identifier(name: str, *, prefix: str = "t") -> str:
    """Postgres-safe lowercase identifier (max 63 chars) for knowledge tables and columns."""
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    ident = _IDENT_RE.sub("_", folded).strip("_")
    if not ident:
        ident = prefix
    if ident[0].isdigit():
        ident = f"{prefix}_{ident}"
    return ident[:63]


_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|tr|h[1-6]|table|ul|ol)[^>]*>", re.IGNORECASE)
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


def html_to_text(value: str) -> str:
    text = _SCRIPT_RE.sub(" ", value)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def truncate(text: str, limit: int = 20_000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n…"


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def to_rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_filename(name: str, default: str = "documento") -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip().strip(".")
    return (cleaned or default)[:200]
