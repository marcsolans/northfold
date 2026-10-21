"""Deployment pipeline (evals gate → point the environment at the version → warm the runtime)."""

from __future__ import annotations

import uuid
from typing import Any

from messer_api.services.deployments import run_pipeline


async def deploy(_ctx: dict[str, Any], deployment_id: str, force: bool = False, skip_evals: bool = False) -> str:
    dep = await run_pipeline(uuid.UUID(deployment_id), force=force, skip_evals=skip_evals)
    return dep.status


JOBS = [deploy]
