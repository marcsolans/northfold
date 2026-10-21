"""Deterministic demo model served when no model provider key is configured.

It speaks the Anthropic Messages API (JSON and streaming SSE) so engine code paths are identical with and
without keys. Behaviour is rule-based and transparent: it chooses a tool by keyword overlap with the tool's
name and description, fills arguments from the user's text (identifiers, amounts, quoted strings, the text
itself for query-like fields), and answers from tool results quoting their sources. Every reply is labelled
as coming from the demo model. Usage is reported for tracing, priced at zero (model ``messer/demo``).
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import AsyncIterator
from typing import Any

DEMO_NOTICE = "[Modo demo — configura ANTHROPIC_API_KEY para usar Claude]"
_STOP = {
    "de",
    "la",
    "el",
    "en",
    "y",
    "a",
    "los",
    "las",
    "del",
    "un",
    "una",
    "por",
    "para",
    "con",
    "que",
    "es",
    "al",
    "lo",
    "se",
    "me",
    "mi",
    "su",
    "sus",
    "the",
    "of",
    "to",
    "and",
    "in",
    "for",
    "on",
    "is",
    "it",
    "this",
    "that",
    "with",
    "an",
    "or",
    "be",
    "as",
    "at",
    "by",
    "from",
    "puedes",
    "quiero",
    "please",
    "favor",
    "hola",
    "hello",
}
_QUERY_FIELDS = (
    "query",
    "question",
    "q",
    "text",
    "prompt",
    "message",
    "body",
    "content",
    "search",
    "topic",
    "consulta",
    "pregunta",
    "descripcion",
    "description",
)
_ID_RE = re.compile(r"\b[A-Z]{1,6}[-/]?\d{2,}(?:[-/]\d+)*\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_AMOUNT_RE = re.compile(r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:€|eur|euros?|\$|usd)?", re.I)
_QUOTED_RE = re.compile(r"[\"“«']([^\"”»']{2,200})[\"”»']")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", _norm(text))
    out: set[str] = set()
    for w in words:
        if w in _STOP or len(w) < 3:
            continue
        out.add(w)
        out.add(w[:5])  # crude stem so "facturas" ~ "factura", "abonos" ~ "abono"
    return out


def _english(text: str) -> bool:
    t = _tokens(text)
    return len(t & {"what", "which", "how", "please", "invoice", "when", "where", "can", "could", "show"}) > len(
        t & {"que", "cual", "como", "factura", "cuando", "donde", "puedes", "dime", "muestra"}
    )


def _blocks_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _parse_amount(raw: str) -> float:
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif raw.count(".") == 1 and len(raw.split(".")[1]) == 3:
        raw = raw.replace(".", "")
    return float(raw)


_RECIPIENT_FIELDS = {"to", "recipient", "destinatario", "para", "email", "correo"}


def _fill_args(schema: dict[str, Any], text: str) -> dict[str, Any]:
    props: dict[str, Any] = schema.get("properties", {}) or {}
    required: list[str] = list(schema.get("required", []) or [])
    ids = _ID_RE.findall(text)
    emails = _EMAIL_RE.findall(text)
    quoted = _QUOTED_RE.findall(text)
    amounts = [m.group(1) for m in _AMOUNT_RE.finditer(text) if not _ID_RE.search(m.group(0))]
    args: dict[str, Any] = {}
    for name, prop in props.items():
        ptype = prop.get("type")
        lname = _norm(name)
        if prop.get("enum"):
            args[name] = prop["enum"][0]
            continue
        if ptype in ("number", "integer"):
            if amounts:
                value = _parse_amount(amounts.pop(0))
                args[name] = int(value) if ptype == "integer" else value
            elif name in required:
                args[name] = 1 if ptype == "integer" else 0.0
            continue
        if ptype == "boolean":
            if name in required:
                args[name] = True
            continue
        if ptype == "array":
            if name in required:
                args[name] = []
            continue
        if ptype == "object":
            if name in required:
                args[name] = {}
            continue
        # strings
        ldesc = _norm(str(prop.get("description", "")))
        if emails and (lname in _RECIPIENT_FIELDS or "mail" in lname or "destinat" in ldesc or "recipient" in ldesc):
            args[name] = emails[0]
        elif any(k in lname for k in ("id", "number", "numero", "code", "codigo", "ref", "invoice", "factura")) and ids:
            args[name] = ids[0]
        elif any(k in lname for k in _QUERY_FIELDS):
            args[name] = quoted[0] if quoted else text.strip()
        elif "sql" in lname:
            args[name] = "SELECT 1"
        elif "url" in lname:
            urls = re.findall(r"https?://\S+", text)
            if urls:
                args[name] = urls[0]
            elif name in required:
                args[name] = ""
        elif name in required:
            # Quoted fragments fill the remaining fields in order ("asunto" then "texto", ...).
            args[name] = quoted.pop(0) if quoted else (ids[0] if ids else text.strip()[:200])
    return args


def _choose_tool(tools: list[dict[str, Any]], text: str) -> dict[str, Any] | None:
    words = _tokens(text)
    if not words:
        return None
    best: tuple[float, dict[str, Any]] | None = None
    for tool in tools:
        if "input_schema" not in tool:  # server tools (web search…) are not simulated
            continue
        name = str(tool.get("name", ""))
        if name in ("read_offloaded", "get_background_task", "list_background_tasks", "cancel_background_task"):
            continue
        name_tokens = _tokens(name.replace("_", " "))
        desc_tokens = _tokens(str(tool.get("description", "")))
        score = 3 * len(words & name_tokens) + len(words & desc_tokens)
        if name == "knowledge_search" and (
            "?" in text
            or words & {"cual", "como", "que", "cuando", "politica", "condic", "plazo", "what", "how", "when", "terms"}
        ):
            score += 3
        if name in ("current_datetime",) and words & {"hoy", "fecha", "today", "date", "hora", "time"}:
            score += 4
        if name == "calculator" and re.search(r"\d\s*[-+*/%]\s*\d", text):
            score += 5
        if best is None or score > best[0]:
            best = (score, tool)
    if best is None or best[0] < 2:
        return None
    return best[1]


def _summarize_result(content: Any) -> str:
    if isinstance(content, list):
        content = "\n".join(_blocks_text([b]) if isinstance(b, dict) else str(b) for b in content)
    text = str(content)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text[:800]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        lines = []
        for r in data["results"][:3]:
            pages = r.get("pages") or []
            page = f", pág. {pages[0]}" if pages and pages[0] else ""
            snippet = re.sub(r"\s+", " ", str(r.get("content", ""))).strip()[:280]
            lines.append(f"• {snippet} ({r.get('source', 'documento')}{page})")
        return "\n".join(lines) if lines else "No he encontrado información relevante."
    if isinstance(data, dict) and "rows" in data and "columns" in data:
        cols = data.get("columns", [])
        rows = data.get("rows", [])[:5]
        head = " | ".join(str(c.get("name", c)) if isinstance(c, dict) else str(c) for c in cols)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
        return f"{head}\n{body}" if rows else "La consulta no ha devuelto filas."
    return json.dumps(data, ensure_ascii=False)[:800]


def _estimate_tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, ensure_ascii=False, default=str)) // 4)


def respond(body: dict[str, Any]) -> dict[str, Any]:
    """Build a complete Anthropic Messages response for ``body``."""
    messages: list[dict[str, Any]] = body.get("messages", [])
    tools: list[dict[str, Any]] = body.get("tools", []) or []
    last = messages[-1] if messages else {"role": "user", "content": ""}
    raw_content = last.get("content")
    content_blocks: list[Any] = raw_content if isinstance(raw_content, list) else []
    tool_results = [b for b in content_blocks if isinstance(b, dict) and b.get("type") == "tool_result"]
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            t = _blocks_text(msg.get("content"))
            if t.strip():
                user_text = t
                break
    en = _english(user_text)
    blocks: list[dict[str, Any]]
    stop_reason = "end_turn"
    if tool_results:
        parts = []
        for res in tool_results:
            if res.get("is_error"):
                parts.append(
                    ("The action could not be completed: " if en else "No se ha podido completar la acción: ")
                    + _summarize_result(res.get("content"))[:400]
                )
            else:
                parts.append(_summarize_result(res.get("content")))
        lead = "Here is what I found:" if en else "Esto es lo que he encontrado:"
        blocks = [{"type": "text", "text": f"{lead}\n{chr(10).join(parts)}\n\n{DEMO_NOTICE}"}]
    else:
        tool = _choose_tool(tools, user_text)
        already_called = any(
            isinstance(b, dict) and b.get("type") == "tool_use"
            for m in messages[-3:]
            if m.get("role") == "assistant"
            for b in (m.get("content") or [])
            if isinstance(m.get("content"), list)
        )
        if tool is not None and not already_called:
            args = _fill_args(tool.get("input_schema", {}), user_text)
            intro = "Let me check that." if en else "Voy a consultarlo."
            blocks = [
                {"type": "text", "text": intro},
                {"type": "tool_use", "id": f"toolu_demo_{uuid.uuid4().hex[:16]}", "name": tool["name"], "input": args},
            ]
            stop_reason = "tool_use"
        else:
            reply = (
                "I'm the Messer demo model. I can use this agent's tools (knowledge search, connectors…) when your "
                "question mentions them."
                if en
                else "Soy el modelo de demostración de Messer. Puedo usar las herramientas de este agente (búsqueda en "
                "conocimiento, conectores…) cuando tu pregunta las menciona."
            )
            blocks = [{"type": "text", "text": f"{reply}\n\n{DEMO_NOTICE}"}]
    input_tokens = _estimate_tokens({"system": body.get("system"), "messages": messages, "tools": tools})
    output_tokens = _estimate_tokens(blocks)
    return {
        "id": f"msg_demo_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "messer-demo"),
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def stream(body: dict[str, Any]) -> AsyncIterator[bytes]:
    """Stream the same response as Anthropic SSE events (text in small deltas)."""
    message = respond(body)
    usage = message["usage"]
    start = {
        **message,
        "content": [],
        "stop_reason": None,
        "usage": {
            "input_tokens": usage["input_tokens"],
            "output_tokens": 1,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }
    yield _sse("message_start", {"type": "message_start", "message": start})
    for index, block in enumerate(message["content"]):
        if block["type"] == "text":
            yield _sse(
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
            )
            text = block["text"]
            for i in range(0, len(text), 24):
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text[i : i + 24]},
                    },
                )
        else:
            yield _sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": index,
                    "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
                },
            )
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": index,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps(block["input"], ensure_ascii=False),
                    },
                },
            )
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": index})
    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": message["stop_reason"], "stop_sequence": None},
            "usage": {"output_tokens": usage["output_tokens"]},
        },
    )
    yield _sse("message_stop", {"type": "message_stop"})
