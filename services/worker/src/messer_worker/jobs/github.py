"""GitHub sync jobs: ``github_push`` (after Messer commits, debounced per project) and ``github_pull`` (after a
push to the connected branch). Both run the same two-way sync (``messer_api.services.github.sync_project``)."""

from __future__ import annotations

import uuid
from typing import Any

from arq import Retry

from messer_api.services import github as svc
from messer_common.logging import get_logger
from messer_common.projects_repo import register_commit_hook

log = get_logger("messer.worker.github")

# Commits made by worker jobs (Composer builders, template clones…) push too.
register_commit_hook(svc.on_commit)

MAX_BUSY_RETRIES = 10


async def _run(ctx: dict[str, Any], project_id: str, reason: str) -> dict[str, Any]:
    try:
        result = await svc.sync_project(uuid.UUID(project_id), reason=reason)
    except svc.SyncBusy as exc:
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < MAX_BUSY_RETRIES:
            raise Retry(defer=5 * attempt) from exc
        log.warning("github.sync_busy", project_id=project_id, reason=reason)
        return {"status": "busy"}
    log.info(
        "github.synced",
        project_id=project_id,
        reason=reason,
        status=result.get("status"),
        pushed=result.get("pushed"),
        pulled=bool(result.get("pulled")),
    )
    return result


async def github_push(ctx: dict[str, Any], project_id: str) -> dict[str, Any]:
    return await _run(ctx, project_id, "push")


async def github_pull(ctx: dict[str, Any], project_id: str, after: str | None = None) -> dict[str, Any]:
    return await _run(ctx, project_id, "pull")


JOBS = [github_push, github_pull]
