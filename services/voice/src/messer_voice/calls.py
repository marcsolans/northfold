"""Call records: load what a session needs, and persist what the traces UI shows.

Every call is a ``voice_calls`` row linked to a conversation (provider ``voice`` | ``phone``); each turn is a
runtime run of that conversation. While the call runs, :class:`CallLog` records each finished turn and attaches
a ``voice`` span (per-turn latency from the engine's ``TurnMetrics``, speech providers, interruption) to the
turn's run, so the trace waterfall shows it next to the LLM and tool spans. When the call ends it stores the
transcript as heard, the speech/line usage and cost (charged to the organization's credits) and the recording.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select

from messer.voice import TurnMetricsEvent, VoiceUsageEvent
from messer_common import credits
from messer_common.db import system_session
from messer_common.db.models import Conversation, Run, Span, Workforce
from messer_common.db.models.voice import FINAL_CALL_STATUSES, VoiceCall
from messer_common.events import publish
from messer_common.execution import NotDeployed, resolve_target
from messer_common.logging import get_logger
from messer_common.pricing import usd_to_credits
from messer_common.residency import org_residency
from messer_common.storage import StorageError, get_storage

from .agent import TurnRun
from .context import CallContext
from .session import SessionBundle

log = get_logger("messer.voice.calls")


class CallUnavailable(Exception):
    """The call cannot be served (unknown, already finished, agent not deployed or not an agent)."""

    def __init__(self, message: str, *, code: str = "call_unavailable") -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def recording_key(org_id: uuid.UUID, call_id: uuid.UUID) -> str:
    return f"{org_id}/voice/{call_id}.mp3"


async def load_call(call_id: uuid.UUID) -> VoiceCall:
    async with system_session() as s:
        call = await s.get(VoiceCall, call_id)
    if call is None:
        raise CallUnavailable("La llamada no existe", code="call_not_found")
    return call


async def call_context(call: VoiceCall) -> CallContext:
    """Resolve the agent, the code version and the voice settings for a call."""
    if call.status in FINAL_CALL_STATUSES:
        raise CallUnavailable("La llamada ya ha terminado", code="call_finished")
    async with system_session() as s:
        member = (
            await s.execute(
                select(Workforce).where(
                    Workforce.project_id == call.project_id,
                    Workforce.org_id == call.org_id,
                    Workforce.name == call.workforce_name,
                )
            )
        ).scalar_one_or_none()
        if member is None or member.kind != "agent":
            raise CallUnavailable("El agente de la llamada no existe", code="agent_not_found")
        try:
            target = await resolve_target(s, call.project_id, call.environment)
        except NotDeployed as exc:
            raise CallUnavailable(str(exc), code="not_deployed") from exc
        residency = await org_residency(s, call.org_id)
    voice_cfg = (member.config_json or {}).get("voice") or {}
    if call.transport == "browser":
        external_user = str(call.user_id) if call.user_id else None
    else:
        external_user = call.from_number if call.direction == "inbound" else call.to_number
    return CallContext(
        call_id=call.id,
        org_id=call.org_id,
        project_id=call.project_id,
        workforce=member.name,
        environment=target.environment,
        ref=target.ref,
        environment_id=target.environment_id,
        version_id=target.version_id,
        conversation_id=call.conversation_id,
        user_id=call.user_id,
        external_user_id=external_user,
        channel="phone" if call.channel == "phone" else "voice",
        transport=call.transport,  # type: ignore[arg-type]
        mode="text" if call.mode == "text" else "audio",
        direction="outbound" if call.direction == "outbound" else "inbound",
        language=str(call.language or voice_cfg.get("language") or "es"),
        voice=str(voice_cfg.get("voice") or ""),
        greeting=str((call.meta or {}).get("greeting") or voice_cfg.get("greeting") or ""),
        record=bool(call.record),
        residency=residency,
    )


async def update_call(call_id: uuid.UUID, **values: Any) -> None:
    async with system_session() as s:
        call = await s.get(VoiceCall, call_id)
        if call is None:
            return
        for key, value in values.items():
            setattr(call, key, value)


async def fail_call(call_id: uuid.UUID, *, code: str, message: str, status: str = "failed") -> None:
    async with system_session() as s:
        call = await s.get(VoiceCall, call_id)
        if call is None or call.status in FINAL_CALL_STATUSES:
            return
        ended = _now()
        call.status = status
        call.error = {"code": code, "message": message}
        call.ended_at = ended
        if call.started_at is not None:
            call.duration_ms = int((ended - call.started_at).total_seconds() * 1000)


def _metrics_dict(metrics: Any) -> dict[str, Any]:
    return metrics.model_dump() if hasattr(metrics, "model_dump") else dict(metrics)


class CallLog:
    """Accumulates one call's record while it runs and persists it."""

    def __init__(self, ctx: CallContext) -> None:
        self.ctx = ctx
        self.bundle: SessionBundle | None = None
        self.started_monotonic = time.monotonic()
        self.metrics: dict[str, dict[str, Any]] = {}
        self.finished: dict[str, TurnRun] = {}
        self.spans_written: set[str] = set()
        self.errors: list[str] = []
        self.recording: Any = None  # engine RecordingResult
        self._lock = asyncio.Lock()

    def attach(self, bundle: SessionBundle) -> None:
        self.bundle = bundle

    # ------------------------------------------------------------------ live hooks

    async def on_recording_saved(self, result: Any) -> None:
        self.recording = result

    async def on_turn_finished(self, turn: TurnRun) -> None:
        self.finished[turn.run_id] = turn
        await self._persist_turns()
        await self._maybe_write_span(turn.run_id)
        await publish(
            f"voice:{self.ctx.call_id}",
            {"type": "turn_finished", "run_id": turn.run_id, "status": turn.status},
            replay=False,
        )

    async def on_event(self, event: Any) -> None:
        if isinstance(event, TurnMetricsEvent):
            run_id = event.metrics.run_id
            if run_id:
                self.metrics[run_id] = _metrics_dict(event.metrics)
                await self._maybe_write_span(run_id)
        elif isinstance(event, VoiceUsageEvent) and self.bundle is not None:
            self.bundle.usage.provider_events.append(event.model_dump(mode="json"))

    def note_error(self, message: str) -> None:
        self.errors.append(message[:500])

    # ------------------------------------------------------------------ persistence

    def _turn_rows(self) -> list[dict[str, Any]]:
        if self.bundle is None:
            return []
        rows = []
        for turn in self.bundle.agent.turns:
            row = turn.as_dict()
            row["metrics"] = self.metrics.get(turn.run_id)
            rows.append(row)
        return rows

    def _transcript(self) -> list[dict[str, Any]]:
        if self.bundle is None:
            return []
        session = self.bundle.session
        started = session.started_at
        out = []
        for entry in session.transcript:
            item = entry.model_dump()
            if started is not None:
                item["offset_ms"] = max(0, round((entry.timestamp - started) * 1000))
            out.append(item)
        return out

    def _model_cost(self) -> Decimal:
        total = Decimal("0")
        for turn in self.finished.values():
            try:
                total += Decimal(turn.cost_usd or "0")
            except ArithmeticError:
                continue
        return total

    async def _persist_turns(self) -> None:
        async with self._lock, system_session() as s:
            call = await s.get(VoiceCall, self.ctx.call_id)
            if call is None:
                return
            call.turns = self._turn_rows()
            call.transcript = self._transcript()
            call.model_cost_usd = self._model_cost()
            first = next((t.user_text for t in self.finished.values() if t.user_text), "")
            if call.conversation_id is not None and first:
                conv = await s.get(Conversation, call.conversation_id)
                if conv is not None and conv.org_id == call.org_id and not conv.title:
                    conv.title = first[:80]

    async def _maybe_write_span(self, run_id: str) -> None:
        if run_id in self.spans_written or run_id not in self.metrics or run_id not in self.finished:
            return
        self.spans_written.add(run_id)
        turn = self.finished[run_id]
        metrics = self.metrics[run_id]
        try:
            run_uuid = uuid.UUID(hex=run_id)
        except ValueError:
            return
        bundle = self.bundle
        async with system_session() as s:
            run = await s.get(Run, run_uuid)
            if run is None or run.org_id != self.ctx.org_id:
                return
            root = (
                (
                    await s.execute(
                        select(Span).where(Span.run_id == run_uuid, Span.parent_call_id.is_(None)).order_by(Span.t0)
                    )
                )
                .scalars()
                .first()
            )
            total_ms = float(metrics.get("turn_total_ms") or 0)
            s.add(
                Span(
                    org_id=self.ctx.org_id,
                    run_id=run_uuid,
                    call_id=f"voice-{run_id}",
                    parent_span_id=root.id if root is not None else None,
                    parent_call_id=root.call_id if root is not None else None,
                    kind="step",
                    name="voice",
                    path=f"{root.path}.voice" if root is not None else "voice",
                    status="cancelled" if metrics.get("interrupted") else "success",
                    input={"user_text": turn.user_text},
                    output={"assistant_text": turn.assistant_text},
                    t0=turn.started_ms,
                    t1=turn.started_ms + int(total_ms),
                    meta={
                        "voice": {
                            "call_id": str(self.ctx.call_id),
                            "transport": self.ctx.transport,
                            "mode": self.ctx.mode,
                            "stt_provider": bundle.meta.get("stt_provider") if bundle else None,
                            "tts_provider": bundle.meta.get("tts_provider") if bundle else None,
                            "metrics": metrics,
                        }
                    },
                )
            )

    async def finalize(self, *, status: str = "completed", error: dict[str, Any] | None = None) -> VoiceCall | None:
        """Persist the final record, charge the speech/line usage and store the recording."""
        bundle = self.bundle
        if bundle is not None:
            await bundle.agent.drain()
        for run_id in list(self.metrics):
            await self._maybe_write_span(run_id)
        usage = bundle.usage if bundle is not None else None
        if usage is not None and usage.telephony_provider and usage.line_seconds == 0:
            usage.line_seconds = time.monotonic() - self.started_monotonic
        costs = usage.costs() if usage is not None else {"total": Decimal("0")}
        voice_cost = costs["total"]
        voice_credits = usd_to_credits(voice_cost) if voice_cost > 0 else Decimal("0")

        recording_key_value: str | None = None
        recording_ms: int | None = None
        result = self.recording
        if result is not None:
            audio_path = Path(result.audio_path)
            try:
                data = await asyncio.to_thread(audio_path.read_bytes)
                key = recording_key(self.ctx.org_id, self.ctx.call_id)
                await get_storage().put(key, data, "audio/mpeg")
                recording_key_value = key
                recording_ms = int(float(result.duration_secs) * 1000)
                for path in (audio_path, Path(result.manifest_path) if result.manifest_path else None):
                    if path is not None:
                        await asyncio.to_thread(path.unlink, True)
            except (OSError, StorageError) as exc:
                log.error("voice.calls.recording_upload_failed", call_id=str(self.ctx.call_id), error=str(exc))
                self.note_error(f"recording: {exc}")

        async with self._lock, system_session() as s:
            call = await s.get(VoiceCall, self.ctx.call_id)
            if call is None:
                return None
            now = _now()
            if call.status not in FINAL_CALL_STATUSES:
                call.status = status
            ended = call.ended_at or now
            call.ended_at = ended
            started = call.answered_at or call.started_at
            if started is not None:
                call.duration_ms = int((ended - started).total_seconds() * 1000)
            call.turns = self._turn_rows()
            call.transcript = self._transcript()
            call.model_cost_usd = self._model_cost()
            if usage is not None:
                call.usage = usage.as_dict()
            call.voice_cost_usd = voice_cost
            call.credits = voice_credits
            if recording_key_value:
                call.recording_key = recording_key_value
                call.recording_ms = recording_ms
            if error is not None:
                call.error = error
            elif self.errors and call.error is None:
                call.error = {"code": "session_errors", "message": "; ".join(self.errors[-5:])}
            if voice_credits > 0:
                await credits.charge_usage(
                    s,
                    org_id=call.org_id,
                    run_id=call.id,
                    project_id=call.project_id,
                    cost_usd=voice_cost,
                    credits=voice_credits,
                    note=f"voz · {call.workforce_name} · {call.transport}",
                )
            if call.conversation_id is not None:
                conv = await s.get(Conversation, call.conversation_id)
                if conv is not None and conv.org_id == call.org_id:
                    conv.updated_at = now
            final = call
        if voice_credits > 0:
            async with system_session() as s:
                await credits.maybe_auto_topup(s, self.ctx.org_id)
        await publish(f"voice:{self.ctx.call_id}", {"type": "call_ended", "status": final.status}, replay=False)
        return final
