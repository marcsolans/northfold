"""GitHub sync kernel: configuration, credentials (GitHub App or fine-grained PAT), the git remote of a project,
webhook signatures and the "connected" marker used by the commit hook.

Two credential modes:

* **GitHub App** (``GITHUB_APP_ID`` + ``GITHUB_APP_PRIVATE_KEY`` + ``GITHUB_WEBHOOK_SECRET``): an app JWT (RS256)
  is exchanged for short-lived installation access tokens; the app's webhook (one URL for every project) is
  verified with ``GITHUB_WEBHOOK_SECRET``.
* **Personal access token**: a fine-grained token pasted by an admin, stored encrypted; each project gets its
  own webhook secret.

Git network operations always go through ``git_remote(...)`` → ``projects_repo.RemoteSpec``. The git and REST
base URLs come from server configuration only (never from users), so tests can point git at local bare
repositories (``MESSER_GITHUB_GIT_URL=file:///tmp/…``) and the REST client at a mock transport.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from datetime import datetime
from functools import lru_cache
from typing import Any

import httpx
import jwt
from pydantic_settings import BaseSettings, SettingsConfigDict

from .projects_repo import ProjectRepo, RemoteSpec
from .settings import REPO_ROOT

API_VERSION = "2022-11-28"
MARKER = "messer-github.json"
_REPO_RE = re.compile(r"^(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/(?P<name>[A-Za-z0-9._-]{1,100})$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


class GitHubSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),), env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    github_app_id: str = ""
    github_app_private_key: str = ""  # PEM; literal "\n" sequences are accepted (single-line env values)
    github_app_slug: str = ""  # for the "install the app" link
    github_webhook_secret: str = ""
    messer_github_api_url: str = "https://api.github.com"
    messer_github_git_url: str = "https://github.com"

    @property
    def private_key(self) -> str:
        return self.github_app_private_key.replace("\\n", "\n").strip()

    @property
    def app_configured(self) -> bool:
        return bool(self.github_app_id and self.private_key and self.github_webhook_secret)


@lru_cache(maxsize=1)
def get_github_settings() -> GitHubSettings:
    return GitHubSettings()


def reset_github_settings() -> None:
    get_github_settings.cache_clear()
    _installation_tokens.clear()


class GitHubError(Exception):
    def __init__(self, message: str, *, code: str = "github_error", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


# ------------------------------------------------------------------------------------------ validation


def parse_repo(full_name: str) -> tuple[str, str]:
    value = full_name.strip().removeprefix("https://github.com/").removesuffix(".git").strip("/")
    match = _REPO_RE.match(value)
    if not match or match.group("name") in (".", ".."):
        raise GitHubError("Indica el repositorio como propietario/nombre (p. ej. acme/soporte)", code="invalid_repo")
    return match.group("owner"), match.group("name")


def validate_branch(branch: str) -> str:
    value = branch.strip().removeprefix("refs/heads/")
    if (
        not _BRANCH_RE.match(value)
        or value.startswith(("-", "/", "."))
        or value.endswith(("/", ".", ".lock"))
        or ".." in value
        or "//" in value
        or "@{" in value
    ):
        raise GitHubError("Nombre de rama no válido", code="invalid_branch")
    return value


# --------------------------------------------------------------------------------------------- REST API

# Tests replace this with ``httpx.MockTransport``; ``None`` uses the network.
api_transport: httpx.AsyncBaseTransport | None = None


async def api_request(
    method: str, path: str, *, token: str | None = None, app_jwt: str | None = None, json_body: Any = None
) -> httpx.Response:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": API_VERSION, "User-Agent": "Messer"}
    if app_jwt:
        headers["Authorization"] = f"Bearer {app_jwt}"
    elif token:
        headers["Authorization"] = f"Bearer {token}"
    base = get_github_settings().messer_github_api_url.rstrip("/")
    try:
        async with httpx.AsyncClient(base_url=base, timeout=20, transport=api_transport) as client:
            return await client.request(method, path, headers=headers, json=json_body)
    except httpx.HTTPError as exc:
        raise GitHubError("No se ha podido contactar con GitHub", code="github_unreachable", status=502) from exc


def _api_error(res: httpx.Response, fallback: str) -> GitHubError:
    if res.status_code == 401:
        return GitHubError("GitHub ha rechazado las credenciales (token caducado o no válido)", code="github_auth")
    if res.status_code in (403, 404):
        return GitHubError(fallback, code="github_no_access")
    return GitHubError(f"GitHub respondió {res.status_code}", code="github_error", status=502)


def app_jwt() -> str:
    """JWT signed with the app's private key (valid ~9 minutes) used to mint installation tokens."""
    settings = get_github_settings()
    if not settings.app_configured:
        raise GitHubError("La GitHub App no está configurada", code="github_app_unavailable")
    now = int(time.time())
    try:
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": settings.github_app_id}, settings.private_key, algorithm="RS256"
        )
    except (ValueError, TypeError, jwt.PyJWTError) as exc:
        raise GitHubError("La clave privada de la GitHub App no es válida", code="github_app_key") from exc


