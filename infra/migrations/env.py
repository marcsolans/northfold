"""Alembic environment: migrations run on the owner connection (DATABASE_URL)."""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from messer_common.db import (
    Base,
    models,  # noqa: F401  (registers tables)
)
from messer_common.settings import get_settings

target_metadata = Base.metadata


def _url() -> str:
    return os.environ.get("MIGRATIONS_DATABASE_URL") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection) -> None:  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # The owner role is named "messer" like the helper-function schema, so the default search path
    # ("$user", public) would put unqualified tables into that schema. Migrations always target public.
    engine = create_async_engine(_url(), connect_args={"options": "-c search_path=public"})
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
