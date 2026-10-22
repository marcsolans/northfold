# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Model proxy of the standalone platform (Anthropic Messages API compatible).

With ``ANTHROPIC_API_KEY`` requests are forwarded to Anthropic unchanged (JSON or streamed SSE). Without a key an
**offline echo model** answers instead, clearly labelled in every reply: it repeats the user's message, and when the
agent has a ``knowledge_search`` tool it searches the exported knowledge first and quotes the passages it found, so
an exported project can be tried end to end with no keys.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

OFFLINE_MODEL = "messer-offline-echo"
OFFLINE_NOTICE = "[Modelo offline de la exportación · Offline export model — añade ANTHROPIC_API_KEY al archivo .env para usar Claude]"
_PASSTHROUGH_HEADERS = ("anthropic-version", "anthropic-beta", "content-type")


def forward_headers(incoming: dict[str, str], api_key: str) -> dict[str, str]:
    headers = {k: v for k, v in incoming.items() if k.lower() in _PASSTHROUGH_HEADERS}
    headers.setdefault("anthropic-version", "2023-06-01")
    headers.setdefault("content-type", "application/json")
    headers["x-api-key"] = api_key
    return headers


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _result_text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(_text_of([b]) if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def _summarize(raw: str) -> str:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw[:800]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        lines = []
        for item in data["results"][:3]:
            snippet = " ".join(str(item.get("content") or "").split())[:300]
            pages = item.get("pages") or []
            page = f", p. {pages[0]}" if pages and pages[0] else ""
            lines.append(f"- {snippet} ({item.get('source') or 'documento'}{page})")
        return "\n".join(lines) if lines else "No hay pasajes relevantes en la base de conocimiento exportada."
    return json.dumps(data, ensure_ascii=False)[:800]


def _tokens(obj: Any) -> int:
    return max(1, len(json.dumps(obj, ensure_ascii=False, default=str)) // 4)


def offline_reply(body: dict[str, Any]) -> dict[str, Any]:
    """A complete Anthropic Messages response produced without any model."""
    messages: list[dict[str, Any]] = list(body.get("messages") or [])
    tools: list[dict[str, Any]] = list(body.get("tools") or [])
    last = messages[-1] if messages else {"role": "user", "content": ""}
    blocks_in = last.get("content") if isinstance(last.get("content"), list) else []
    tool_results = [b for b in blocks_in if isinstance(b, dict) and b.get("type") == "tool_result"]
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user" and _text_of(msg.get("content")).strip():
            user_text = _text_of(msg.get("content")).strip()
            break
    stop_reason = "end_turn"
    if tool_results:
        found = "\n".join(_summarize(_result_text(r.get("content"))) for r in tool_results)
        blocks: list[dict[str, Any]] = [
            {"type": "text", "text": f"Esto es lo que he encontrado:\n{found}\n\n{OFFLINE_NOTICE}"}
        ]
    elif user_text and any(t.get("name") == "knowledge_search" and "input_schema" in t for t in tools):
        blocks = [
            {
                "type": "tool_use",
                "id": f"toolu_offline_{uuid.uuid4().hex[:16]}",
                "name": "knowledge_search",
                "input": {"query": user_text[:500]},
            }
        ]
        stop_reason = "tool_use"
    else:
        echo = user_text or "(mensaje vacío)"
        blocks = [{"type": "text", "text": f"Echo: {echo}\n\n{OFFLINE_NOTICE}"}]
    return {
        "id": f"msg_offline_{uuid.uuid4().hex[:20]}",
        "type": "message",
        "role": "assistant",
        "model": OFFLINE_MODEL,
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": _tokens({"system": body.get("system"), "messages": messages}),
            "output_tokens": _tokens(blocks),
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
    }


def _sse(event: str, data: dict[str, Any]) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


async def offline_stream(body: dict[str, Any]) -> AsyncIterator[bytes]:
    """The offline reply as Anthropic streaming events."""
    message = offline_reply(body)
    usage = message["usage"]
    start = {**message, "content": [], "stop_reason": None, "usage": {**usage, "output_tokens": 1}}
    yield _sse("message_start", {"type": "message_start", "message": start})
    for index, block in enumerate(message["content"]):
        if block["type"] == "text":
            yield _sse(
                "content_block_start",
                {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}},
            )
            text = block["text"]
            for i in range(0, len(text), 32):
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": text[i : i + 32]},
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
