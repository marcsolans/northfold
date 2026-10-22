"""Backups are tested by restoring them: back up, wipe everything, restore, and check data, KB schema and repos."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from sqlalchemy import text

from messer_common.db import dispose_engines, system_session
from messer_common.projects_repo import ProjectRepo
from messer_common.settings import get_settings
from messer_common.storage import get_storage
from messer_common.testing.fixtures import REPO_ROOT, principal_for

SCRIPTS = Path(REPO_ROOT) / "infra" / "scripts"


def _env(tmp: Path) -> dict[str, str]:
    s = get_settings()
    return {
        **os.environ,
        "DATABASE_URL": s.database_url,
        "DATABASE_APP_URL": s.database_app_url,
        "DATABASE_READONLY_URL": s.database_readonly_url,
        "MESSER_PROJECTS_DIR": str(s.projects_dir),
        "MESSER_STORAGE_DIR": str(s.storage_dir),
        "BACKUP_PASSPHRASE": "contraseña-de-prueba",
    }


@pytest.mark.skipif(shutil.which("pg_dump") is None, reason="pg_dump not installed")
async def test_backup_then_restore_brings_everything_back(make_org, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from messer_api.services.knowledge.lifecycle import create_kb
    from messer_api.services.knowledge.tables import upsert_table
    from messer_api.services.projects import create_project

    org, owner = await make_org(name="Copias")
    principal = principal_for(owner.id, org.id, "owner")
    async with system_session() as s:
        project = await create_project(s, principal, name="Facturas")
    kb = await create_kb(principal, name="Facturas", project_id=project.id)
    async with system_session() as s:
        await upsert_table(
            s,
            org_id=org.id,
            kb_id=kb.id,
            table="facturas",
            columns=[{"name": "numero", "type": "text"}, {"name": "importe", "type": "numeric"}],
            rows=[{"numero": "F-1", "importe": 120}, {"numero": "F-2", "importe": 980}],
            primary_key=["numero"],
        )
    await get_storage().put(f"orgs/{org.id}/demo.txt", b"contenido", "text/plain")
    head = await ProjectRepo.for_project(str(project.id)).head()

    env = _env(tmp_path)
    out = await asyncio.to_thread(
        subprocess.run,
        [str(SCRIPTS / "backup.sh"), str(tmp_path / "bk")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    backup_dir = Path(out.stdout.strip().splitlines()[-1])
    assert (backup_dir / "db.dump.enc").exists() and (backup_dir / "manifest.json").exists()

    # Disaster: the data, the KB schema and role, the repositories and the files are gone.
    async with system_session() as s:
        await s.execute(text(f'DROP SCHEMA "{kb.schema_name}" CASCADE'))
        await s.execute(text("TRUNCATE public.orgs CASCADE"))
        await s.execute(text(f'DROP ROLE "{kb.reader_role}"'))
    shutil.rmtree(get_settings().projects_dir)
    shutil.rmtree(get_settings().storage_dir)
    await dispose_engines()

    res = await asyncio.to_thread(
        subprocess.run,
        [str(SCRIPTS / "restore.sh"), str(backup_dir)],
        env=env,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    assert res.returncode == 0, res.stderr

    async with system_session() as s:
        name = (await s.execute(text("SELECT name FROM public.orgs WHERE id = :i"), {"i": org.id})).scalar_one()
        total = (await s.execute(text(f'SELECT sum(importe) FROM "{kb.schema_name}"."facturas"'))).scalar_one()
        role = (await s.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": kb.reader_role})).first()
    assert name == "Copias" and int(total) == 1100 and role is not None
    assert await ProjectRepo.for_project(str(project.id)).head() == head
    assert await get_storage().get(f"orgs/{org.id}/demo.txt") == b"contenido"
