"""Sandbox process pool: one isolated process per (project, commit).

Isolation today: a separate process with a scrubbed environment (only the sandbox token, platform URL,
project ids and the project's own secrets), its own session/process group, and resource limits (address
space, CPU time, open files). Moving to gVisor, Firecracker or E2B is a matter of replacing ``_spawn`` (see
DECISIONS.md D-021). Sandboxes are reused while warm and reaped when idle; a new commit gets a new sandbox,
so deploying never interrupts runs in flight on the previous one.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import resource
import signal
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from messer_common.logging import get_logger
from messer_common.settings import get_settings

from ..tokens import issue_sandbox_token

log = get_logger("messer.runtime.sandbox")

IDLE_TTL_S = 15 * 60
START_TIMEOUT_S = 60
_SAFE_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "TZ",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "HTTPS_PROXY",
    "NO_PROXY",
    "https_proxy",
    "no_proxy",
)
# Project secrets that would let agent code bypass the model gateway (and with it credits, budgets, residency).
_RESERVED_SECRETS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
)


@dataclass(slots=True)
class Sandbox:
    key: tuple[str, str]
    org_id: uuid.UUID
    project_id: uuid.UUID
    commit: str
    project_dir: Path
    socket_path: Path
    process: asyncio.subprocess.Process
    started_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    active: int = 0
    drain_task: asyncio.Task[None] | None = None

    @property
    def alive(self) -> bool:
        return self.process.returncode is None

    def client(self, timeout: float | None = None) -> httpx.AsyncClient:
        transport = httpx.AsyncHTTPTransport(uds=str(self.socket_path))
        return httpx.AsyncClient(transport=transport, base_url="http://sandbox", timeout=timeout)


def _limits() -> None:  # runs in the child before exec
    settings = get_settings()
    mem = settings.runtime_sandbox_memory_mb * 1024 * 1024
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    cpu = settings.runtime_sandbox_cpu_seconds
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
    os.setsid()


class SandboxPool:
    def __init__(self, internal_base_url: str) -> None:
        self.internal_base_url = internal_base_url.rstrip("/")
        self._sandboxes: dict[tuple[str, str], Sandbox] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._reaper: asyncio.Task[None] | None = None

    def start_reaper(self) -> None:
        if self._reaper is None:
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.monotonic()
            for key, sbx in list(self._sandboxes.items()):
                if not sbx.alive or (sbx.active == 0 and now - sbx.last_used > IDLE_TTL_S):
                    await self._stop(key)

    async def _stop(self, key: tuple[str, str]) -> None:
        sbx = self._sandboxes.pop(key, None)
        if sbx is None:
            return
        if sbx.alive:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(sbx.process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(sbx.process.wait(), timeout=5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(sbx.process.pid, signal.SIGKILL)
        with contextlib.suppress(FileNotFoundError):
            sbx.socket_path.unlink()
        log.info("sandbox.stopped", project=str(sbx.project_id), commit=sbx.commit[:8])

    async def shutdown(self) -> None:
        if self._reaper is not None:
            self._reaper.cancel()
        for key in list(self._sandboxes):
            await self._stop(key)

    def stats(self) -> list[dict[str, Any]]:
        return [
            {
                "project_id": str(s.project_id),
                "commit": s.commit,
                "active": s.active,
                "alive": s.alive,
                "uptime_s": round(time.monotonic() - s.started_at),
            }
            for s in self._sandboxes.values()
        ]

    async def get(
        self,
        *,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        commit: str,
        project_dir: Path,
        secrets: dict[str, str],
        environment: str,
    ) -> Sandbox:
        key = (str(project_id), commit)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            existing = self._sandboxes.get(key)
            if existing is not None and existing.alive:
                existing.last_used = time.monotonic()
                return existing
            if existing is not None:
                await self._stop(key)
            sbx = await self._spawn(
                org_id=org_id,
                project_id=project_id,
                commit=commit,
                project_dir=project_dir,
                secrets=secrets,
                environment=environment,
            )
            self._sandboxes[key] = sbx
            return sbx

    async def _spawn(
        self,
        *,
        org_id: uuid.UUID,
        project_id: uuid.UUID,
        commit: str,
        project_dir: Path,
        secrets: dict[str, str],
        environment: str,
    ) -> Sandbox:
        settings = get_settings()
        sock_dir = settings.runtime_cache_dir / "sockets"
        sock_dir.mkdir(parents=True, exist_ok=True)
        socket_path = sock_dir / f"{str(project_id)[:8]}-{commit[:12]}-{uuid.uuid4().hex[:6]}.sock"
        home = settings.runtime_cache_dir / "home" / str(project_id)
        home.mkdir(parents=True, exist_ok=True)
        env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
        env.update(
            {
                k: v
                for k, v in secrets.items()
                if k.isidentifier() and not k.startswith("MESSER_") and k not in _RESERVED_SECRETS
            }
        )
        env.update(
            {
                "HOME": str(home),
                "PYTHONPATH": str(project_dir),
                "PYTHONDONTWRITEBYTECODE": "1",
                "MESSER_API_HOST": f"{self.internal_base_url}/internal/v1",
                "MESSER_API_KEY": issue_sandbox_token(
                    org_id=org_id, project_id=project_id, commit=commit, environment=environment
                ),
                "MESSER_ORG_ID": str(org_id),
                "MESSER_PROJECT_ID": str(project_id),
                "MESSER_REV": commit,
                "MESSER_OFFLOAD_DIR": str(home / "offload"),
                "MESSER_LOG_LEVEL": "WARNING",
            }
        )
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "messer_runtime.sandbox.server",
            "--project-dir",
            str(project_dir),
            "--socket",
            str(socket_path),
            cwd=str(project_dir),
            env=env,
            preexec_fn=_limits,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        sbx = Sandbox(
            key=(str(project_id), commit),
            org_id=org_id,
            project_id=project_id,
            commit=commit,
            project_dir=project_dir,
            socket_path=socket_path,
            process=process,
        )
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            if not sbx.alive:
                stderr = (await process.stderr.read()).decode(errors="replace") if process.stderr else ""
                raise RuntimeError(f"sandbox exited during start: {stderr[-2000:]}")
            if socket_path.exists():
                try:
                    async with sbx.client(timeout=2) as c:
                        if (await c.get("/healthcheck")).status_code == 200:
                            break
                except httpx.HTTPError:
                    pass
            await asyncio.sleep(0.1)
        else:
            await self._stop(sbx.key)
            raise RuntimeError("sandbox did not become ready in time")
        if process.stderr is not None:
            sbx.drain_task = asyncio.create_task(_drain(process.stderr, str(project_id), commit))
        log.info("sandbox.started", project=str(project_id), commit=commit[:8], pid=process.pid)
        return sbx

    @contextlib.asynccontextmanager
    async def lease(self, sbx: Sandbox) -> AsyncIterator[Sandbox]:
        sbx.active += 1
        try:
            yield sbx
        finally:
            sbx.active -= 1
            sbx.last_used = time.monotonic()


async def _drain(stream: asyncio.StreamReader, project_id: str, commit: str) -> None:
    while True:
        line = await stream.readline()
        if not line:
            return
        log.warning("sandbox.stderr", project=project_id, commit=commit[:8], line=line.decode(errors="replace")[:2000])
