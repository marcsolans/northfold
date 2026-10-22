"""Demo outbox: delivery for demo channels and simulator conversations.

Nothing leaves the platform. The reply is recorded as an outbound ``channel_messages`` row with status
``stored`` (the readable answer is already in ``conversations.messages``), so the simulator and the inbox show
exactly what a real user would have received, split the way the provider would split it.
"""

from __future__ import annotations

import uuid

from .base import ChannelAdapter


def store(adapter: ChannelAdapter, text: str) -> tuple[list[str], list[str]]:
    """(parts as the provider would send them, synthetic message ids)."""
    parts = adapter.parts(text)
    return parts, [f"demo-{uuid.uuid4().hex}" for _ in parts]
