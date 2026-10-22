"""Service-to-service endpoints (``/internal/v1``), authenticated with the platform service token."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from messer_common.security import constant_time_equals
from messer_common.settings import get_settings

from . import livekit
from .runner import ACTIVE
from .status import voice_status


async def require_service(request: Request) -> None:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token or not constant_time_equals(token, get_settings().service_token):
        raise HTTPException(status_code=401, detail="invalid service token")


router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_service)])


@router.get("/status")
async def status() -> dict[str, Any]:
    return {**voice_status(), "sessions": len(ACTIVE)}


@router.get("/sessions")
async def sessions() -> dict[str, Any]:
    return {
        "items": [
            {
                "call_id": key,
                "transport": bundle.meta.get("transport"),
                "mode": bundle.meta.get("mode"),
                "turns": len(bundle.agent.turns),
            }
            for key, bundle in ACTIVE.items()
        ]
    }


class LivekitJoin(BaseModel):
    call_id: uuid.UUID


@router.post("/livekit/join")
async def livekit_join(body: LivekitJoin) -> dict[str, Any]:
    try:
        return await livekit.join(body.call_id)
    except livekit.LivekitError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
