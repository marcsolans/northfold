"""Connector → knowledge base syncs (``Jobs.RUN_SYNC``)."""

from __future__ import annotations

import uuid
from typing import Any

from messer_api.services.connector_syncs import execute_sync


async def run_sync(_ctx: dict[str, Any], sync_id: str) -> dict[str, Any]:
    """Run one sync. Connector failures are stored on the ``syncs`` row and returned, never raised."""
    return await execute_sync(uuid.UUID(sync_id))


JOBS = [run_sync]
