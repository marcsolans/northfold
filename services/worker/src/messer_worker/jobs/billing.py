"""Billing jobs: ``auto_topup`` (enqueued by ``messer_common.credits.maybe_auto_topup`` after usage is charged)."""

from __future__ import annotations

import uuid
from typing import Any

from messer_api.services.billing import execute_auto_topup


async def auto_topup(_ctx: dict[str, Any], org_id: str) -> dict[str, Any]:
    """Buy the configured credit pack if the organization is still below its threshold (re-checked under lock)."""
    return await execute_auto_topup(uuid.UUID(org_id))


JOBS = [auto_topup]
