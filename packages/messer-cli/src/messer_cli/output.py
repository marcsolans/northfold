"""Terminal output helpers (colors only on a TTY and without ``NO_COLOR``)."""

from __future__ import annotations

import json
import os
import sys
from typing import Any


def _color(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


def bold(text: str) -> str:
    return _color("1", text)


def dim(text: str) -> str:
    return _color("2", text)


def green(text: str) -> str:
    return _color("32", text)


def red(text: str) -> str:
    return _color("31", text)


def yellow(text: str) -> str:
    return _color("33", text)


def say(*parts: Any) -> None:
    print(*parts, flush=True)  # noqa: T201 - CLI output


def err(message: str) -> None:
    print(f"{red('Error:')} {message}", file=sys.stderr, flush=True)  # noqa: T201 - CLI output


def as_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str), flush=True)  # noqa: T201 - CLI output


def table(rows: list[list[str]], headers: list[str]) -> None:
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
    say("  ".join(bold(h.ljust(w)) for h, w in zip(headers, widths, strict=True)))
    for row in rows:
        say("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))
