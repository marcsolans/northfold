"""/api/v1/voice — voice sessions (browser tickets), call records, phone numbers, outbound calls, LiveKit rooms.

Live audio flows between the client and the voice service; these endpoints authorize and record it.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, rls_session
from messer_common.db.models import Conversation
from messer_common.db.models.voice import FINAL_CALL_STATUSES, VoiceCall, VoicePhoneNumber
from messer_common.execution import NotDeployed, resolve_target
from messer_common.residency import allowed_provider, org_residency
from messer_common.settings import get_settings
from messer_common.storage import StorageError, get_storage

from ..deps import ensure_project_access, get_db, require_role
from ..errors import ApiError, Conflict, NotFound
from ..services import projects as project_svc
from ..services import voice as svc
from ..services.limits import require_feature

router = APIRouter(prefix="/voice", tags=["voice"])

Environment = Literal["development", "production"]
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


# ------------------------------------------------------------------------------------------- models


class StatusOut(BaseModel):
    mode: Literal["audio", "text"]
    audio: dict[str, Any]
    dictation: dict[str, Any]
    telephony: dict[str, bool]
    livekit: bool
    region: str | None
    residency: str | None
    missing: list[dict[str, str]]


class SessionIn(BaseModel):
    project_id: uuid.UUID
    workforce: str = Field(min_length=1, max_length=80)
    environment: Environment = "development"
    conversation_id: uuid.UUID | None = None
    mode: Literal["auto", "audio", "text"] = "auto"
    record: bool = False
    consent: bool = False
    language: str | None = Field(default=None, max_length=16)


class SessionOut(BaseModel):
    call_id: uuid.UUID
    conversation_id: uuid.UUID
    ticket: str
    ws_url: str
    expires_in: int
    mode: Literal["audio", "text"]
    language: str
    voice: str
    greeting: str
    stt: str | None
    tts: str | None
    recording: bool


class TranscriptionIn(BaseModel):
    language: str | None = Field(default=None, max_length=16)


class TranscriptionOut(BaseModel):
    mode: Literal["server", "browser"]
    ticket: str | None
    ws_url: str | None
    expires_in: int
    language: str
    stt: str | None


class CallSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workforce_name: str
    environment: str
    conversation_id: uuid.UUID | None
    phone_number_id: uuid.UUID | None
    transport: str
    channel: str
    mode: str
    direction: str
    status: str
    from_number: str | None
    to_number: str | None
    language: str
    turns: int
    duration_ms: int | None
    voice_cost_usd: Decimal
    model_cost_usd: Decimal
    total_cost_usd: Decimal
    has_recording: bool
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class CallDetail(CallSummary):
    stt_provider: str | None
    tts_provider: str | None
    recording_consent: str | None
    recording_ms: int | None
    transcript: list[dict[str, Any]]
    turn_details: list[dict[str, Any]]
    usage: dict[str, Any]
    credits: Decimal
    error: dict[str, Any] | None
    latency: dict[str, float | None]


class CallPage(BaseModel):
    items: list[CallSummary]
    total: int


class OutboundIn(BaseModel):
    phone_number_id: uuid.UUID
    to: str = Field(min_length=6, max_length=20)
    workforce: str | None = Field(default=None, max_length=80)
    greeting: str | None = Field(default=None, max_length=500)


class NumberOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workforce_name: str
    environment: str
    provider: str
    number: str
    label: str
    status: str
    purchased: bool
    record_calls: bool
    greeting: str
    error: str | None
    created_at: datetime


class ProviderNumber(BaseModel):
    provider: str
    number: str
    external_id: str
    label: str
    locality: str | None = None
    country: str | None = None
    voice: bool = True
    assigned: bool = False


class NumberIn(BaseModel):
    project_id: uuid.UUID
    provider: Literal["twilio", "telnyx"]
    number: str = Field(min_length=6, max_length=20)
    external_id: str | None = Field(default=None, max_length=120)
    buy: bool = False
    workforce: str = Field(min_length=1, max_length=80)
    environment: Environment = "production"
    label: str = Field(default="", max_length=200)
    record_calls: bool = False
    greeting: str = Field(default="", max_length=500)


class NumberPatch(BaseModel):
    workforce: str | None = Field(default=None, max_length=80)
    environment: Environment | None = None
    label: str | None = Field(default=None, max_length=200)
    record_calls: bool | None = None
    greeting: str | None = Field(default=None, max_length=500)


class LivekitIn(BaseModel):
    project_id: uuid.UUID
    workforce: str = Field(min_length=1, max_length=80)
    environment: Environment = "development"


class LivekitOut(BaseModel):
    call_id: uuid.UUID
    conversation_id: uuid.UUID
    url: str
    room: str
    token: str
    identity: str


class VoicesOut(BaseModel):
    provider: str
    default: str | None = None
    items: list[dict[str, Any]]


# ------------------------------------------------------------------------------------------- helpers


def _normalize(number: str) -> str:
    raw = re.sub(r"[^\d+]", "", number.strip())
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not _E164.match(raw):
        raise ApiError("El número debe estar en formato internacional (+34…)", code="invalid_phone_number")
    return raw


def _summary(call: VoiceCall) -> CallSummary:
    return CallSummary(
        id=call.id,
        project_id=call.project_id,
        workforce_name=call.workforce_name,
        environment=call.environment,
        conversation_id=call.conversation_id,
        phone_number_id=call.phone_number_id,
        transport=call.transport,
        channel=call.channel,
        mode=call.mode,
        direction=call.direction,
        status=call.status,
        from_number=call.from_number,
        to_number=call.to_number,
        language=call.language,
        turns=len(call.turns or []),
        duration_ms=call.duration_ms,
        voice_cost_usd=call.voice_cost_usd,
        model_cost_usd=call.model_cost_usd,
        total_cost_usd=svc.call_cost(call),
        has_recording=bool(call.recording_key),
        started_at=call.started_at,
        ended_at=call.ended_at,
        created_at=call.created_at,
    )


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _latency(call: VoiceCall) -> dict[str, float | None]:
    keys = {
        "speech_end_to_transcript_ms": "stt",
        "eou_to_llm_first_token_ms": "llm_first_token",
        "eou_to_first_audio_ms": "first_audio",
        "turn_total_ms": "turn_total",
    }
    collected: dict[str, list[float]] = {name: [] for name in keys.values()}
    for turn in call.turns or []:
        metrics = turn.get("metrics") if isinstance(turn, dict) else None
        if not isinstance(metrics, dict):
            continue
        for key, name in keys.items():
            value = metrics.get(key)
            if isinstance(value, int | float):
                collected[name].append(float(value))
    return {f"avg_{name}_ms": _avg(values) for name, values in collected.items()}


def _detail(call: VoiceCall) -> CallDetail:
    return CallDetail(
        **_summary(call).model_dump(),
        stt_provider=call.stt_provider,
        tts_provider=call.tts_provider,
        recording_consent=call.recording_consent,
        recording_ms=call.recording_ms,
        transcript=list(call.transcript or []),
        turn_details=list(call.turns or []),
        usage=dict(call.usage or {}),
        credits=call.credits,
        error=call.error,
        latency=_latency(call),
    )


def _number_out(row: VoicePhoneNumber) -> NumberOut:
    return NumberOut(
        id=row.id,
        project_id=row.project_id,
        workforce_name=row.workforce_name,
        environment=row.environment,
        provider=row.provider,
        number=row.number,
        label=row.label,
        status=row.status,
        purchased=row.purchased,
        record_calls=row.record_calls,
        greeting=row.greeting,
        error=row.error,
        created_at=row.created_at,
    )


async def _call(session: AsyncSession, call_id: uuid.UUID) -> VoiceCall:
    call = await session.get(VoiceCall, call_id)
    if call is None:
        raise NotFound("Llamada no encontrada")
    return call


async def _number(session: AsyncSession, number_id: uuid.UUID) -> VoicePhoneNumber:
    row = await session.get(VoicePhoneNumber, number_id)
    if row is None:
        raise NotFound("Número no encontrado")
    return row


async def _check_target(session: AsyncSession, project_id: uuid.UUID, environment: str) -> None:
    try:
        await resolve_target(session, project_id, environment)
    except NotDeployed as exc:
        raise Conflict(str(exc), code="not_deployed") from exc


# ------------------------------------------------------------------------------------------- status


@router.get("/status", response_model=StatusOut)
async def voice_status(
    principal: Principal = Depends(require_role("viewer")), session: AsyncSession = Depends(get_db)
) -> StatusOut:
    assert principal.org_id is not None
    residency = await org_residency(session, principal.org_id)
    return StatusOut(**svc.status(residency))


@router.get("/voices", response_model=VoicesOut)
async def list_voices(
    language: str = Query(default="es", max_length=16),
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> VoicesOut:
    assert principal.org_id is not None
    residency = await org_residency(session, principal.org_id)
    return VoicesOut(**await svc.voices(residency, language))


# ------------------------------------------------------------------------------------------- browser sessions


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_session(body: SessionIn, principal: Principal = Depends(require_role("builder"))) -> SessionOut:
    """Start a browser voice call with an agent: returns a single-use ticket for the voice service WebSocket."""
    ensure_project_access(principal, body.project_id)
    if body.record and not body.consent:
        raise ApiError("Para grabar la llamada hace falta el consentimiento", code="recording_consent_required")
    assert principal.org_id is not None
    async with rls_session(principal) as session:
        project = await project_svc.get_project(session, body.project_id)
        member = await svc.ensure_agent(session, project, body.workforce)
        voice_cfg = svc.agent_voice(member)
        if body.environment == "production":
            await require_feature(session, project.org_id, "voice")
            if not voice_cfg["enabled"]:
                raise ApiError("Activa la voz en la configuración del agente", code="voice_disabled")
        await _check_target(session, project.id, body.environment)
        residency = await org_residency(session, project.org_id)
        audio = svc.audio_providers(residency)
        mode: Literal["audio", "text"] = "audio" if audio is not None and body.mode != "text" else "text"
        if body.mode == "audio" and audio is None:
            raise svc.VoiceUnavailable("No hay proveedores de voz configurados para audio", code="audio_unavailable")
        call_id = uuid.uuid4()
        if body.conversation_id is not None:
            conv = await session.get(Conversation, body.conversation_id)
            if (
                conv is None
                or conv.project_id != project.id
                or conv.workforce_name != member.name
                or conv.provider not in ("studio", "voice")
                or conv.external_user_id != str(principal.user_id)
            ):
                raise NotFound("Conversación no encontrada")
        else:
            conv = Conversation(
                org_id=project.org_id,
                project_id=project.id,
                channel_key=f"voice:{call_id}",
                provider="voice",
                workforce_name=member.name,
                external_user_id=str(principal.user_id),
                external_thread_id=str(call_id),
                title="",
            )
            session.add(conv)
            await session.flush()
        language = (body.language or voice_cfg["language"] or "es").strip()
        call = VoiceCall(
            id=call_id,
            org_id=project.org_id,
            project_id=project.id,
            workforce_name=member.name,
            environment=body.environment,
            conversation_id=conv.id,
            user_id=principal.user_id,
            transport="browser",
            channel="voice",
            mode=mode,
            direction="inbound",
            status="pending",
            language=language,
            stt_provider=audio[0].provider if audio and mode == "audio" else "browser",
            tts_provider=audio[1].provider if audio and mode == "audio" else "browser",
            record=body.record and mode == "audio",
            recording_consent="explicit" if body.record and mode == "audio" else None,
            started_at=datetime.now(UTC),
        )
        session.add(call)
        await audit.record(
            session,
            action="voice.session_started",
            principal=principal,
            entity_type="voice_call",
            entity_id=call_id,
            diff={"workforce": member.name, "environment": body.environment, "mode": mode, "record": call.record},
        )
        conversation_id = conv.id
    ticket = svc.mint_ticket("session", ttl_s=svc.TICKET_TTL_S, call_id=call_id, org=str(project.org_id))
    return SessionOut(
        call_id=call_id,
        conversation_id=conversation_id,
        ticket=ticket,
        ws_url=svc.session_ws_url(ticket),
        expires_in=svc.TICKET_TTL_S,
        mode=mode,
        language=language,
        voice=voice_cfg["voice"],
        greeting=voice_cfg["greeting"],
        stt=audio[0].label if audio and mode == "audio" else None,
        tts=audio[1].label if audio and mode == "audio" else None,
        recording=call.record,
    )


@router.post("/transcriptions", response_model=TranscriptionOut, status_code=201)
async def create_transcription(
    body: TranscriptionIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> TranscriptionOut:
    """Dictation for the Composer: a ticket for the voice service STT, or ``browser`` (Web Speech API)."""
    assert principal.org_id is not None
    residency = await org_residency(session, principal.org_id)
    status = svc.status(residency)
    language = (body.language or "es").strip()
    if status["dictation"]["mode"] != "server":
        return TranscriptionOut(mode="browser", ticket=None, ws_url=None, expires_in=0, language=language, stt=None)
    ticket = svc.mint_ticket(
        "transcribe", ttl_s=svc.TICKET_TTL_S, org=str(principal.org_id), user=str(principal.user_id), language=language
    )
    return TranscriptionOut(
        mode="server",
        ticket=ticket,
        ws_url=svc.transcribe_ws_url(ticket),
        expires_in=svc.TICKET_TTL_S,
        language=language,
        stt=status["dictation"]["stt"],
    )


# ------------------------------------------------------------------------------------------- calls


@router.get("/calls", response_model=CallPage)
async def list_calls(
    project_id: uuid.UUID | None = None,
    workforce: str | None = None,
    conversation_id: uuid.UUID | None = None,
    phone_number_id: uuid.UUID | None = None,
    transport: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> CallPage:
    query = select(VoiceCall)
    if principal.project_id is not None:
        query = query.where(VoiceCall.project_id == principal.project_id)
    if project_id is not None:
        query = query.where(VoiceCall.project_id == project_id)
    if workforce:
        query = query.where(VoiceCall.workforce_name == workforce)
    if conversation_id is not None:
        query = query.where(VoiceCall.conversation_id == conversation_id)
    if phone_number_id is not None:
        query = query.where(VoiceCall.phone_number_id == phone_number_id)
    if transport:
        query = query.where(VoiceCall.transport == transport)
    total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    rows = (
        (await session.execute(query.order_by(VoiceCall.created_at.desc()).limit(limit).offset(offset))).scalars().all()
    )
    return CallPage(items=[_summary(r) for r in rows], total=int(total))


@router.get("/calls/{call_id}", response_model=CallDetail)
async def get_call(
    call_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), session: AsyncSession = Depends(get_db)
) -> CallDetail:
    call = await _call(session, call_id)
    ensure_project_access(principal, call.project_id)
    return _detail(call)


@router.get("/calls/{call_id}/recording")
async def get_recording(
    call_id: uuid.UUID, principal: Principal = Depends(require_role("viewer")), session: AsyncSession = Depends(get_db)
) -> Response:
    call = await _call(session, call_id)
    ensure_project_access(principal, call.project_id)
    if not call.recording_key:
        raise NotFound("Esta llamada no tiene grabación")
    try:
        data = await get_storage().get(call.recording_key)
    except StorageError as exc:
        raise NotFound("La grabación ya no está disponible") from exc
    await audit.record(
        session, action="voice.recording_accessed", principal=principal, entity_type="voice_call", entity_id=call.id
    )
    return Response(
        content=data,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, no-store", "Content-Disposition": f'inline; filename="{call.id}.mp3"'},
    )


@router.delete("/calls/{call_id}/recording", status_code=204)
async def delete_recording(
    call_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), session: AsyncSession = Depends(get_db)
) -> Response:
    call = await _call(session, call_id)
    ensure_project_access(principal, call.project_id)
    if not call.recording_key:
        raise NotFound("Esta llamada no tiene grabación")
    try:
        await get_storage().delete(call.recording_key)
    except StorageError as exc:
        raise ApiError(f"No se pudo borrar la grabación: {exc}", code="storage_error", status_code=502) from exc
    await audit.record(
        session,
        action="voice.recording_deleted",
        principal=principal,
        entity_type="voice_call",
        entity_id=call.id,
        diff={"recording_key": call.recording_key},
    )
    call.recording_key = None
    call.recording_ms = None
    return Response(status_code=204)


@router.post("/calls", response_model=CallSummary, status_code=201)
async def place_call(body: OutboundIn, principal: Principal = Depends(require_role("builder"))) -> CallSummary:
    """Outbound phone call from one of the project's numbers; the agent speaks first if it has a greeting."""
    to = _normalize(body.to)
    assert principal.org_id is not None
    async with rls_session(principal) as session:
        number = await _number(session, body.phone_number_id)
        ensure_project_access(principal, number.project_id)
        await require_feature(session, number.org_id, "voice")
        if number.status != "active":
            raise Conflict("El número no está activo", code="number_inactive")
        project = await project_svc.get_project(session, number.project_id)
        member = await svc.ensure_agent(session, project, body.workforce or number.workforce_name)
        await _check_target(session, project.id, number.environment)
        residency = await org_residency(session, number.org_id)
        if svc.audio_providers(residency) is None:
            raise svc.VoiceUnavailable("No hay proveedores de voz configurados", code="audio_unavailable")
        conv = await svc.phone_conversation(session, number=number, party=to)
        meta: dict[str, Any] = {}
        if body.greeting:
            meta["greeting"] = body.greeting
        elif number.greeting:
            meta["greeting"] = number.greeting
        call = VoiceCall(
            org_id=number.org_id,
            project_id=number.project_id,
            workforce_name=member.name,
            environment=number.environment,
            conversation_id=conv.id,
            phone_number_id=number.id,
            user_id=principal.user_id,
            transport=number.provider,
            channel="phone",
            mode="audio",
            direction="outbound",
            status="pending",
            from_number=number.number,
            to_number=to,
            language=svc.agent_voice(member)["language"],
            record=number.record_calls,
            recording_consent="notice" if number.record_calls else None,
            started_at=datetime.now(UTC),
            meta=meta,
        )
        session.add(call)
        await session.flush()
        conv.external_thread_id = str(call.id)
        await audit.record(
            session,
            action="voice.call_placed",
            principal=principal,
            entity_type="voice_call",
            entity_id=call.id,
            diff={"from": number.number, "to": to, "workforce": member.name},
        )
        call_id = call.id
    try:
        external = await svc.dial(call, number)
    except ApiError as exc:
        async with rls_session(principal) as session:
            failed = await _call(session, call_id)
            failed.status = "failed"
            failed.error = {"code": exc.code, "message": exc.message}
            failed.ended_at = datetime.now(UTC)
        raise
    async with rls_session(principal) as session:
        placed = await _call(session, call_id)
        placed.external_call_id = external or None
        placed.status = "ringing"
        await session.flush()
        return _summary(placed)


