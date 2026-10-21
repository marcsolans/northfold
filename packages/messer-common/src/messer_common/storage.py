"""File storage adapter: local filesystem or Supabase Storage (private bucket per organization)."""

from __future__ import annotations

import abc
import asyncio
from pathlib import Path

import httpx

from .settings import get_settings


class StorageError(Exception):
    pass


class Storage(abc.ABC):
    @abc.abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abc.abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...


def _safe_key(key: str) -> str:
    parts = [p for p in key.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        raise StorageError("empty storage key")
    return "/".join(parts)


class LocalStorage(Storage):
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise StorageError(f"not found: {key}")
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            await asyncio.to_thread(path.unlink)

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()


class SupabaseStorage(Storage):
    """Objects live under bucket ``org-<org_id>``; the key's first segment is the org id."""

    def __init__(self, url: str, service_key: str) -> None:
        self.base = url.rstrip("/") + "/storage/v1"
        self.headers = {"Authorization": f"Bearer {service_key}", "apikey": service_key}

    def _split(self, key: str) -> tuple[str, str]:
        safe = _safe_key(key)
        org, _, rest = safe.partition("/")
        return f"org-{org}", rest or "object"

    async def _ensure_bucket(self, client: httpx.AsyncClient, bucket: str) -> None:
        res = await client.post(f"{self.base}/bucket", json={"id": bucket, "name": bucket, "public": False})
        if res.status_code not in (200, 201, 400, 409):
            raise StorageError(f"bucket create failed: {res.status_code} {res.text}")

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        bucket, path = self._split(key)
        async with httpx.AsyncClient(headers=self.headers, timeout=120) as client:
            await self._ensure_bucket(client, bucket)
            res = await client.post(
                f"{self.base}/object/{bucket}/{path}",
                content=data,
                headers={"Content-Type": content_type, "x-upsert": "true"},
            )
            if res.status_code >= 300:
                raise StorageError(f"upload failed: {res.status_code} {res.text}")

    async def get(self, key: str) -> bytes:
        bucket, path = self._split(key)
        async with httpx.AsyncClient(headers=self.headers, timeout=120) as client:
            res = await client.get(f"{self.base}/object/{bucket}/{path}")
            if res.status_code == 404 or res.status_code == 400:
                raise StorageError(f"not found: {key}")
            res.raise_for_status()
            return res.content

    async def delete(self, key: str) -> None:
        bucket, path = self._split(key)
        async with httpx.AsyncClient(headers=self.headers, timeout=60) as client:
            await client.request("DELETE", f"{self.base}/object/{bucket}", json={"prefixes": [path]})

    async def exists(self, key: str) -> bool:
        try:
            await self.get(key)
            return True
        except StorageError:
            return False


_storage: Storage | None = None


def get_storage() -> Storage:
    global _storage
    if _storage is None:
        settings = get_settings()
        if settings.has_supabase_storage:
            _storage = SupabaseStorage(settings.supabase_url, settings.supabase_service_role_key)
        else:
            _storage = LocalStorage(settings.storage_dir)
    return _storage


def set_storage(storage: Storage | None) -> None:
    global _storage
    _storage = storage
