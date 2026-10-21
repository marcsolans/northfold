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


def _admin_sql(statements: list[str], database: str = "postgres") -> None:
    """Run admin SQL: via MESSER_TEST_PG_ADMIN_URL (CI) or `su postgres` (local peer auth)."""
    admin_url = os.environ.get("MESSER_TEST_PG_ADMIN_URL")
    if admin_url:
        import psycopg

        base = admin_url.rsplit("/", 1)[0]
        with psycopg.connect(f"{base}/{database}", autocommit=True) as conn:
            for stmt in statements:
                conn.execute(stmt)  # type: ignore[arg-type]
        return
    for stmt in statements:
        subprocess.run(
            ["su", "postgres", "-c", f'psql -v ON_ERROR_STOP=1 -d {database} -c "{stmt}"'],
            check=True,
            capture_output=True,
            text=True,
        )


def _recreate_database() -> None:
    """Fresh database per test session so every migration (including newly edited ones) runs."""
    settings = get_settings()
    db = settings.database_url.rsplit("/", 1)[1]
    if not db.startswith("messer_test"):
        raise RuntimeError(f"refusing to recreate non-test database {db}")
    _admin_sql(
        [
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{db}' AND pid <> pg_backend_pid()",
            f"DROP DATABASE IF EXISTS {db}",
            f"CREATE DATABASE {db} OWNER messer",
        ]
    )
    _admin_sql(
        [
            "CREATE EXTENSION IF NOT EXISTS vector",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE EXTENSION IF NOT EXISTS unaccent",
        ],
        database=db,
    )


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> None:
    _recreate_database()
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
