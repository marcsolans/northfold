"""Project code at a given commit, fetched from the control plane and cached on local disk."""

from __future__ import annotations

import asyncio
import io
import shutil
import tarfile
import uuid
from collections import defaultdict
from pathlib import Path

import httpx

from messer_common.settings import get_settings

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class CodeFetchError(Exception):
    pass


def _cache_root() -> Path:
    root = get_settings().runtime_cache_dir / "code"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_extract(data: bytes, target: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or ".." in Path(name).parts or member.issym() or member.islnk():
                raise CodeFetchError(f"unsafe path in archive: {name}")
        tar.extractall(target, filter="data")


async def fetch_archive(project_id: uuid.UUID, ref: str) -> tuple[str, bytes]:
    settings = get_settings()
    url = f"{settings.messer_api_url.rstrip('/')}/internal/v1/projects/{project_id}/archive"
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.get(url, params={"ref": ref}, headers={"Authorization": f"Bearer {settings.service_token}"})
    if res.status_code != 200:
        raise CodeFetchError(f"archive fetch failed ({res.status_code}): {res.text[:200]}")
    return res.headers["x-messer-commit"], res.content


async def ensure_checkout(project_id: uuid.UUID, ref: str) -> tuple[str, Path]:
    """Return (commit, directory) for ``ref``. Commits are immutable, so cached checkouts never go stale."""
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref):
        target = _cache_root() / str(project_id) / ref
        if target.is_dir():
            return ref, target
    commit, data = await fetch_archive(project_id, ref)
    target = _cache_root() / str(project_id) / commit
    async with _locks[str(target)]:
        if target.is_dir():
            return commit, target
        tmp = target.with_name(f".{commit}.{uuid.uuid4().hex[:6]}")
        tmp.mkdir(parents=True)
        try:
            await asyncio.to_thread(_safe_extract, data, tmp)
            tmp.rename(target)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
    return commit, target
