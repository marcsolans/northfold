"""Git-backed project repositories (one repository per project).

Everything built in Messer is code: the Studio edits files in this repository and every change is a
commit. ``versions`` rows point at commits. The data plane fetches a commit as a tar.gz archive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .settings import get_settings

_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_log = logging.getLogger("messer.projects_repo")

# Called after every commit Messer creates (init/write/restore) with (project_id, sha). Hooks must be fast
# (e.g. enqueue a job) and never raise into the caller: failures are logged and the commit stands.
CommitHook = Callable[[str, str], Awaitable[None]]
_commit_hooks: list[CommitHook] = []
COMMIT_HOOK_TIMEOUT_S = 5.0


def register_commit_hook(hook: CommitHook) -> None:
    """Register ``hook`` once (idempotent), e.g. at service start-up."""
    if hook not in _commit_hooks:
        _commit_hooks.append(hook)


def unregister_commit_hook(hook: CommitHook) -> None:
    if hook in _commit_hooks:
        _commit_hooks.remove(hook)


class RepoError(Exception):
    pass


class PushRejected(RepoError):
    """The remote branch moved: fetch and merge before pushing again."""


@dataclass(frozen=True, slots=True)
class RemoteSpec:
    """A git remote addressed by URL. Credentials travel as HTTP headers through ``GIT_CONFIG_*`` environment
    variables, never in the URL or on the command line (so they cannot leak through ``ps`` or error output).
    Tests point ``url`` at a local bare repository (``file://…``)."""

    url: str
    headers: tuple[str, ...] = ()

    def env(self) -> dict[str, str]:
        env = {"GIT_CONFIG_COUNT": str(len(self.headers))}
        for i, header in enumerate(self.headers):
            env[f"GIT_CONFIG_KEY_{i}"] = "http.extraHeader"
            env[f"GIT_CONFIG_VALUE_{i}"] = header
        return env


@dataclass(slots=True)
class MergeResult:
    old_head: str
    new_head: str
    kind: Literal["up_to_date", "fast_forward", "merge"]
    conflicts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TreeEntry:
    mode: str
    type: str
    size: int | None
    path: str


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

    async def write(self, files: Mapping[str, str | bytes | None], *, message: str, author: str, email: str) -> str:
        """Write (or delete, when the value is None) files and commit. Returns the new HEAD."""
        async with _locks[str(self.path)]:
            await self._write(files)
            return await self._commit(message, author, email)

    async def _write(self, files: Mapping[str, str | bytes | None]) -> None:
        for rel, content in files.items():
            target = self.path / _safe_rel(rel)
            if content is None:
                if target.exists():
                    await asyncio.to_thread(target.unlink)
                continue
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            if isinstance(content, bytes):
                await asyncio.to_thread(target.write_bytes, content)
            else:
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
        sha = await self.head()
        await self._notify_commit(sha)
        return sha

    async def _notify_commit(self, sha: str) -> None:
        for hook in list(_commit_hooks):
            try:
                await asyncio.wait_for(hook(self.path.name, sha), timeout=COMMIT_HOOK_TIMEOUT_S)
            except Exception:  # a hook must never break a commit
                _log.warning("commit hook %r failed for %s", hook, self.path.name, exc_info=True)

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

    # ------------------------------------------------------------------ remotes (GitHub sync)
    # Every network operation goes through a RemoteSpec, so tests use a local bare repository.

    def _git_remote(self, remote: RemoteSpec, *args: str, timeout: float = 180) -> subprocess.CompletedProcess[bytes]:
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            "HOME": str(self.path.parent),
            **remote.env(),
        }
        cmd = [
            "git",
            "-c",
            "core.quotepath=off",
            "-c",
            "credential.helper=",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.https.allow=always",
            "-c",
            "protocol.file.allow=always",
            *args,
        ]
        try:
            return subprocess.run(cmd, cwd=self.path, capture_output=True, env=env, check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RepoError(f"git {args[0]} timed out after {int(timeout)} s") from exc

    async def fetch_remote(self, remote: RemoteSpec, branch: str) -> str | None:
        """Fetch ``branch`` into ``refs/messer/remote/<branch>``; ``None`` when the branch (or repo) is empty."""
        local_ref = f"refs/messer/remote/{branch}"
        res = await asyncio.to_thread(
            self._git_remote, remote, "fetch", "--no-tags", "--quiet", remote.url, f"+refs/heads/{branch}:{local_ref}"
        )
        if res.returncode != 0:
            err = res.stderr.decode(errors="replace").strip()
            if "couldn't find remote ref" in err or "could not find remote ref" in err:
                return None
            raise RepoError(f"git fetch failed: {err}")
        return (await self._run("rev-parse", "--verify", local_ref)).decode().strip()

    async def push_remote(self, remote: RemoteSpec, branch: str, sha: str) -> None:
        """Push ``sha`` to ``refs/heads/<branch>`` (never forced). Raises ``PushRejected`` if the remote moved."""
        res = await asyncio.to_thread(
            self._git_remote, remote, "push", "--porcelain", "--quiet", remote.url, f"{sha}:refs/heads/{branch}"
        )
        if res.returncode == 0:
            return
        out = res.stdout.decode(errors="replace") + "\n" + res.stderr.decode(errors="replace")
        if "[rejected]" in out or "non-fast-forward" in out or "fetch first" in out or "stale info" in out:
            raise PushRejected("the remote branch has new commits")
        raise RepoError(f"git push failed: {res.stderr.decode(errors='replace').strip()}")

    async def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        res = await asyncio.to_thread(self._git_status, "merge-base", "--is-ancestor", ancestor, descendant)
        if res not in (0, 1):
            raise RepoError(f"git merge-base failed for {ancestor[:12]}..{descendant[:12]}")
        return res == 0

    def _git_status(self, *args: str) -> int:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(self.path.parent)}
        return subprocess.run(
            ["git", *args], cwd=self.path, capture_output=True, env=env, check=False, timeout=60
        ).returncode

    async def tree_entries(self, ref: str) -> list[TreeEntry]:
        """Every entry of the tree at ``ref`` with its mode and blob size (used to vet incoming commits)."""
        out = (await self._run("ls-tree", "-r", "-l", "--full-tree", "-z", ref)).decode(errors="replace")
        entries: list[TreeEntry] = []
        for record in out.split("\0"):
            if not record:
                continue
            meta, _, path = record.partition("\t")
            mode, kind, _sha, size = meta.split(maxsplit=3)
            entries.append(
                TreeEntry(mode=mode, type=kind, size=int(size) if size.strip().isdigit() else None, path=path)
            )
        return entries

    async def changed_files(self, ref_a: str, ref_b: str) -> list[str]:
        out = (await self._run("diff", "--name-only", "--no-renames", "-z", ref_a, ref_b)).decode(errors="replace")
        return [p for p in out.split("\0") if p]

    async def merge_commit(self, sha: str, *, message: str, author: str, email: str) -> MergeResult:
        """Merge ``sha`` into HEAD. Fast-forwards when possible; otherwise a merge commit in which conflicting
        hunks keep HEAD's side (Messer wins only on real conflicts). Conflicted paths are returned and appended
        to the merge commit message."""
        async with _locks[str(self.path)]:
            old = await self.head()
            if old == sha or await self.is_ancestor(sha, old):
                return MergeResult(old_head=old, new_head=old, kind="up_to_date")
            if (await self._run("status", "--porcelain")).decode().strip():
                raise RepoError("the working tree has uncommitted changes")
            identity = ["-c", f"user.name={author}", "-c", f"user.email={email}"]
            if await self.is_ancestor(old, sha):
                await self._run("merge", "--ff-only", "--quiet", sha)
                return MergeResult(old_head=old, new_head=await self.head(), kind="fast_forward")
            probe = await asyncio.to_thread(
                self._git_capture,
                "merge-tree",
                "--write-tree",
                "--name-only",
                "--no-messages",
                "--allow-unrelated-histories",
                old,
                sha,
            )
            conflicts: list[str] = []
            if probe[0] == 1:
                lines = probe[1].decode(errors="replace").splitlines()
                conflicts = sorted({line for line in lines[1:] if line.strip()})
            elif probe[0] != 0:
                raise RepoError("git merge-tree failed")
            full_message = message
            if conflicts:
                full_message += "\n\nConflicts resolved in favour of Messer:\n" + "\n".join(f"- {p}" for p in conflicts)
            res = await asyncio.to_thread(
                self._git_capture,
                *identity,
                "merge",
                "--no-ff",
                "--no-edit",
                "--quiet",
                "--allow-unrelated-histories",
                "-X",
                "ours",
                "-m",
                full_message,
                sha,
            )
            if res[0] != 0:
                try:
                    await self._resolve_ours(identity, full_message)
                except RepoError:
                    await self._run("merge", "--abort", check=False)
                    raise
            return MergeResult(old_head=old, new_head=await self.head(), kind="merge", conflicts=conflicts)

    def _git_capture(self, *args: str) -> tuple[int, bytes, bytes]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(self.path.parent)}
        res = subprocess.run(
            ["git", "-c", "core.quotepath=off", "-c", "commit.gpgsign=false", *args],
            cwd=self.path,
            capture_output=True,
            env=env,
            check=False,
            timeout=120,
        )
        return res.returncode, res.stdout, res.stderr

    async def _resolve_ours(self, identity: list[str], message: str) -> None:
        """Finish a merge whose conflicts ``-X ours`` could not settle (modify/delete, renames): keep HEAD."""
        unmerged = (await self._run("diff", "--name-only", "--diff-filter=U", "-z")).decode(errors="replace")
        paths = [p for p in unmerged.split("\0") if p]
        if not paths and not (self.path / ".git" / "MERGE_HEAD").exists():
            raise RepoError("git merge failed")
        for rel in paths:
            exists_ours = self._git_status("cat-file", "-e", f"HEAD:{rel}") == 0
            if exists_ours:
                await self._run("checkout", "--ours", "--", rel)
                await self._run("add", "--", rel)
            else:
                await self._run("rm", "-q", "--cached", "--ignore-unmatch", "--", rel)
                target = self.path / rel
                if target.is_file() or target.is_symlink():
                    await asyncio.to_thread(target.unlink)
        await self._run(*identity, "commit", "-q", "--no-edit", "-m", message)

    async def commit_info(self, ref: str) -> Commit:
        out = (await self._run("log", "-1", "--format=%H%x1f%s%x1f%an%x1f%aI", ref)).decode().strip()
        sha, msg, author, date = out.split("\x1f")
        return Commit(sha=sha, message=msg, author=author, date=datetime.fromisoformat(date).astimezone(UTC))
