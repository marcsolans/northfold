"""Database engines and sessions.

Three connections, three roles:

* ``owner``    — DATABASE_URL, owns the schema. Used for migrations and for
                 *system* work that is not tied to a user request (webhooks,
                 scheduler, workers). Owner connections bypass RLS, so system
                 code must always filter by ``org_id`` explicitly.
* ``app``      — DATABASE_APP_URL, role ``messer_app`` without BYPASSRLS. Every
                 user-facing request runs here inside :func:`rls_session`, which
                 sets ``app.user_id`` / ``app.org_id`` for the policies.
* ``readonly`` — DATABASE_READONLY_URL, role ``messer_readonly`` used by the SQL
                 console and the agent SQL tool, switched per query to the
                 knowledge base's reader role.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..settings import get_settings

_engines: dict[str, AsyncEngine] = {}
_makers: dict[str, async_sessionmaker[AsyncSession]] = {}


def _engine(kind: str) -> AsyncEngine:
    if kind not in _engines:
        settings = get_settings()
        url = {
            "owner": settings.database_url,
            "app": settings.database_app_url,
            "readonly": settings.database_readonly_url,
        }[kind]
        _engines[kind] = create_async_engine(
            url,
            pool_size=10 if kind != "readonly" else 4,
            max_overflow=20 if kind != "readonly" else 4,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
        _makers[kind] = async_sessionmaker(_engines[kind], expire_on_commit=False)
    return _engines[kind]


def get_owner_engine() -> AsyncEngine:
    return _engine("owner")


def get_app_engine() -> AsyncEngine:
    return _engine("app")


def get_readonly_engine() -> AsyncEngine:
    return _engine("readonly")


async def dispose_engines() -> None:
    for engine in _engines.values():
        await engine.dispose()
    _engines.clear()
    _makers.clear()


@dataclass(slots=True)
class Principal:
    """Who is making a request. ``org_id`` is the active organization."""

    user_id: uuid.UUID | None
    org_id: uuid.UUID | None = None
    role: str | None = None
    is_superadmin: bool = False
    email: str | None = None
    api_key_id: uuid.UUID | None = None
    impersonated_by: uuid.UUID | None = None
    scopes: list[str] = field(default_factory=list)
    project_id: uuid.UUID | None = None  # API keys scoped to one project
    mfa_verified: bool = False


async def apply_rls_settings(session: AsyncSession, principal: Principal) -> None:
    await session.execute(
        text(
            "select set_config('app.user_id', :uid, true), set_config('app.org_id', :oid, true),"
            " set_config('app.superadmin', :sa, true)"
        ),
        {
            "uid": str(principal.user_id) if principal.user_id else "",
            "oid": str(principal.org_id) if principal.org_id else "",
            "sa": "on" if principal.is_superadmin else "off",
        },
    )


@asynccontextmanager
async def rls_session(principal: Principal) -> AsyncIterator[AsyncSession]:
    """Transaction on the application role with RLS settings applied.

    Commits on success, rolls back on error. ``set_config(..., true)`` scopes the
    settings to this transaction so pooled connections never leak identities.
    """
    _engine("app")
    async with _makers["app"]() as session:
        async with session.begin():
            await apply_rls_settings(session, principal)
            yield session


@asynccontextmanager
async def system_session() -> AsyncIterator[AsyncSession]:
    """Transaction on the owner role (bypasses RLS). Filter by org_id explicitly."""
    _engine("owner")
    async with _makers["owner"]() as session:
        async with session.begin():
            yield session


@asynccontextmanager
async def readonly_session() -> AsyncIterator[AsyncSession]:
    _engine("readonly")
    async with _makers["readonly"]() as session:
        async with session.begin():
            yield session
