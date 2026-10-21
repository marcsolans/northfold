"""pytest fixtures: migrated test database, per-test truncation, users/orgs factories."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import text

from messer_common.db import Principal, dispose_engines, system_session
from messer_common.settings import REPO_ROOT, get_settings

KEEP_TABLES = {"alembic_version", "plans", "model_prices", "feature_flags", "connectors", "templates"}


def _ensure_database() -> None:
    settings = get_settings()
    db = settings.database_url.rsplit("/", 1)[1]
    exists = subprocess.run(
        ["su", "postgres", "-c", f"psql -tAc \"SELECT 1 FROM pg_database WHERE datname='{db}'\""],
        capture_output=True,
        text=True,
        check=False,
    )
    if exists.returncode == 0 and exists.stdout.strip() != "1":
        subprocess.run(["su", "postgres", "-c", f"createdb -O messer {db}"], check=True)
        subprocess.run(
            [
                "su",
                "postgres",
                "-c",
                f"psql -d {db} -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; "
                "CREATE EXTENSION IF NOT EXISTS unaccent;'",
            ],
            check=True,
        )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    _ensure_database()
    env = dict(os.environ)
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(Path(REPO_ROOT) / "infra/migrations/alembic.ini"),
            "upgrade",
            "head",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{res.stdout}\n{res.stderr}")


@pytest.fixture(scope="session")
async def seeded(migrated_database: None) -> None:
    from messer_api.services.seed import seed_reference_data

    async with system_session() as s:
        await seed_reference_data(s)


@pytest.fixture(autouse=True)
async def clean_database(seeded: None) -> AsyncIterator[None]:
    yield
    async with system_session() as s:
        rows = await s.execute(text("select tablename from pg_tables where schemaname = 'public'"))
        tables = [r[0] for r in rows if r[0] not in KEEP_TABLES]
        if tables:
            await s.execute(text("TRUNCATE " + ", ".join(f'public."{t}"' for t in tables) + " CASCADE"))
        schemas = await s.execute(text("select nspname from pg_namespace where nspname like 'kb\\_%'"))
        for (schema,) in schemas:
            await s.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    from messer_common.events import get_redis

    try:
        await get_redis().flushdb()
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
async def _dispose_engines_at_end() -> AsyncIterator[None]:
    yield
    await dispose_engines()


@pytest.fixture
async def make_user():  # type: ignore[no-untyped-def]
    from messer_common.db.models import AuthCredential, User
    from messer_common.security import hash_password

    async def factory(
        email: str | None = None,
        *,
        password: str = "Sup3rSecret!pass",
        superadmin: bool = False,
        name: str = "Test User",
    ) -> User:
        email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
        async with system_session() as s:
            user = User(id=uuid.uuid4(), email=email, name=name, is_superadmin=superadmin)
            s.add(user)
            await s.flush()
            s.add(AuthCredential(user_id=user.id, password_hash=hash_password(password)))
        return user

    return factory


@pytest.fixture
async def make_org(make_user):  # type: ignore[no-untyped-def]
    from messer_api.services.orgs import create_org
    from messer_common.db.models import Membership, User

    async def factory(owner: User | None = None, name: str = "Acme", members: dict[str, str] | None = None):  # type: ignore[no-untyped-def]
        owner = owner or await make_user()
        async with system_session() as s:
            org = await create_org(s, owner=owner, name=name)
            for user_id, role in (members or {}).items():
                s.add(Membership(org_id=org.id, user_id=uuid.UUID(user_id), role=role))
        return org, owner

    return factory


def principal_for(user_id: uuid.UUID, org_id: uuid.UUID | None, role: str | None = None) -> Principal:
    return Principal(user_id=user_id, org_id=org_id, role=role)