@router.post("/calls/{call_id}/hangup", response_model=CallSummary)
async def hangup_call(call_id: uuid.UUID, principal: Principal = Depends(require_role("builder"))) -> CallSummary:
    async with rls_session(principal) as session:
        call = await _call(session, call_id)
        ensure_project_access(principal, call.project_id)
        if call.status in FINAL_CALL_STATUSES:
            return _summary(call)
        if call.transport not in ("twilio", "telnyx"):
            raise ApiError("Solo se pueden colgar llamadas telefónicas", code="not_a_phone_call")
        await audit.record(
            session, action="voice.call_hung_up", principal=principal, entity_type="voice_call", entity_id=call.id
        )
        snapshot = call
    await svc.hangup(snapshot)
    async with rls_session(principal) as session:
        return _summary(await _call(session, call_id))


# ------------------------------------------------------------------------------------------- phone numbers


@router.get("/numbers", response_model=list[NumberOut])
async def list_numbers(
    project_id: uuid.UUID | None = None,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> list[NumberOut]:
    query = select(VoicePhoneNumber).order_by(VoicePhoneNumber.created_at)
    scope = principal.project_id or project_id
    if scope is not None:
        query = query.where(VoicePhoneNumber.project_id == scope)
    rows = (await session.execute(query)).scalars().all()
    return [_number_out(r) for r in rows]


@router.get("/numbers/available", response_model=list[ProviderNumber])
async def available_numbers(
    provider: Literal["twilio", "telnyx"],
    country: str = Query(default="ES", min_length=2, max_length=2),
    contains: str | None = Query(default=None, max_length=12, pattern=r"^\d*$"),
    principal: Principal = Depends(require_role("admin")),
) -> list[ProviderNumber]:
    items = await svc.search_available(provider, country=country, contains=contains or None)
    return [ProviderNumber(**i) for i in items]


@router.get("/numbers/owned", response_model=list[ProviderNumber])
async def owned_numbers(
    provider: Literal["twilio", "telnyx"],
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_db),
) -> list[ProviderNumber]:
    """Numbers already in the provider account; ``assigned`` marks the ones a project uses (any organization)."""
    items = await svc.owned_numbers(provider)
    assigned = set(
        (await session.execute(select(VoicePhoneNumber.number).where(VoicePhoneNumber.provider == provider))).scalars()
    )
    return [ProviderNumber(**i, assigned=i["number"] in assigned) for i in items]


