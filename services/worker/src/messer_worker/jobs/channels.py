"""Channel jobs: process inbound messages from WhatsApp, Slack, Teams, Telegram, email and the simulator."""

from __future__ import annotations

import uuid
from typing import Any

from arq import Retry

from messer_common.channels.processing import RetryLater, process_inbound
from messer_common.logging import get_logger

log = get_logger("messer.worker.channels")

MAX_TRIES = 5  # arq default max_tries: the fifth try is the last one


async def channel_inbound(ctx: dict[str, Any], message_id: str) -> dict[str, Any]:
    """Run the channel's agent for one inbound message and deliver the answer (idempotent per message)."""
    job_try = int(ctx.get("job_try") or 1)
    try:
        return await process_inbound(uuid.UUID(message_id), final_attempt=job_try >= MAX_TRIES)
    except RetryLater as exc:
        log.warning("channel.inbound_retry", message_id=message_id, attempt=job_try, reason=str(exc))
        raise Retry(defer=min(exc.defer_s * job_try, 300)) from exc


JOBS = [channel_inbound]
