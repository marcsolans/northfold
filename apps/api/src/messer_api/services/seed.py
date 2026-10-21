"""Idempotent reference data: plans, model prices, feature flags (used by bootstrap and tests)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db.models import FeatureFlag, ModelPrice, Plan
from messer_common.models_config import price_seeds
from messer_common.plans import DEFAULT_PLANS

DEFAULT_FLAGS = [
    ("composer_voice", "Dictado por voz en el Composer", True),
    ("guard", "Guard: control de comportamiento", True),
    ("github_sync", "Sincronización con GitHub", True),
    ("byoc", "Despliegue en la nube del cliente", True),
]


async def seed_plans(session: AsyncSession, *, overwrite: bool = False) -> None:
    for plan in DEFAULT_PLANS:
        stmt = insert(Plan).values(**plan)
        if overwrite:
            stmt = stmt.on_conflict_do_update(
                index_elements=[Plan.id], set_={k: v for k, v in plan.items() if k != "id"}
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=[Plan.id])
        await session.execute(stmt)


async def seed_model_prices(session: AsyncSession) -> None:
    for seed in price_seeds():
        await session.execute(
            insert(ModelPrice)
            .values(
                model=seed.model,
                provider=seed.provider,
                display_name=seed.display_name,
                input_per_mtok_usd=seed.input,
                output_per_mtok_usd=seed.output,
                cache_read_per_mtok_usd=seed.cache_read,
                cache_write_per_mtok_usd=seed.cache_write,
                context_window=seed.context_window,
            )
            .on_conflict_do_nothing(index_elements=[ModelPrice.model])
        )


async def seed_flags(session: AsyncSession) -> None:
    for key, description, enabled in DEFAULT_FLAGS:
        await session.execute(
            insert(FeatureFlag)
            .values(key=key, description=description, enabled=enabled)
            .on_conflict_do_nothing(index_elements=[FeatureFlag.key])
        )


async def seed_reference_data(session: AsyncSession) -> None:
    await seed_plans(session)
    await seed_model_prices(session)
    await seed_flags(session)
    # Connector catalog and templates are seeded by their own modules when installed.
    from . import catalog_seed

    await catalog_seed.seed_all(session)


async def plans_exist(session: AsyncSession) -> bool:
    return (await session.execute(select(Plan.id).limit(1))).first() is not None