@router.post("/numbers", response_model=NumberOut, status_code=201)
async def assign_number(body: NumberIn, principal: Principal = Depends(require_role("admin"))) -> NumberOut:
    """Buy a number (``buy``) or take one the account owns, route it to the voice service and assign an agent."""
    ensure_project_access(principal, body.project_id)
    number = _normalize(body.number)
    async with rls_session(principal) as session:
        project = await project_svc.get_project(session, body.project_id)
        await require_feature(session, project.org_id, "voice")
        member = await svc.ensure_agent(session, project, body.workforce)
        if not svc.agent_voice(member)["enabled"]:
            raise ApiError("Activa la voz en la configuración del agente", code="voice_disabled")
        if not svc.telephony_configured()[body.provider]:
            raise svc.VoiceUnavailable(f"{body.provider} no está configurado", code="telephony_not_configured")
        taken = (
            await session.execute(
                select(func.count())
                .select_from(VoicePhoneNumber)
                .where(VoicePhoneNumber.provider == body.provider, VoicePhoneNumber.number == number)
            )
        ).scalar_one()
        if taken:
            raise Conflict("Ese número ya está asignado", code="number_taken")
        org_id = project.org_id
    provisioned = await svc.provision_number(body.provider, number=number, external_id=body.external_id, buy=body.buy)
    async with rls_session(principal) as session:
        row = VoicePhoneNumber(
            org_id=org_id,
            project_id=body.project_id,
            workforce_name=body.workforce,
            environment=body.environment,
            provider=body.provider,
            number=number,
            external_id=str(provisioned.get("external_id") or ""),
            label=body.label or str(provisioned.get("label") or ""),
            status="active",
            purchased=body.buy,
            record_calls=body.record_calls,
            greeting=body.greeting,
            created_by=principal.user_id,
        )
        session.add(row)
        try:
            await session.flush()
        except IntegrityError as exc:
            raise Conflict("Ese número ya está asignado", code="number_taken") from exc
        await audit.record(
            session,
            action="voice.number_purchased" if body.buy else "voice.number_assigned",
            principal=principal,
            entity_type="voice_phone_number",
            entity_id=row.id,
            diff={"provider": body.provider, "number": number, "workforce": body.workforce},
        )
        await session.refresh(row)
        return _number_out(row)


