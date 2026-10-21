"""Control plane → runtime client (service token). Used by the API, the worker and the scheduler."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .settings import get_settings

# Test hook: route runtime calls through a custom transport.
transport: httpx.AsyncBaseTransport | None = None


class RuntimeUnavailable(Exception):
    """The runtime could not be reached or answered with an unexpected error."""


def _client(timeout: float | None) -> httpx.AsyncClient:
    s = get_settings()
    return httpx.AsyncClient(
        base_url=s.messer_runtime_url.rstrip("/"),
        headers={"Authorization": f"Bearer {s.service_token}"},
        timeout=httpx.Timeout(timeout, connect=10) if timeout is not None else httpx.Timeout(None, connect=10),
        transport=transport,
    )


def _jsonable(body: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(body, default=lambda v: str(v) if isinstance(v, uuid.UUID) else repr(v)))


async def stream_run(body: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    """Start a run and yield its events (engine events plus RUN_STARTED / RUN_ERROR / RUN_FINISHED)."""
    try:
        async with _client(None) as c, c.stream("POST", "/internal/v1/runs/stream", json=_jsonable(body)) as res:
            if res.status_code != 200:
                detail = (await res.aread()).decode(errors="replace")[:500]
                raise RuntimeUnavailable(f"runtime answered {res.status_code}: {detail}")
            async for line in res.aiter_lines():
                if line.startswith("data: "):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
    except httpx.HTTPError as exc:
        raise RuntimeUnavailable(f"runtime unreachable: {exc}") from exc


async def run(body: dict[str, Any], timeout_s: float = 900) -> dict[str, Any]:
    """Synchronous run: returns the RUN_FINISHED summary plus ``output`` and ``errors``."""
    return await _post("/internal/v1/runs", body, timeout_s)


async def evals(
    project_id: uuid.UUID, name: str, *, ref: str = "HEAD", tags: list[str] | None = None
) -> dict[str, Any]:
    return await _post(f"/internal/v1/projects/{project_id}/workforce/{name}/evals", {"ref": ref, "tags": tags}, 960)


async def flow(project_id: uuid.UUID, name: str, ref: str = "HEAD") -> dict[str, Any]:
    return await _get(f"/internal/v1/projects/{project_id}/workforce/{name}/flow", {"ref": ref})


async def schema(project_id: uuid.UUID, name: str, ref: str = "HEAD") -> dict[str, Any]:
    return await _get(f"/internal/v1/projects/{project_id}/workforce/{name}/schema", {"ref": ref})


async def warm(project_id: uuid.UUID, ref: str) -> dict[str, Any]:
    """Fetch the code at ``ref`` and start its sandbox so the first production run is fast."""
    return await _post(f"/internal/v1/projects/{project_id}/warm", {"ref": ref}, 180)


async def sandboxes() -> dict[str, Any]:
    return await _get("/internal/v1/sandboxes", {})


async def invalidate_caches() -> None:
    try:
        await _post("/internal/v1/caches/invalidate", {}, 10)
    except RuntimeUnavailable:
        # Caches expire on their own within a minute; a missed invalidation is not an error.
        return


async def _post(path: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    try:
        async with _client(timeout_s) as c:
            res = await c.post(path, json=_jsonable(body))
    except httpx.HTTPError as exc:
        raise RuntimeUnavailable(f"runtime unreachable: {exc}") from exc
    return _decode(res)


async def _get(path: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        async with _client(120) as c:
            res = await c.get(path, params=params)
    except httpx.HTTPError as exc:
        raise RuntimeUnavailable(f"runtime unreachable: {exc}") from exc
    return _decode(res)


def _decode(res: httpx.Response) -> dict[str, Any]:
    try:
        data = res.json()
    except ValueError as exc:
        raise RuntimeUnavailable(f"runtime answered {res.status_code} with a non-JSON body") from exc
    if res.status_code >= 500 and "error" in data:
        raise RuntimeUnavailable(
            str(data["error"].get("message") if isinstance(data["error"], dict) else data["error"])
        )
    if res.status_code >= 400:
        detail = data.get("detail") or data.get("error") or data
        raise RuntimeUnavailable(f"runtime answered {res.status_code}: {detail}")
    return data if isinstance(data, dict) else {"data": data}
