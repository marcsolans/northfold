"""Extension point between the model gateway and Guard (behaviour control, spec 7.13).

The gateway asks for a Guard session for every model call. When the calling agent has Guard enabled, the session
decides the turn before the call (route to the small or large model, answer deterministically, rewrite the
request) and validates the model's message after it (policies, JSON Schema). Without the ``messer_runtime.guard``
package, or for agents without Guard, calls go straight to the providers.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from messer_common.events import get_redis

if TYPE_CHECKING:
    from .gateway import CallContext

MEMBER_KEY = "run:{run_id}:member"


@dataclass(slots=True)
class BeforeOutcome:
    body: dict[str, Any]
    model: str | None = None  # provider/model override (model routing)
    message: dict[str, Any] | None = None  # answer without calling a model (deterministic policy)
    meta: dict[str, Any] = field(default_factory=dict)


class GuardSession(Protocol):
    async def before(self, body: dict[str, Any]) -> BeforeOutcome: ...

    async def after(self, body: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]: ...


async def remember_member(run_id: str, project_id: str, member: str) -> None:
    """Called when a run starts so model calls of that run can be attributed to the workforce member."""
    await get_redis().set(MEMBER_KEY.format(run_id=run_id), f"{project_id}:{member}", ex=86400)


async def member_of(run_id: str | None) -> tuple[str, str] | None:
    if not run_id:
        return None
    raw = await get_redis().get(MEMBER_KEY.format(run_id=run_id))
    if not raw or ":" not in raw:
        return None
    project_id, member = str(raw).split(":", 1)
    return project_id, member


async def session_for(ctx: CallContext, body: dict[str, Any]) -> GuardSession | None:
    try:
        module = importlib.import_module("messer_runtime.guard")
    except ModuleNotFoundError:
        return None
    factory = getattr(module, "session_for", None)
    if factory is None:
        return None
    session: GuardSession | None = await factory(ctx, body)
    return session


GUARD_KEY = "run:{run_id}:guard"


async def record_decision(run_id: str | None, decision: dict[str, Any]) -> None:
    """Keep one Guard decision of a run (policy, verdicts, routed model, latency, cost); persisted as a span."""
    if not run_id:
        return
    import json
    import time

    key = GUARD_KEY.format(run_id=run_id)
    r = get_redis()
    await r.rpush(key, json.dumps({"t": int(time.time() * 1000), **decision}, default=str))  # type: ignore[misc]
    await r.expire(key, 86400)


async def decisions(run_id: str) -> list[dict[str, Any]]:
    import json

    raw = await get_redis().lrange(GUARD_KEY.format(run_id=run_id), 0, -1)  # type: ignore[misc]
    return [json.loads(item) for item in raw or []]
