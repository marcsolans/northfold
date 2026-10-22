"""GDPR jobs: ``data_export`` (zip in storage + email with a signed link) and ``data_delete`` (verifiable
deletion report stored in ``data_requests.report``). Producers: ``/api/v1/data-requests`` and the backoffice."""

from __future__ import annotations

import uuid
from typing import Any

from messer_api.services.data_requests import run_delete, run_export


async def data_export(_ctx: dict[str, Any], request_id: str) -> str | None:
    row = await run_export(uuid.UUID(request_id))
    return row.status if row is not None else None


async def data_delete(_ctx: dict[str, Any], request_id: str) -> str | None:
    row = await run_delete(uuid.UUID(request_id))
    return row.status if row is not None else None


JOBS = [data_export, data_delete]
