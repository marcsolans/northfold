"""Helpers shared by the voice service tests (agents, model mocks, WebSocket helpers)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx


async def setup_agent(
    client: httpx.AsyncClient,
    *,
    email: str = "marta@acme.example",
    name: str = "recepcion",
    voice: dict[str, Any] | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> str:
    res = await client.post("/api/v1/auth/signup", json={"email": email, "password": "Contrasena123", "name": "Marta"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Recepción"})).json()["id"]
    agent = (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": name})).json()
    cfg = agent["config"]
    cfg["system_prompt"] = "Eres la recepcionista de Acme. Responde en español, en frases cortas."
    cfg["voice"] = {"enabled": True, "voice": "", "language": "es", "greeting": "", **(voice or {})}
    cfg["tools"] = tools or []
    res = await client.put(f"/api/v1/projects/{pid}/workforce/{name}/config", json=cfg)
    assert res.status_code == 200, res.text
    return str(pid)


def _texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    out: list[str] = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(str(block.get("text", "")))
    return out


def anthropic_memory_reply(prefix: str = "") -> Callable[[httpx.Request], httpx.Response]:
    """Anthropic Messages mock whose answer proves what the model saw: the user turns of the conversation."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        users = [t for m in body.get("messages", []) if m.get("role") == "user" for t in _texts(m.get("content"))]
        text = f"{prefix}Llevo {len(users)} mensajes tuyos. El primero: {users[0] if users else ''}"
        usage = {"input_tokens": 100, "output_tokens": 20}
        message = {
            "id": "msg_voice",
            "type": "message",
            "role": "assistant",
            "model": body.get("model", "claude-sonnet-5-5"),
            "content": [{"type": "text", "text": text}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }
        if not body.get("stream"):
            return httpx.Response(200, json=message)
        start = {**message, "content": [], "stop_reason": None, "usage": {"input_tokens": 100, "output_tokens": 1}}
        events = [
            ("message_start", {"type": "message_start", "message": start}),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            ),
            (
                "content_block_delta",
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}},
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 20},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        raw = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)
        return httpx.Response(200, content=raw.encode(), headers={"content-type": "text/event-stream"})

    return handler