async def installation_for_repo(owner: str, repo: str) -> int:
    res = await api_request("GET", f"/repos/{owner}/{repo}/installation", app_jwt=app_jwt())
    if res.status_code != 200:
        raise _api_error(res, f"La GitHub App de Messer no está instalada en {owner}/{repo}")
    return int(res.json()["id"])


_installation_tokens: dict[int, tuple[str, float]] = {}


async def installation_token(installation_id: int) -> str:
    cached = _installation_tokens.get(installation_id)
    if cached and cached[1] - time.time() > 300:
        return cached[0]
    res = await api_request("POST", f"/app/installations/{installation_id}/access_tokens", app_jwt=app_jwt())
    if res.status_code != 201:
        raise _api_error(res, "La instalación de la GitHub App ya no tiene acceso")
    data = res.json()
    token = str(data["token"])
    expires = time.time() + 3600
    raw_exp = data.get("expires_at")
    if isinstance(raw_exp, str):
        try:
            expires = datetime.fromisoformat(raw_exp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    _installation_tokens[installation_id] = (token, expires)
    return token


async def repo_info(token: str, owner: str, repo: str) -> dict[str, Any]:
    """Repository metadata; the token must be able to push (contents: read and write)."""
    res = await api_request("GET", f"/repos/{owner}/{repo}", token=token)
    if res.status_code != 200:
        raise _api_error(res, f"El token no tiene acceso a {owner}/{repo}")
    data: dict[str, Any] = res.json()
    permissions = data.get("permissions") or {}
    if permissions and not (permissions.get("push") or permissions.get("admin") or permissions.get("maintain")):
        raise GitHubError(
            f"El token puede leer {owner}/{repo} pero no escribir: concede «Contents: Read and write»",
            code="github_read_only",
        )
    return data


async def create_webhook(token: str, owner: str, repo: str, *, url: str, secret: str) -> int | None:
    """Create the push webhook with the token (needs «Webhooks: Read and write»). ``None`` if not allowed."""
    res = await api_request(
        "POST",
        f"/repos/{owner}/{repo}/hooks",
        token=token,
        json_body={
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {"url": url, "content_type": "json", "secret": secret, "insecure_ssl": "0"},
        },
    )
    if res.status_code == 201:
        return int(res.json()["id"])
    if res.status_code in (403, 404, 422):
        return None
    raise _api_error(res, "No se ha podido crear el webhook")


async def delete_webhook(token: str, owner: str, repo: str, hook_id: int) -> bool:
    res = await api_request("DELETE", f"/repos/{owner}/{repo}/hooks/{hook_id}", token=token)
    return res.status_code in (204, 404)


# ------------------------------------------------------------------------------------------ git remote


def git_remote(owner: str, repo: str, token: str | None) -> RemoteSpec:
    base = get_github_settings().messer_github_git_url.rstrip("/")
    url = f"{base}/{owner}/{repo}.git"
    if not token or url.startswith("file:"):
        return RemoteSpec(url=url)
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return RemoteSpec(url=url, headers=(f"Authorization: Basic {basic}",))


# ------------------------------------------------------------------------------------------- webhooks


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    return hmac.compare_digest(sign(secret, body), header.strip())


# --------------------------------------------------------------------------------------------- marker


def mark_connected(repo: ProjectRepo, info: dict[str, Any] | None) -> None:
    """Write (or remove, with ``None``) the non-secret marker that tells the commit hook to enqueue a push."""
    marker = repo.path / ".git" / MARKER
    if info is None:
        marker.unlink(missing_ok=True)
        return
    if (repo.path / ".git").is_dir():
        marker.write_text(json.dumps(info), encoding="utf-8")


def is_marked(project_id: str, projects_dir: Any) -> bool:
    return (projects_dir / project_id / ".git" / MARKER).is_file()
