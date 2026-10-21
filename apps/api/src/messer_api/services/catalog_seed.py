"""Seeds global catalogs contributed by other packages (connectors, templates).

Each contributor registers an async callable ``(session) -> None`` in ``SEEDERS``. Modules that
are not installed are skipped, so the API works with a partial install.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.logging import get_logger

log = get_logger("messer.seed")

# "module:function" entries resolved lazily.
SEEDERS: list[str] = [
    "messer_api.services.connectors_catalog:seed_connectors",
    "messer_api.services.templates_catalog:seed_templates",
]


async def seed_all(session: AsyncSession) -> None:
    for entry in SEEDERS:
        module_name, _, fn_name = entry.partition(":")
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                log.info("seed.skip", seeder=entry, reason="module not installed yet")
                continue
            raise
        fn: Callable[[AsyncSession], Awaitable[None]] = getattr(module, fn_name)
        await fn(session)
