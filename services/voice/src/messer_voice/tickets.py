"""Short-lived, single-use tickets that authorize a connection to the voice service.

Minted by the API (``POST /api/v1/voice/sessions`` and ``/transcriptions``) and by this service for the media
streams of phone calls. A ticket is a compact HS256 token (``messer_common.security.sign_payload``) with
``typ = "voice_ticket"``, a ``purpose`` (``session`` | ``transcribe`` | ``telephony``), a ``jti`` and, for calls,
the ``call`` id. It is redeemed once: the ``jti`` is claimed in Redis.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from messer_common.events import get_redis
from messer_common.security import TokenError, random_token, sign_payload, verify_signed_payload

TICKET_TYPE = "voice_ticket"
Purpose = Literal["session", "transcribe", "telephony"]


class TicketError(Exception):
    """The ticket is missing, malformed, expired, for another purpose or already used."""


@dataclass(frozen=True, slots=True)
class Ticket:
    purpose: Purpose
    jti: str
    call_id: uuid.UUID | None
    org_id: uuid.UUID | None
    claims: dict[str, Any]


def mint(purpose: Purpose, *, ttl_s: int, call_id: uuid.UUID | None = None, **claims: Any) -> str:
    payload: dict[str, Any] = {"typ": TICKET_TYPE, "purpose": purpose, "jti": random_token(16), **claims}
    if call_id is not None:
        payload["call"] = str(call_id)
    return sign_payload(payload, ttl_s)


def _uuid(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise TicketError("malformed ticket") from exc


def decode(token: str, purpose: Purpose) -> Ticket:
    if not token:
        raise TicketError("missing ticket")
    try:
        claims = verify_signed_payload(token)
    except TokenError as exc:
        raise TicketError(f"invalid ticket: {exc}") from exc
    if claims.get("typ") != TICKET_TYPE or claims.get("purpose") != purpose or not claims.get("jti"):
        raise TicketError("invalid ticket")
    return Ticket(
        purpose=purpose,
        jti=str(claims["jti"]),
        call_id=_uuid(claims.get("call")),
        org_id=_uuid(claims.get("org")),
        claims=claims,
    )


async def redeem(token: str, purpose: Purpose) -> Ticket:
    """Verify the ticket and claim it (single use)."""
    ticket = decode(token, purpose)
    claimed = await get_redis().set(f"voice:ticket:{ticket.jti}", "1", nx=True, ex=24 * 3600)
    if not claimed:
        raise TicketError("ticket already used")
    return ticket
