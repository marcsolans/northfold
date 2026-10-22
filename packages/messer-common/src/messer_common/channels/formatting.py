"""Text helpers for channels: provider formatting of the agent's Markdown and splitting long replies."""

from __future__ import annotations

import html
import re
from typing import Any

MAX_PARTS = 10
ELLIPSIS = "…"

_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", re.DOTALL)
_ITALIC_STAR = re.compile(r"(?<![\w*])\*(?=\S)([^*\n]+?)(?<=\S)\*(?![\w*])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+|mailto:[^\s)]+)\)")
_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*+]\s+", re.MULTILINE)
_HR = re.compile(r"^[ \t]*(?:(?:-[ \t]*){3,}|(?:\*[ \t]*){3,}|(?:_[ \t]*){3,})$", re.MULTILINE)
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_BOLD_MARK = "\x01"


def text_of(output: Any) -> str:
    """Plain text of an agent output (engine message with content blocks, or a string)."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict):
        content = output.get("content")
        if isinstance(content, list):
            return "".join(
                str(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"
            ).strip()
        if isinstance(content, str):
            return content.strip()
        if "text" in output:
            return str(output["text"]).strip()
    return ""


def _protect_code(text: str) -> tuple[str, list[str]]:
    blocks: list[str] = []

    def keep(match: re.Match[str]) -> str:
        blocks.append(match.group(0))
        return f"\x02{len(blocks) - 1}\x02"

    return _FENCE.sub(keep, text), blocks


def _restore_code(text: str, blocks: list[str], *, fence: bool) -> str:
    def put(match: re.Match[str]) -> str:
        raw = blocks[int(match.group(1))]
        if fence:
            return raw
        inner = _FENCE.match(raw)
        return inner.group(1).rstrip("\n") if inner else raw

    return re.sub(r"\x02(\d+)\x02", put, text)


def to_whatsapp(markdown: str) -> str:
    """WhatsApp: *bold*, _italic_, ~strike~, ```code```, plain links, • bullets."""
    text, code = _protect_code(markdown.strip())
    text = _HR.sub("", text)
    text = _HEADING.sub(lambda m: f"{_BOLD_MARK}{m.group(1)}{_BOLD_MARK}", text)
    text = _BOLD.sub(lambda m: f"{_BOLD_MARK}{m.group(1) or m.group(2)}{_BOLD_MARK}", text)
    text = _ITALIC_STAR.sub(r"_\1_", text)
    text = _STRIKE.sub(r"~\1~", text)
    text = _LINK.sub(lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})", text)
    text = _BULLET.sub(r"\1• ", text)
    text = text.replace(_BOLD_MARK, "*")
    return _restore_code(_collapse(text), code, fence=True)


def to_slack(markdown: str) -> str:
    """Slack mrkdwn: escape &, <, > and use *bold*, _italic_, ~strike~, <url|text> links."""
    text, code = _protect_code(markdown.strip())
    links: list[str] = []

    def keep_link(match: re.Match[str]) -> str:
        label = match.group(1).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        links.append(f"<{match.group(2)}|{label}>")
        return f"\x03{len(links) - 1}\x03"

    text = _LINK.sub(keep_link, text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = _HR.sub("", text)
    text = _HEADING.sub(lambda m: f"{_BOLD_MARK}{m.group(1)}{_BOLD_MARK}", text)
    text = _BOLD.sub(lambda m: f"{_BOLD_MARK}{m.group(1) or m.group(2)}{_BOLD_MARK}", text)
    text = _ITALIC_STAR.sub(r"_\1_", text)
    text = _STRIKE.sub(r"~\1~", text)
    text = _BULLET.sub(r"\1• ", text)
    text = text.replace(_BOLD_MARK, "*")
    text = re.sub(r"\x03(\d+)\x03", lambda m: links[int(m.group(1))], text)
    return _restore_code(_collapse(text), code, fence=True)


def to_plain(markdown: str) -> str:
    """Plain text (Telegram without parse mode, email text part): Markdown markers removed, links spelled out."""
    text, code = _protect_code(markdown.strip())
    text = _HR.sub("", text)
    text = _HEADING.sub(r"\1", text)
    text = _BOLD.sub(lambda m: m.group(1) or m.group(2), text)
    text = _ITALIC_STAR.sub(r"\1", text)
    text = _STRIKE.sub(r"\1", text)
    text = _LINK.sub(lambda m: m.group(2) if m.group(1) == m.group(2) else f"{m.group(1)} ({m.group(2)})", text)
    text = _BULLET.sub(r"\1• ", text)
    text = re.sub(r"`([^`\n]+)`", r"\1", text)
    return _restore_code(_collapse(text), code, fence=False)


def to_html(markdown: str) -> str:
    """Minimal, safe HTML for email replies (escaped text, paragraphs, bold, italics, links, lists, code)."""
    text, code = _protect_code(markdown.strip())
    text = re.sub(r"\x02(\d+)\x02", lambda m: f"\n\n{m.group(0)}\n\n", _HR.sub("", text))
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if re.fullmatch(r"\x02\d+\x02", block):
            out.append(block)
            continue
        lines = block.splitlines()
        if all(_BULLET.match(line) for line in lines):
            items = "".join(f"<li>{_inline_html(_BULLET.sub('', line, count=1))}</li>" for line in lines)
            out.append(f"<ul>{items}</ul>")
            continue
        heading = _HEADING.fullmatch(block)
        if heading:
            out.append(f"<p><strong>{_inline_html(heading.group(1))}</strong></p>")
            continue
        out.append("<p>" + "<br>".join(_inline_html(line) for line in lines) + "</p>")
    rendered = "\n".join(out)

    def put(match: re.Match[str]) -> str:
        inner = _FENCE.match(code[int(match.group(1))])
        body = inner.group(1).rstrip("\n") if inner else code[int(match.group(1))]
        return f'<pre style="font-family:monospace">{html.escape(body)}</pre>'

    return re.sub(r"\x02(\d+)\x02", put, rendered)


def _inline_html(text: str) -> str:
    links: list[str] = []

    def keep_link(match: re.Match[str]) -> str:
        links.append(f'<a href="{html.escape(match.group(2), quote=True)}">{html.escape(match.group(1))}</a>')
        return f"\x03{len(links) - 1}\x03"

    text = _LINK.sub(keep_link, text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", text)
    text = _ITALIC_STAR.sub(r"<em>\1</em>", text)
    text = _STRIKE.sub(r"<del>\1</del>", text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    return re.sub(r"\x03(\d+)\x03", lambda m: links[int(m.group(1))], text)


def _collapse(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def split_text(text: str, limit: int, max_parts: int = MAX_PARTS) -> list[str]:
    """Split ``text`` into chunks of at most ``limit`` characters, preferring paragraph, line, sentence and word
    boundaries. At most ``max_parts`` chunks are returned; the last one ends with an ellipsis when truncated."""
    text = text.strip()
    if not text:
        return []
    if limit < 20:
        raise ValueError("limit too small")
    parts: list[str] = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = -1
        for sep in ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " "):
            idx = window.rfind(sep)
            if idx >= limit // 3:
                # Sentence and clause separators keep their punctuation in the current chunk.
                cut = idx + (1 if sep in (". ", "? ", "! ", "; ", ", ") else 0)
                break
        if cut <= 0:
            cut = limit
        chunk = rest[:cut].rstrip()
        if chunk:
            parts.append(chunk)
        rest = rest[cut:].lstrip()
        if len(parts) == max_parts:
            break
    if rest and len(parts) < max_parts:
        parts.append(rest)
    elif rest:
        last = parts[-1]
        parts[-1] = (last[: limit - len(ELLIPSIS)].rstrip() if len(last) >= limit else last) + ELLIPSIS
    return parts


def single_line(text: str, limit: int) -> str:
    """Collapse whitespace (template parameters may not contain newlines or long runs of spaces) and truncate."""
    flat = re.sub(r"\s+", " ", text).strip()
    if len(flat) <= limit:
        return flat
    return flat[: limit - len(ELLIPSIS)].rstrip() + ELLIPSIS