async def recv_until(
    ws: Any, kind: str, *, timeout_s: float = 90.0, into: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Read JSON frames until one of type ``kind`` arrives (frames read on the way are appended to ``into``)."""
    async with asyncio.timeout(timeout_s):
        while True:
            raw = await ws.recv()
            if isinstance(raw, bytes):
                continue
            frame = json.loads(raw)
            if into is not None:
                into.append(frame)
            if frame.get("type") == kind:
                return frame


# ------------------------------------------------------------------------------------------- fake speech


class ScriptedSTT:
    """Fake hosted STT with native end-of-turn.

    Browser-style frames carrying ``SAY:<text>`` commit that text; for phone audio (no markers survive μ-law),
    every ``commit_every`` bytes of audio commit the next scripted utterance.
    """

    native_eou = True

    def __init__(self, script: list[str] | None = None, commit_every: int = 12_800) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.script = list(script or [])
        self.commit_every = commit_every
        self.received = 0
        self._since_commit = 0
        self.closed = False

    async def connect(self, config: Any) -> None:
        return None

    async def push_audio(self, chunk: bytes) -> None:
        from messer.voice.providers import TranscriptEvent

        self.received += len(chunk)
        if chunk.startswith(b"SAY:"):
            text = chunk[4:].rstrip(b"\x00").decode()
            self.queue.put_nowait(TranscriptEvent(type="partial", text=text))
            self.queue.put_nowait(TranscriptEvent(type="committed", text=text))
            return
        self._since_commit += len(chunk)
        if self.script and self._since_commit >= self.commit_every:
            self._since_commit = 0
            self.queue.put_nowait(TranscriptEvent(type="committed", text=self.script.pop(0)))

    async def commit(self) -> None:
        return None

    async def events(self) -> Any:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            yield event

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.queue.put_nowait(None)

    def add_usage_listener(self, listener: Any) -> None:
        return None

    def remove_usage_listener(self, listener: Any) -> None:
        return None


class SilentTTS:
    """Fake hosted TTS: ``ms_per_char`` milliseconds of silent PCM16 16 kHz per character."""

    provider_id = "elevenlabs"

    def __init__(self, ms_per_char: float = 20.0) -> None:
        self.ms_per_char = ms_per_char
        self.texts: list[str] = []

    async def connect(self, config: Any) -> None:
        return None

    async def synthesize(self, text: str) -> Any:
        self.texts.append(text)
        total = int(16_000 * len(text) * self.ms_per_char / 1000) * 2
        while total > 0:
            size = min(3200, total)
            total -= size
            yield bytes(size)

    def open_stream(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def add_usage_listener(self, listener: Any) -> None:
        return None

    def remove_usage_listener(self, listener: Any) -> None:
        return None


def say(text: str) -> bytes:
    """A browser audio frame the scripted STT transcribes as ``text`` (padded to 100 ms of PCM)."""
    data = b"SAY:" + text.encode()
    return data + b"\x00" * max(0, 3200 - len(data))


def use_fake_speech(monkeypatch: Any, *, script: list[str] | None = None, ms_per_char: float = 20.0) -> dict[str, Any]:
    """Pretend Deepgram + ElevenLabs are configured and replace them with the fakes above."""
    from messer.voice.providers import AudioInputConfig, AudioOutputConfig
    from messer_common.settings import get_settings
    from messer_voice import session as session_mod

    monkeypatch.setattr(get_settings(), "deepgram_api_key", "dg-test")
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "el-test")
    made: dict[str, Any] = {"stt": [], "tts": []}

    def fake_stt(option: Any, *, language: str | None) -> Any:
        stt = ScriptedSTT(script)
        made["stt"].append(stt)
        return stt, AudioInputConfig(model=option.model, language=language, sample_rate=16_000)

    def fake_tts(option: Any, *, language: str | None, voice: str | None) -> Any:
        tts = SilentTTS(ms_per_char)
        made["tts"].append(tts)
        return tts, AudioOutputConfig(model=option.model, voice=voice or "test", sample_rate=16_000)

    monkeypatch.setattr(session_mod, "build_stt", fake_stt)
    monkeypatch.setattr(session_mod, "build_tts", fake_tts)
    return made


async def upgrade_plan(email: str, plan_id: str = "business") -> None:
    """Move the user's organization to a plan with the ``voice`` feature."""
    from sqlalchemy import select, update

    from messer_common.db import system_session
    from messer_common.db.models import Membership, Org, Subscription, User

    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == email))).scalar_one()
        org_id = (await s.execute(select(Membership.org_id).where(Membership.user_id == user.id))).scalar_one()
        await s.execute(update(Subscription).where(Subscription.org_id == org_id).values(plan_id=plan_id))
        await s.execute(update(Org).where(Org.id == org_id).values(plan_id=plan_id))


def _anthropic(body: dict[str, Any], blocks: list[dict[str, Any]], stop_reason: str) -> httpx.Response:
    usage = {"input_tokens": 100, "output_tokens": 20}
    message = {
        "id": "msg_voice",
        "type": "message",
        "role": "assistant",
        "model": body.get("model", "claude-sonnet-5-5"),
        "content": blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }
    if not body.get("stream"):
        return httpx.Response(200, json=message)
    start = {**message, "content": [], "stop_reason": None, "usage": {"input_tokens": 100, "output_tokens": 1}}
    events: list[tuple[str, dict[str, Any]]] = [("message_start", {"type": "message_start", "message": start})]
    for i, block in enumerate(blocks):
        if block["type"] == "text":
            events.append(
                (
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}},
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}},
                )
            )
        else:
            events.append(
                (
                    "content_block_start",
                    {"type": "content_block_start", "index": i, "content_block": {**block, "input": {}}},
                )
            )
            events.append(
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": i,
                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
                    },
                )
            )
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 20},
            },
        )
    )
    events.append(("message_stop", {"type": "message_stop"}))
    raw = "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events)
    return httpx.Response(200, content=raw.encode(), headers={"content-type": "text/event-stream"})


def anthropic_tool_then_text(final_text: str, *, delay_s: float = 1.5) -> Any:
    """First call: ``calculator`` tool use; after the tool result (and ``delay_s``): ``final_text``."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        last = (body.get("messages") or [{}])[-1]
        content = last.get("content")
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            await asyncio.sleep(delay_s)
            return _anthropic(body, [{"type": "text", "text": final_text}], "end_turn")
        block = {"type": "tool_use", "id": "toolu_voice", "name": "calculator", "input": {"expression": "120*0.21"}}
        return _anthropic(body, [block], "tool_use")

    return handler


def anthropic_text(text: str) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return _anthropic(json.loads(request.content), [{"type": "text", "text": text}], "end_turn")

    return handler
