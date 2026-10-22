"""Remote-runnable adapter: the engine's ``VoiceSession`` talks to an agent that runs in the runtime.

Agents never run in the voice service. Each user turn becomes one run streamed from the runtime
(``messer_common.runtime_client.stream_run``) with ``channel`` = ``voice`` | ``phone`` and the call's conversation,
and the runtime's engine events are rehydrated into the event objects ``VoiceSession`` consumes:

* text deltas of the root agent's own LLM (``<agent>.llm``) → ``DeltaEvent(TextDelta)`` (spoken),
* ``START`` of a tool span directly under the agent → ``DeltaEvent(ToolUse)`` (tool-call filler, status),
* the root LLM's ``OUTPUT`` → ``OutputEvent(output=Message)`` (reconcile final text, drain TTS),
* ``APPROVAL`` / ``INTERACTION`` → the engine events (the session lifts them to ``agent_approval`` …).

Memory: a turn continues from the conversation's ``last_run_id`` (``parent_run_id``), which the runtime updates
when it finalizes each run — the same rule as every other channel, so approvals resumed from the inbox chain
correctly. A barge-in stops *reading* the run, never the run itself: it keeps draining in the background so the
runtime finalizes it (trace, cost, credits, memory), and the next turn waits for it before chaining.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from messer.types.events import ApprovalEvent, InteractionEvent, OutputEvent, validate_event
from messer.types.events.delta import DeltaEvent, TextDelta, ToolUse
from messer.types.message import Message
from messer_common import runtime_client
from messer_common.db import new_id, system_session
from messer_common.db.models import Conversation
from messer_common.logging import get_logger
from messer_common.runtime_client import RuntimeUnavailable

from .context import CallContext
from .phrases import phrase

log = get_logger("messer.voice.agent")

PREVIOUS_RUN_WAIT_S = 20.0
_END = object()
_FAILED = ("error", "timeout", "budget_exceeded", "blocked", "cancelled")


@dataclass(slots=True)
class TurnRun:
    """One user turn and the run that answered it."""

    turn_index: int
    run_id: str
    user_text: str
    parent_run_id: str | None
    started_ms: int
    status: str = "running"
    assistant_text: str = ""
    cost_usd: str = "0"
    credits: str = "0"
    demo: bool = False
    error: dict[str, Any] | None = None
    approvals: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    finished: asyncio.Event = field(default_factory=asyncio.Event)

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "status": self.status,
            "user_text": self.user_text,
            "assistant_text": self.assistant_text,
            "cost_usd": self.cost_usd,
            "credits": self.credits,
            "demo": self.demo,
            "tools": self.tools,
            "approvals": [
                {"id": a.get("id"), "tool_name": a.get("tool_name"), "title": a.get("title")} for a in self.approvals
            ],
            "error": self.error,
            "started_ms": self.started_ms,
        }


class _Translator:
    """Runtime wire events (dicts) → engine event objects for one run."""

    def __init__(self, turn: TurnRun, language: str) -> None:
        self.turn = turn
        self.language = language
        self.root_call: str | None = None
        self.root_path: str | None = None
        self.llm_path: str | None = None
        self.tool_calls: set[str] = set()

    def feed(self, data: dict[str, Any]) -> list[Any]:
        kind = data.get("type")
        path = str(data.get("path") or "")
        if kind == "START":
            if self.root_call is None and data.get("parent_call_id") is None:
                self.root_call = str(data.get("call_id"))
                self.root_path = path
                self.llm_path = f"{path}.llm"
                return []
            if (
                self.root_call is not None
                and data.get("parent_call_id") == self.root_call
                and path != self.llm_path
                and path.startswith(f"{self.root_path}.")
            ):
                call_id = str(data.get("call_id"))
                if call_id in self.tool_calls:
                    return []
                self.tool_calls.add(call_id)
                name = path.rsplit(".", 1)[-1]
                self.turn.tools.append(name)
                return [
                    DeltaEvent(
                        run_id=self.turn.run_id,
                        path=self.llm_path or path,
                        call_id=call_id,
                        item=ToolUse(id=call_id, name=name),
                    )
                ]
            return []
        if kind == "DELTA":
            item = data.get("item") or {}
            if path != self.llm_path or not isinstance(item, dict) or item.get("type") not in ("text_delta", "text"):
                return []
            event = validate_event(data)
            return [event]
        if kind == "OUTPUT":
            if path != self.llm_path:
                return []
            output = data.get("output")
            status = data.get("status") or {}
            if not isinstance(output, dict) or "role" not in output or "content" not in output:
                return []
            try:
                message = Message.validate(output)  # type: ignore[arg-type]
                return [
                    OutputEvent(
                        run_id=str(data.get("run_id") or self.turn.run_id),
                        path=path,
                        call_id=str(data.get("call_id")),
                        parent_call_id=data.get("parent_call_id"),
                        status=status if isinstance(status, dict) and status else {"code": "success"},
                        t0=int(data.get("t0") or 0),
                        t1=int(data.get("t1") or 0),
                        output=message,
                    )
                ]
            except (ValueError, TypeError) as exc:
                log.warning("voice.agent.bad_llm_output", error=str(exc))
                return []
        if kind in ("APPROVAL", "INTERACTION"):
            try:
                event = validate_event(data)
            except (ValueError, TypeError) as exc:
                log.warning("voice.agent.bad_suspension_event", error=str(exc))
                return []
            if isinstance(event, ApprovalEvent | InteractionEvent):
                return [event]
        return []

    def finish(self) -> list[Any]:
        """A failed turn that said nothing still gets a spoken apology (the error itself reaches the client)."""
        if self.turn.status in _FAILED and not self.turn.assistant_text.strip():
            text = phrase("turn_failed", self.language)
            return [
                DeltaEvent(
                    run_id=self.turn.run_id,
                    path=self.llm_path or "voice.llm",
                    call_id=f"{self.turn.run_id}-apology",
                    item=TextDelta(id=f"{self.turn.run_id}-apology", text_delta=text),
                )
            ]
        return []


TurnCallback = Callable[[TurnRun], Awaitable[None]]


class RuntimeAgent:
    """Duck-typed agent for :class:`messer.voice.VoiceSession` backed by runtime runs."""

    def __init__(self, ctx: CallContext, *, on_turn_finished: TurnCallback | None = None) -> None:
        self.ctx = ctx
        self.name = ctx.workforce
        # No provider connection to warm and no in-process tracing: the runtime owns both.
        self.model: str | None = None
        self.tracing_provider = None
        self.turns: list[TurnRun] = []
        self.current: TurnRun | None = None
        self._on_turn_finished = on_turn_finished
        self._pumps: set[asyncio.Task[None]] = set()
        self._last_pump: asyncio.Task[None] | None = None
        self._last_run_id: str | None = None

    @property
    def current_run_id(self) -> str | None:
        return self.current.run_id if self.current is not None else None

    def __call__(self, *, prompt: Any = None, **_: Any) -> AsyncIterator[Any]:
        text = prompt.collect_text() if isinstance(prompt, Message) else str(prompt or "")
        return self._turn(text.strip())

    async def _resolve_system_prompt(self) -> str | None:
        return None

    async def _parent_run_id(self) -> str | None:
        previous = self._last_pump
        if previous is not None and not previous.done():
            try:
                await asyncio.wait_for(asyncio.shield(previous), timeout=PREVIOUS_RUN_WAIT_S)
            except TimeoutError:
                log.warning("voice.agent.previous_run_slow", call_id=str(self.ctx.call_id))
        if self.ctx.conversation_id is None:
            return self._last_run_id
        async with system_session() as s:
            last = (
                await s.execute(
                    select(Conversation.last_run_id).where(
                        Conversation.id == self.ctx.conversation_id, Conversation.org_id == self.ctx.org_id
                    )
                )
            ).scalar_one_or_none()
        return last.hex if last is not None else self._last_run_id

    def _body(self, turn: TurnRun) -> dict[str, Any]:
        ctx = self.ctx
        return {
            "org_id": str(ctx.org_id),
            "project_id": str(ctx.project_id),
            "workforce": ctx.workforce,
            "ref": ctx.ref,
            "input": {"prompt": turn.user_text},
            "run_id": turn.run_id,
            "parent_run_id": turn.parent_run_id,
            "environment": ctx.environment,
            "environment_id": str(ctx.environment_id) if ctx.environment_id else None,
            "version_id": str(ctx.version_id) if ctx.version_id else None,
            "channel": ctx.channel,
            "user_id": str(ctx.user_id) if ctx.user_id else None,
            "external_user_id": ctx.external_user_id,
            "conversation_id": str(ctx.conversation_id) if ctx.conversation_id else None,
        }

    async def _turn(self, text: str) -> AsyncIterator[Any]:
        parent = await self._parent_run_id()
        turn = TurnRun(
            turn_index=len(self.turns) + 1,
            run_id=new_id().hex,
            user_text=text,
            parent_run_id=parent,
            started_ms=int(time.time() * 1000),
        )
        self.turns.append(turn)
        self.current = turn
        queue: asyncio.Queue[Any] = asyncio.Queue()
        pump = asyncio.create_task(self._pump(turn, queue), name=f"voice-run-{turn.run_id}")
        self._last_pump = pump
        self._pumps.add(pump)
        pump.add_done_callback(self._pumps.discard)
        translator = _Translator(turn, self.ctx.language)
        while True:
            item = await queue.get()
            if item is _END:
                break
            for event in translator.feed(item):
                yield event
        for event in translator.finish():
            yield event

    async def _pump(self, turn: TurnRun, queue: asyncio.Queue[Any]) -> None:
        """Read the run to the end, whoever is still listening."""
        try:
            async for event in runtime_client.stream_run(self._body(turn)):
                kind = event.get("type")
                if kind == "DELTA":
                    item = event.get("item") or {}
                    if isinstance(item, dict) and str(event.get("path", "")).endswith(".llm"):
                        turn.assistant_text += str(item.get("text_delta") or "")
                elif kind == "OUTPUT" and event.get("parent_call_id") is None:
                    output = event.get("output")
                    if isinstance(output, dict):
                        content = output.get("content")
                        if isinstance(content, list):
                            final = "".join(
                                str(b.get("text", ""))
                                for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                            if final.strip():
                                turn.assistant_text = final
                elif kind == "RUN_ERROR":
                    error = event.get("error")
                    turn.error = error if isinstance(error, dict) else {"message": str(error)}
                elif kind == "RUN_FINISHED":
                    turn.status = str(event.get("status") or "error")
                    turn.cost_usd = str(event.get("cost_usd") or "0")
                    turn.credits = str(event.get("credits") or "0")
                    turn.demo = bool(event.get("demo"))
                    turn.approvals = [a for a in event.get("approvals") or [] if isinstance(a, dict)]
                    if event.get("error"):
                        turn.error = event["error"]
                queue.put_nowait(event)
        except RuntimeUnavailable as exc:
            turn.status = "error"
            turn.error = {"type": "runtime_unavailable", "message": str(exc)[:500]}
            log.error("voice.agent.runtime_unavailable", call_id=str(self.ctx.call_id), error=str(exc))
        except Exception as exc:
            turn.status = "error"
            turn.error = {"type": type(exc).__name__, "message": str(exc)[:500]}
            log.exception("voice.agent.run_failed", call_id=str(self.ctx.call_id))
        finally:
            if turn.status == "running":
                turn.status = "error"
            if turn.status not in _FAILED:
                self._last_run_id = turn.run_id
            queue.put_nowait(_END)
            turn.finished.set()
            if self._on_turn_finished is not None:
                try:
                    await self._on_turn_finished(turn)
                except Exception:
                    log.exception("voice.agent.turn_callback_failed", run_id=turn.run_id)

    async def drain(self, timeout_s: float = 60.0) -> None:
        """Wait for every run of the call to finish (call teardown)."""
        pending = [t for t in self._pumps if not t.done()]
        if not pending:
            return
        _done, still = await asyncio.wait(pending, timeout=timeout_s)
        for task in still:
            log.warning("voice.agent.run_abandoned", call_id=str(self.ctx.call_id), task=task.get_name())
