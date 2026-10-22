"""Guard in the runtime model gateway (spec 7.13).

``session_for(ctx, body)`` is called by the gateway (through ``guard_bridge``) for every model call. It returns a
:class:`GuardSession` when the run's workforce member has Guard enabled with an enabled playbook, and ``None``
otherwise (calls then go straight to the providers). Engine-internal helper calls of a guarded run (LLM-judge
guardrails, memory summaries: another model and no tools) are not guarded.
"""

from __future__ import annotations

from typing import Any

from messer_common.events import get_redis
from messer_common.logging import get_logger

from .. import gateway, guard_bridge
from ..gateway import CallContext
from .facts import run_key
from .loader import GuardTarget, InvalidPlaybook, is_auxiliary_call, load_target
from .session import GuardSession

log = get_logger("messer.runtime.guard")

__all__ = ["GuardSession", "GuardTarget", "session_for"]


async def _report_invalid(run_id: str, invalid: InvalidPlaybook) -> None:
    """Once per run, leave a visible trace that Guard could not apply the stored playbook."""
    if await get_redis().set(f"guard:{run_key(run_id)}:invalid", "1", nx=True, ex=86400):
        await guard_bridge.record_decision(
            run_id,
            {
                "kind": "error",
                "policy": "invalid_playbook",
                "action": "pass",
                "status": "error",
                "member": invalid.member,
                "output": {"error": invalid.error},
                "on_path": False,
            },
        )


async def session_for(ctx: CallContext, body: dict[str, Any]) -> GuardSession | None:
    if not ctx.run_id:
        return None
    try:
        target = await load_target(ctx.org_id, ctx.project_id, ctx.run_id)
        if target is None:
            return None
        if isinstance(target, InvalidPlaybook):
            await _report_invalid(ctx.run_id, target)
            return None
        if is_auxiliary_call(body, target):
            return None
        info = await gateway._org_info(ctx.org_id)
    except Exception:
        log.exception("guard.session_failed", run_id=ctx.run_id)
        return None
    return GuardSession(ctx, target, info)
