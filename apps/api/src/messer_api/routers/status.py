"""GET /api/v1/status/public: public status page data (service health with 90-day history)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from messer_common.db import system_session

from ..ratelimit import rate_limit
from ..services.service_health import public_summary

router = APIRouter(prefix="/status", tags=["status"])

PublicStatus = Literal["operational", "degraded", "down", "unknown"]


class DayOut(BaseModel):
    date: str
    status: Literal["operational", "degraded", "down", "no_data"]
    uptime: float | None


class ServiceOut(BaseModel):
    key: str
    status: PublicStatus
    latency_ms: int | None
    checked_at: str | None
    uptime_90d: float | None
    days: list[DayOut]


class IncidentOut(BaseModel):
    service: str
    status: Literal["degraded", "down"]
    started_at: str
    resolved_at: str | None


class PublicStatusOut(BaseModel):
    status: PublicStatus
    updated_at: str | None
    generated_at: str
    history_days: int
    services: list[ServiceOut]
    incidents: list[IncidentOut]


@router.get("/public", response_model=PublicStatusOut, dependencies=[Depends(rate_limit("status_public", 120, 60))])
async def public_status(response: Response) -> dict[str, Any]:
    # service_health is a system table (no RLS policy for the app role): read on the owner connection.
    async with system_session() as s:
        summary = await public_summary(s)
    response.headers["Cache-Control"] = "public, max-age=30"
    return summary
