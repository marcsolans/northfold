"""Structure-aware chunking.

Blocks are grouped under their heading path; a chunk never spans two top-level sections when it is
already substantial, targets ``max_tokens`` (default 800) and carries ``overlap_tokens`` (default 120) of
trailing context from the previous chunk of the same section. Oversized blocks are split by lines, then
sentences, then words. Each chunk keeps its page range and heading path.

Token counts use a fast heuristic close to BPE tokenizers for Spanish and English: one token per short
word plus one per additional five characters, one per punctuation mark, one per CJK character.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .parsing import Block

_TOKEN_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]|\w+|[^\w\s]")
_CJK_RE = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
_SENTENCE_RE = re.compile(r"(?<=[.!?…;:])\s+(?=\S)")


def estimate_tokens(text: str) -> int:
    count = 0
    for piece in _TOKEN_RE.findall(text):
        if len(piece) == 1:
            count += 1
        elif _CJK_RE.match(piece):
            count += 1
        else:
            count += 1 + (len(piece) - 1) // 5
    return count


@dataclass(slots=True)
class Chunk:
    ordinal: int
    content: str
    heading: str | None
    page_from: int | None
    page_to: int | None
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Unit:
    text: str
    tokens: int
    page: int | None


def _split_words(text: str, max_tokens: int) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    tokens = 0
    for word in text.split():
        t = estimate_tokens(word)
        if current and tokens + t > max_tokens:
            out.append(" ".join(current))
            current, tokens = [], 0
        current.append(word)
        tokens += t
    if current:
        out.append(" ".join(current))
    return out


def _pack(pieces: Iterable[str], max_tokens: int, joiner: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    tokens = 0
    for piece in pieces:
        t = estimate_tokens(piece)
        if t > max_tokens:
            if current:
                out.append(joiner.join(current))
                current, tokens = [], 0
            out.extend(_split_words(piece, max_tokens))
            continue
        if current and tokens + t > max_tokens:
            out.append(joiner.join(current))
            current, tokens = [], 0
        current.append(piece)
        tokens += t
    if current:
        out.append(joiner.join(current))
    return out


def split_text(text: str, max_tokens: int) -> list[str]:
    """Split text into pieces of at most ``max_tokens`` along lines, then sentences, then words."""
    if estimate_tokens(text) <= max_tokens:
        return [text]
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) > 1:
        pieces: list[str] = []
        for line in lines:
            pieces.extend(split_text(line, max_tokens))
        return _pack(pieces, max_tokens, "\n")
    sentences = _SENTENCE_RE.split(text)
    if len(sentences) > 1:
        return _pack(sentences, max_tokens, " ")
    return _split_words(text, max_tokens)


def _tail(units: list[_Unit], overlap_tokens: int) -> list[_Unit]:
    """Trailing context (whole sentences when possible) of about ``overlap_tokens`` tokens."""
    if overlap_tokens <= 0 or not units:
        return []
    out: list[_Unit] = []
    budget = overlap_tokens
    for unit in reversed(units):
        if unit.tokens <= budget:
            out.insert(0, unit)
            budget -= unit.tokens
            if budget <= overlap_tokens * 0.15:
                break
            continue
        sentences = _SENTENCE_RE.split(unit.text)
        picked: list[str] = []
        for sentence in reversed(sentences):
            t = estimate_tokens(sentence)
            if t > budget:
                break
            picked.insert(0, sentence)
            budget -= t
        if not picked:
            words = unit.text.split()
            take: list[str] = []
            for word in reversed(words):
                t = estimate_tokens(word)
                if t > budget:
                    break
                take.insert(0, word)
                budget -= t
            picked = [" ".join(take)] if take else []
        if picked:
            text = " ".join(picked)
            out.insert(0, _Unit(text, estimate_tokens(text), unit.page))
        break
    return out


def chunk_blocks(
    blocks: list[Block],
    *,
    max_tokens: int = 800,
    overlap_tokens: int = 120,
    min_section_tokens: int | None = None,
) -> list[Chunk]:
    """Group parsed blocks into retrieval chunks."""
    max_tokens = max(50, max_tokens)
    overlap_tokens = max(0, min(overlap_tokens, max_tokens // 2))
    flush_threshold = min_section_tokens if min_section_tokens is not None else max(40, max_tokens // 8)

    chunks: list[Chunk] = []
    stack: list[tuple[int, str]] = []
    current: list[_Unit] = []
    current_tokens = 0
    current_overlap = 0
    current_path: list[str] = []

    def path() -> list[str]:
        return [text for _, text in stack]

    def flush(carry: bool) -> None:
        nonlocal current, current_tokens, current_overlap, current_path
        if not current or current_tokens <= current_overlap:
            if not carry:
                current, current_tokens, current_overlap = [], 0, 0
            return
        content = "\n\n".join(u.text for u in current).strip()
        if content:
            pages = [u.page for u in current if u.page is not None]
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    content=content,
                    heading=" > ".join(current_path) if current_path else None,
                    page_from=min(pages) if pages else None,
                    page_to=max(pages) if pages else None,
                    token_count=estimate_tokens(content),
                    metadata={"heading_path": list(current_path), "overlap_tokens": current_overlap},
                )
            )
        previous = current
        current = _tail(previous, overlap_tokens) if carry else []
        current_tokens = sum(u.tokens for u in current)
        current_overlap = current_tokens
        current_path = path()

    for block in blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.kind == "heading":
            level = max(1, block.level or 1)
            substantive = current_tokens - current_overlap
            if substantive >= flush_threshold:
                flush(carry=False)
            elif substantive <= 0:
                # Only overlap from the previous section: a heading is a structural boundary, drop it.
                current, current_tokens, current_overlap = [], 0, 0
            else:
                # Small section: keep accumulating, but record the heading inside the text.
                unit = _Unit("#" * min(level, 6) + " " + text, estimate_tokens(text) + 1, block.page)
                current.append(unit)
                current_tokens += unit.tokens
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, text))
            if not current:
                current_path = path()
                current_overlap = 0
            continue
        for piece in split_text(text, max_tokens - overlap_tokens):
            unit = _Unit(piece, estimate_tokens(piece), block.page)
            if current and current_tokens + unit.tokens > max_tokens:
                flush(carry=True)
            if not current:
                current_path = path()
            current.append(unit)
            current_tokens += unit.tokens
    flush(carry=False)
    return chunks
