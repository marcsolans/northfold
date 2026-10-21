"""Shared pytest helpers for every Messer Python package.

Usage in a package ``conftest.py``::

    from messer_common.testing import configure_test_env
    configure_test_env()          # must run before importing settings-dependent modules
    pytest_plugins = ["messer_common.testing.fixtures"]

The test database is ``$MESSER_TEST_DATABASE`` (default ``messer_test``) on the local server.
Each parallel workstream can use its own database name to avoid interference.
"""

from __future__ import annotations

import os

TEST_ENV_DEFAULTS = {
    "MESSER_ENV": "test",
    "MESSER_EMAIL_PROVIDER": "console",
    "MESSER_WEB_URL": "http://localhost:3000",
    "MESSER_API_URL": "http://localhost:8000",
    "MESSER_EMBEDDINGS_PROVIDER": "hash",
    "ANTHROPIC_API_KEY": "",
    "STRIPE_SECRET_KEY": "",
    "SUPABASE_URL": "",
    "SUPABASE_ANON_KEY": "",
    "SENTRY_DSN": "",
}


def configure_test_env() -> str:
    db = os.environ.get("MESSER_TEST_DATABASE", "messer_test")
    host = os.environ.get("MESSER_TEST_DB_HOST", "localhost:5432")
    os.environ["DATABASE_URL"] = f"postgresql+psycopg://messer:messer@{host}/{db}"
    os.environ["DATABASE_APP_URL"] = f"postgresql+psycopg://messer_app:messer_app@{host}/{db}"
    os.environ["DATABASE_READONLY_URL"] = f"postgresql+psycopg://messer_readonly:messer_readonly@{host}/{db}"
    os.environ.setdefault("REDIS_URL", os.environ.get("MESSER_TEST_REDIS_URL", "redis://localhost:6379/15"))
    os.environ["MESSER_PROJECTS_DIR"] = os.environ.get("MESSER_TEST_PROJECTS_DIR", f"/tmp/messer-test/{db}/projects")
    os.environ["MESSER_STORAGE_DIR"] = os.environ.get("MESSER_TEST_STORAGE_DIR", f"/tmp/messer-test/{db}/storage")
    os.environ["MESSER_RUNTIME_CACHE_DIR"] = f"/tmp/messer-test/{db}/runtime"
    # Tests are hermetic by default; set MESSER_TEST_KEEP_<VAR>=1 to keep a real value (e.g. a live API key).
    for key, value in TEST_ENV_DEFAULTS.items():
        if not os.environ.get(f"MESSER_TEST_KEEP_{key}"):
            os.environ[key] = value
    from messer_common.settings import reset_settings_cache

    reset_settings_cache()
    return db
