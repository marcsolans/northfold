"""Git smart HTTP protocol for project repositories (``git clone`` / ``fetch`` / ``push`` against Messer).

* ``upload-pack`` (fetch/clone) is served by ``git upload-pack --stateless-rpc`` on the project repository with
  Messer's internal refs (``refs/messer/*``) hidden. Protocol v2 is passed through (``Git-Protocol`` header).
* ``receive-pack`` (push) is implemented here instead of by ``git receive-pack``, because a push is not a plain ref
  update: the commands are parsed from the pkt-line request, the pack is indexed into a quarantine directory
  (``git index-pack --strict --fix-thin``), every update is vetted and applied by
  :func:`messer_api.services.git_push.apply_push` (merge policy, versions, audit), and only then are the objects
  moved into the repository. The client gets a standard ``report-status`` (inside side-band 1 when requested) plus
  progress lines on side-band 2 (shown as ``remote: Messer: …``).
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
import tempfile
import zlib
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

from messer_common.logging import get_logger
from messer_common.projects_repo import ProjectRepo

from .git_push import ZERO_SHA, PushReport, RefResult, RefUpdate, git_env

log = get_logger("messer.api.git_http")

MAX_PUSH_BYTES = 200 * 1024 * 1024
MAX_FETCH_REQUEST_BYTES = 16 * 1024 * 1024
PROCESS_TIMEOUT_S = 600
CHUNK = 64 * 1024
RECEIVE_CAPABILITIES = "report-status delete-refs side-band-64k quiet atomic ofs-delta agent=messer/1.0"
HIDE_REFS = ("-c", "uploadpack.hideRefs=refs/messer", "-c", "uploadpack.hideRefs=refs/remotes")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PROTOCOL = re.compile(r"^version=[0-9]$")


class GitProtocolError(Exception):
    """Malformed request (answered with HTTP 400)."""


class BodyTooLarge(Exception):
    pass


def pkt(data: str | bytes) -> bytes:
    raw = data.encode() if isinstance(data, str) else data
    return f"{len(raw) + 4:04x}".encode() + raw


FLUSH = b"0000"


def git_protocol(header: str | None) -> str | None:
    value = (header or "").strip()
    return value if _PROTOCOL.match(value) else None


# ------------------------------------------------------------------------------------------ request bodies


async def read_body(
    chunks: AsyncIterator[bytes], *, gzip: bool, limit: int, target: IO[bytes] | None = None
) -> bytes | None:
    """Read (and gunzip) a request body; into ``target`` when given (returns None), else into memory."""
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS) if gzip else None
    size = 0
    parts: list[bytes] = []

    def emit(data: bytes) -> None:
        nonlocal size
        size += len(data)
        if size > limit:
            raise BodyTooLarge
        if target is not None:
            target.write(data)
        else:
            parts.append(data)

    async for chunk in chunks:
        if not chunk:
            continue
        if inflater is not None:
            try:
                emit(inflater.decompress(chunk, limit + 1 - size))
            except zlib.error as exc:
                raise GitProtocolError("invalid gzip body") from exc
        else:
            emit(chunk)
    if inflater is not None:
        emit(inflater.flush())
    return None if target is not None else b"".join(parts)


# ---------------------------------------------------------------------------------------- advertisements


async def _run(args: list[str], *, cwd: Path, env: dict[str, str], stdin: bytes | None = None) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=PROCESS_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    if proc.returncode != 0:
        log.warning("git_http.command_failed", command=args[:4], error=err.decode(errors="replace")[:500])
    return proc.returncode or 0, out


async def upload_pack_advertisement(repo: ProjectRepo, protocol: str | None) -> bytes:
    env = git_env({"GIT_PROTOCOL": protocol} if protocol else None)
    code, out = await _run(
        ["git", *HIDE_REFS, "upload-pack", "--stateless-rpc", "--advertise-refs", "."], cwd=repo.path, env=env
    )
    if code != 0:
        raise GitProtocolError("upload-pack failed")
    if protocol == "version=2":
        return out
    return pkt("# service=git-upload-pack\n") + FLUSH + out


async def receive_pack_advertisement(repo: ProjectRepo, branch: str) -> bytes:
    env = git_env()
    refs: list[tuple[str, str]] = []
    code, out = await _run(
        ["git", "for-each-ref", "--format=%(objectname) %(refname)", f"refs/heads/{branch}", "refs/tags"],
        cwd=repo.path,
        env=env,
    )
    if code == 0:
        for line in out.decode(errors="replace").splitlines():
            sha, _, ref = line.partition(" ")
            if _SHA.match(sha) and ref:
                refs.append((sha, ref))
    body = pkt("# service=git-receive-pack\n") + FLUSH
    if not refs:
        body += pkt(f"{ZERO_SHA} capabilities^{{}}\0{RECEIVE_CAPABILITIES}\n")
    for i, (sha, ref) in enumerate(refs):
        body += pkt(f"{sha} {ref}\0{RECEIVE_CAPABILITIES}\n" if i == 0 else f"{sha} {ref}\n")
    return body + FLUSH


# ------------------------------------------------------------------------------------------- upload-pack


async def upload_pack(repo: ProjectRepo, body: bytes, protocol: str | None) -> AsyncIterator[bytes]:
    """Stream ``git upload-pack --stateless-rpc`` for one request (stdin written concurrently with stdout)."""
    env = git_env({"GIT_PROTOCOL": protocol} if protocol else None)
    proc = await asyncio.create_subprocess_exec(
        "git",
        *HIDE_REFS,
        "upload-pack",
        "--stateless-rpc",
        ".",
        cwd=repo.path,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    assert proc.stdin is not None and proc.stdout is not None
    stdin, stdout = proc.stdin, proc.stdout

    async def feed() -> None:
        try:
            stdin.write(body)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stdin.close()

    feeder = asyncio.create_task(feed())
    try:
        while True:
            chunk = await asyncio.wait_for(stdout.read(CHUNK), timeout=PROCESS_TIMEOUT_S)
            if not chunk:
                break
            yield chunk
        await feeder
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        await proc.wait()
        if not feeder.done():
            feeder.cancel()


# ------------------------------------------------------------------------------------------ receive-pack


@dataclass(slots=True)
class ReceiveRequest:
    updates: list[RefUpdate] = field(default_factory=list)
    capabilities: set[str] = field(default_factory=set)
    shallow: bool = False
    pack_offset: int = 0


def parse_receive_request(stream: IO[bytes]) -> ReceiveRequest:
    """Read the command list (pkt-lines up to the first flush); the pack (if any) follows at ``pack_offset``."""
    req = ReceiveRequest()
    first = True
    while True:
        head = stream.read(4)
        if len(head) == 0:
            break  # an empty body: nothing to do (git's large-request probe)
        if len(head) < 4:
            raise GitProtocolError("truncated pkt-line")
        try:
            length = int(head, 16)
        except ValueError as exc:
            raise GitProtocolError("invalid pkt-line length") from exc
        if length == 0:
            break
        if length < 4:
            raise GitProtocolError("invalid pkt-line length")
        payload = stream.read(length - 4)
        if len(payload) != length - 4:
            raise GitProtocolError("truncated pkt-line")
        line = payload.rstrip(b"\n")
        if first and b"\0" in line:
            line, _, caps = line.partition(b"\0")
            req.capabilities = set(caps.decode(errors="replace").split())
        first = False
        text = line.decode(errors="replace")
        if text.startswith("shallow "):
            req.shallow = True
            continue
        parts = text.split(" ")
        if len(parts) != 3 or not _SHA.match(parts[0]) or not _SHA.match(parts[1]) or not parts[2]:
            raise GitProtocolError(f"invalid command: {text[:120]}")
        req.updates.append(RefUpdate(old=parts[0], new=parts[1], ref=parts[2]))
    req.pack_offset = stream.tell()
    return req


@dataclass(slots=True)
class Quarantine:
    """Incoming objects live here until the push is accepted (``GIT_OBJECT_DIRECTORY`` + alternates)."""

    repo: ProjectRepo
    path: Path

    @classmethod
    def create(cls, repo: ProjectRepo) -> Quarantine:
        path = repo.path / ".git" / "objects" / f"incoming-{secrets.token_hex(8)}"
        (path / "pack").mkdir(parents=True)
        return cls(repo=repo, path=path)

    def env(self) -> dict[str, str]:
        return git_env(
            {
                "GIT_OBJECT_DIRECTORY": str(self.path),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(self.repo.path / ".git" / "objects"),
            }
        )

    def migrate(self) -> None:
        """Move the indexed pack(s) into the repository; the ``.idx`` goes last so readers never see a half pack."""
        target = self.repo.path / ".git" / "objects" / "pack"
        target.mkdir(parents=True, exist_ok=True)
        files = sorted((self.path / "pack").iterdir(), key=lambda p: (p.suffix == ".idx", p.name))
        for item in files:
            if item.suffix in (".pack", ".idx", ".rev", ".bitmap"):
                os.replace(item, target / item.name)

    def remove(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


async def index_pack(quarantine: Quarantine, stream: IO[bytes], offset: int) -> str | None:
    """Index the pack into the quarantine. Returns an error string for ``unpack <error>`` or None."""
    stream.seek(offset)
    first = stream.read(CHUNK)
    if not first:
        return "no pack data"
    proc = await asyncio.create_subprocess_exec(
        "git",
        "index-pack",
        "--stdin",
        "--fix-thin",
        "--strict",
        cwd=quarantine.repo.path,
        env=quarantine.env(),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stderr is not None
    stdin, stderr = proc.stdin, proc.stderr

    async def feed() -> None:
        chunk = first
        try:
            while chunk:
                stdin.write(chunk)
                await stdin.drain()
                chunk = await asyncio.to_thread(stream.read, CHUNK)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            stdin.close()

    try:
        _, err = await asyncio.wait_for(asyncio.gather(feed(), stderr.read()), timeout=PROCESS_TIMEOUT_S)
        await asyncio.wait_for(proc.wait(), timeout=PROCESS_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return "index-pack timed out"
    if proc.returncode != 0:
        log.info("git_http.index_pack_failed", error=err.decode(errors="replace")[:500])
        return "index-pack failed"
    return None


def report_status(results: list[RefResult], *, unpack_error: str | None, sideband: bool, messages: list[str]) -> bytes:
    """``report-status`` (inside side-band 1 when negotiated). Messer's messages go on band 2 like hook output,
    so they are shown even when the client asked for ``quiet`` (which only silences transfer progress)."""
    status = pkt(f"unpack {unpack_error or 'ok'}\n")
    for result in results:
        status += pkt(f"ok {result.ref}\n" if result.error is None else f"ng {result.ref} {result.error}\n")
    status += FLUSH
    if not sideband:
        return status
    out = b""
    for message in messages:
        out += pkt(b"\x02" + f"{message}\n".encode())
    for i in range(0, len(status), 65515):
        out += pkt(b"\x01" + status[i : i + 65515])
    return out + FLUSH


async def spool_body(chunks: AsyncIterator[bytes], *, gzip: bool) -> IO[bytes]:
    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    try:
        await read_body(chunks, gzip=gzip, limit=MAX_PUSH_BYTES, target=spool)
    except BaseException:
        spool.close()
        raise
    spool.seek(0)
    return spool


def empty_report(req: ReceiveRequest, error: str) -> PushReport:
    return PushReport(results=[RefResult(u.ref, error) for u in req.updates])
