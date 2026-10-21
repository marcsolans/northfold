"""What code a run executes: environment → git ref (shared by the API, the worker and the scheduler)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import Environment, Version

ENVIRONMENTS = ("development", "production")


class NotDeployed(Exception):
    """The production environment has no deployed version yet."""


@dataclass(frozen=True, slots=True)
class Target:
    ref: str
    environment: str
    environment_id: uuid.UUID | None
    version_id: uuid.UUID | None


async def resolve_target(session: AsyncSession, project_id: uuid.UUID, environment: str) -> Target:
    """Development runs the latest commit; production runs the deployed version's exact commit."""
    if environment not in ENVIRONMENTS:
        raise ValueError(f"unknown environment {environment!r}")
    env = (
        await session.execute(
            select(Environment).where(Environment.project_id == project_id, Environment.name == environment)
        )
    ).scalar_one_or_none()
    if environment == "development":
        return Target(ref="HEAD", environment=environment, environment_id=env.id if env else None, version_id=None)
    if env is None or env.deployed_version_id is None:
        raise NotDeployed("El proyecto todavía no está desplegado en producción")
    version = await session.get(Version, env.deployed_version_id)
    if version is None:
        raise NotDeployed("La versión desplegada ya no existe")
    return Target(ref=version.git_commit, environment=environment, environment_id=env.id, version_id=version.id)
