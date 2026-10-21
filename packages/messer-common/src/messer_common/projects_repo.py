"""Git-backed project repositories (one repository per project).

Everything built in Messer is code: the Studio edits files in this repository and every change is a
commit. ``versions`` rows point at commits. The data plane fetches a commit as a tar.gz archive.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .settings import get_settings

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class RepoError(Exception):
    pass


@dataclass(slots=True)
class Commit:
    sha: str
    message: str
    author: str
    date: datetime


def _safe_rel(path: str) -> str:
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or parts[0] == ".git":
        raise RepoError(f"invalid path in repository: {path!r}")
    return "/".join(parts)


class ProjectRepo:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_project(cls, project_id: str) -> ProjectRepo:
        return cls(get_settings().projects_dir / str(project_id))

    # ------------------------------------------------------------------ git plumbing
    def _git(self, *args: str, input_bytes: bytes | None = None, check: bool = True) -> bytes:
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(self.path.parent),
        }
        res = subprocess.run(
            ["git", "-c", "core.quotepath=off", "-c", "init.defaultBranch=main", "-c", "commit.gpgsign=false", *args],
            cwd=self.path,
            input=input_bytes,
            capture_output=True,
            env=env,
            check=False,
            timeout=60,
        )
        if check and res.returncode != 0:
            raise RepoError(f"git {' '.join(args[:2])} failed: {res.stderr.decode(errors='replace').strip()}")
        return res.stdout

    async def _run(self, *args: str, input_bytes: bytes | None = None, check: bool = True) -> bytes:
        return await asyncio.to_thread(self._git, *args, input_bytes=input_bytes, check=check)

    @property
    def exists(self) -> bool:
        return (self.path / ".git").is_dir()

    # ------------------------------------------------------------------ lifecycle
    async def init(self, files: dict[str, str], *, message: str, author: str, email: str) -> str:
        async with _locks[str(self.path)]:
            self.path.mkdir(parents=True, exist_ok=True)
            if not self.exists:
                await self._run("init", "-q")
            await self._write(files)
            return await self._commit(message, author, email, allow_empty=True)

    async def write(self, files: Mapping[str, str | None], *, message: str, author: str, email: str) -> str:
        """Write (or delete, when the value is None) files and commit. Returns the new HEAD."""
        async with _locks[str(self.path)]:
            await self._write(files)
            return await self._commit(message, author, email)

    async def _write(self, files: Mapping[str, str | None]) -> None:
        for rel, content in files.items():
            target = self.path / _safe_rel(rel)
            if content is None:
                if target.exists():
                    await asyncio.to_thread(target.unlink)
                continue
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_text, content, "utf-8")

    async def _commit(self, message: str, author: str, email: str, *, allow_empty: bool = False) -> str:
        await self._run("add", "-A")
        status = (await self._run("status", "--porcelain")).decode().strip()
        if not status and not allow_empty:
            return await self.head()
        args = ["-c", f"user.name={author}", "-c", f"user.email={email}", "commit", "-q", "-m", message]
        if allow_empty:
            args.append("--allow-empty")
        await self._run(*args)
        return await self.head()

    # ------------------------------------------------------------------ reads
    async def head(self) -> str:
        return (await self._run("rev-parse", "HEAD")).decode().strip()

    async def read(self, rel: str, ref: str = "HEAD") -> str | None:
        out = await self._run("show", f"{ref}:{_safe_rel(rel)}", check=False)
        if not out and not (self.path / _safe_rel(rel)).exists():
            return None
        try:
            return out.decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def read_working(self, rel: str) -> str | None:
        target = self.path / _safe_rel(rel)
        if not target.exists():
            return None
        return await asyncio.to_thread(target.read_text, "utf-8")

    async def list_files(self, ref: str = "HEAD", prefix: str = "") -> list[str]:
        out = (await self._run("ls-tree", "-r", "--name-only", ref)).decode()
        files = [f for f in out.splitlines() if f]
        return [f for f in files if f.startswith(prefix)] if prefix else files

    async def log(self, path: str | None = None, limit: int = 50) -> list[Commit]:
        args = ["log", f"-n{limit}", "--format=%H%x1f%s%x1f%an%x1f%aI"]
        if path:
            args += ["--", _safe_rel(path)]
        out = (await self._run(*args)).decode()
        commits: list[Commit] = []
        for line in out.splitlines():
            sha, msg, author, date = line.split("\x1f")
            commits.append(
                Commit(sha=sha, message=msg, author=author, date=datetime.fromisoformat(date).astimezone(UTC))
            )
        return commits

    async def diff(self, ref_a: str, ref_b: str, path: str | None = None) -> str:
        args = ["diff", "--no-color", ref_a, ref_b]
        if path:
            args += ["--", _safe_rel(path)]
        return (await self._run(*args)).decode(errors="replace")

    async def archive(self, ref: str) -> bytes:
        """tar.gz of the tree at ``ref`` (used by the runtime and by project export)."""
        return await self._run("archive", "--format=tar.gz", ref)

    async def restore(self, paths: list[str], ref: str, *, message: str, author: str, email: str) -> str:
        async with _locks[str(self.path)]:
            for rel in paths:
                await self._run("checkout", ref, "--", _safe_rel(rel))
            return await self._commit(message, author, email)

    async def resolve(self, ref: str) -> str:
        return (await self._run("rev-parse", "--verify", f"{ref}^{{commit}}")).decode().strip()
