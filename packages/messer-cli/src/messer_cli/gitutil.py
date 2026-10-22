"""Git helpers for ``messer push`` and for finding the Messer project of a working tree."""

from __future__ import annotations

import base64
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REMOTE_NAME = "messer"
# {base_url}/orgs/{org}/projects/{project}/git — base_url ends in /api/v1.
_REMOTE = re.compile(
    r"^(?P<base>https?://[^/\s]+(?:/[^\s]*?)?)/orgs/(?P<org>[0-9a-fA-F-]{36})/projects/(?P<project>[0-9a-fA-F-]{36})/git/?$"
)


class GitError(Exception):
    pass


@dataclass(slots=True)
class MesserRemote:
    name: str
    url: str
    base_url: str
    org_id: str
    project_id: str


def parse_remote_url(url: str) -> tuple[str, str, str] | None:
    """(base_url, org_id, project_id) of a Messer git URL, or None."""
    m = _REMOTE.match(url.strip().removesuffix(".git"))
    return (m["base"], m["org"].lower(), m["project"].lower()) if m else None


def git(*args: str, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> str:
    res = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, env=env, check=False, timeout=300
    )
    if check and res.returncode != 0:
        raise GitError(res.stderr.strip() or f"git {args[0]} failed")
    return res.stdout.strip()


def repo_root(cwd: Path) -> Path:
    try:
        return Path(git("rev-parse", "--show-toplevel", cwd=cwd))
    except (GitError, FileNotFoundError) as exc:
        raise GitError("Ejecuta este comando dentro de un repositorio git (git init)") from exc


def find_remote(cwd: Path) -> MesserRemote | None:
    """The remote named ``messer``, else the only remote pointing to a Messer project."""
    names = [n for n in git("remote", cwd=cwd).splitlines() if n]
    found: list[MesserRemote] = []
    for name in names:
        urls = [u for u in git("remote", "get-url", "--push", "--all", name, cwd=cwd).splitlines() if u]
        parsed = [(u, parse_remote_url(u)) for u in urls]
        matches = [(u, p) for u, p in parsed if p is not None]
        if name == REMOTE_NAME and not matches:
            raise GitError("El remoto «messer» no apunta a un proyecto de Messer; renómbralo antes de continuar")
        if matches:
            if len(urls) != 1:
                raise GitError(f"El remoto «{name}» tiene varias URLs de push; deja solo una")
            url, (base, org, project) = matches[0]
            found.append(MesserRemote(name=name, url=url, base_url=base, org_id=org, project_id=project))
    named = [r for r in found if r.name == REMOTE_NAME]
    if named:
        return named[0]
    if len(found) > 1:
        raise GitError("Hay varios remotos de Messer: llama «messer» al que quieras usar")
    return found[0] if found else None


def auth_env(url: str, api_key: str) -> dict[str, str]:
    """Credentials as an HTTP header scoped to ``url`` through ``GIT_CONFIG_*`` (never in argv or the URL)."""
    basic = base64.b64encode(f"messer:{api_key}".encode()).decode()
    env = dict(os.environ)
    count = int(env.get("GIT_CONFIG_COUNT", "0") or 0)
    env[f"GIT_CONFIG_KEY_{count}"] = f"http.{url}.extraHeader"
    env[f"GIT_CONFIG_VALUE_{count}"] = f"Authorization: Basic {basic}"
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env