@router.patch("/numbers/{number_id}", response_model=NumberOut)
async def update_number(
    number_id: uuid.UUID,
    body: NumberPatch,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> NumberOut:
    row = await _number(session, number_id)
    ensure_project_access(principal, row.project_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("workforce"):
        project = await project_svc.get_project(session, row.project_id)
        member = await svc.ensure_agent(session, project, changes["workforce"])
        row.workforce_name = member.name
    for key in ("environment", "label", "record_calls", "greeting"):
        if key in changes and changes[key] is not None:
            setattr(row, key, changes[key])
    await audit.record(
        session,
        action="voice.number_updated",
        principal=principal,
        entity_type="voice_phone_number",
        entity_id=row.id,
        diff=changes,
    )
    await session.flush()
    await session.refresh(row)
    return _number_out(row)


@router.delete("/numbers/{number_id}", status_code=204)
async def remove_number(
    number_id: uuid.UUID,
    release: bool = Query(default=False, description="Also release the number at the provider (stops billing)"),
    principal: Principal = Depends(require_role("admin")),
) -> Response:
    async with rls_session(principal) as session:
        row = await _number(session, number_id)
        ensure_project_access(principal, row.project_id)
        snapshot = VoicePhoneNumber(
            id=row.id,
            org_id=row.org_id,
            project_id=row.project_id,
            workforce_name=row.workforce_name,
            provider=row.provider,
            number=row.number,
            external_id=row.external_id,
        )
    if release:
        await svc.release_number(snapshot)
    async with rls_session(principal) as session:
        row = await _number(session, number_id)
        await audit.record(
            session,
            action="voice.number_released" if release else "voice.number_unassigned",
            principal=principal,
            entity_type="voice_phone_number",
            entity_id=row.id,
            diff={"provider": row.provider, "number": row.number},
        )
        await session.delete(row)
    return Response(status_code=204)


# ------------------------------------------------------------------------------------------- LiveKit


@router.post("/livekit/sessions", response_model=LivekitOut, status_code=201)
async def create_livekit_session(
    body: LivekitIn, principal: Principal = Depends(require_role("builder"))
) -> LivekitOut:
    """A LiveKit room with the agent in it, and a token for the caller to join."""
    ensure_project_access(principal, body.project_id)
    if not svc.livekit_configured():
        raise svc.VoiceUnavailable("LiveKit no está configurado", code="livekit_not_configured")
    async with rls_session(principal) as session:
        project = await project_svc.get_project(session, body.project_id)
        await require_feature(session, project.org_id, "voice")
        member = await svc.ensure_agent(session, project, body.workforce)
        await _check_target(session, project.id, body.environment)
        residency = await org_residency(session, project.org_id)
        if svc.audio_providers(residency) is None or not allowed_provider(residency, "voice", "livekit"):
            raise svc.VoiceUnavailable("No hay proveedores de voz configurados", code="audio_unavailable")
        call_id = uuid.uuid4()
        conv = Conversation(
            org_id=project.org_id,
            project_id=project.id,
            channel_key=f"voice:{call_id}",
            provider="voice",
            workforce_name=member.name,
            external_user_id=str(principal.user_id),
            external_thread_id=str(call_id),
            title="",
        )
        session.add(conv)
        await session.flush()
        session.add(
            VoiceCall(
                id=call_id,
                org_id=project.org_id,
                project_id=project.id,
                workforce_name=member.name,
                environment=body.environment,
                conversation_id=conv.id,
                user_id=principal.user_id,
                transport="livekit",
                channel="voice",
                mode="audio",
                direction="inbound",
                status="pending",
                language=svc.agent_voice(member)["language"],
                started_at=datetime.now(UTC),
            )
        )
        await audit.record(
            session,
            action="voice.livekit_session_started",
            principal=principal,
            entity_type="voice_call",
            entity_id=call_id,
            diff={"workforce": member.name, "environment": body.environment},
        )
        conversation_id = conv.id
    try:
        await svc.livekit_join(call_id)
    except ApiError as exc:
        async with rls_session(principal) as session:
            failed = await _call(session, call_id)
            failed.status = "failed"
            failed.error = {"code": exc.code, "message": exc.message}
            failed.ended_at = datetime.now(UTC)
        raise
    room = svc.livekit_room(call_id)
    identity = f"user-{principal.user_id}"
    return LivekitOut(
        call_id=call_id,
        conversation_id=conversation_id,
        url=get_settings().livekit_url,
        room=room,
        token=svc.livekit_token(identity, room, name=principal.email or identity),
        identity=identity,
    )
