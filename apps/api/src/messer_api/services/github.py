"""GitHub sync for projects (spec 7.10).

* Every Messer commit (``ProjectRepo`` commit hook) enqueues a debounced ``GITHUB_PUSH`` for connected projects.
* A push to the connected branch on GitHub reaches ``POST /api/github/webhook`` and enqueues ``GITHUB_PULL``.
* Both jobs run :func:`sync_project`: fetch the branch, merge what GitHub has that Messer does not (fast-forward,
  or a merge commit where Messer's side wins only on real conflicts and the commit message lists them), sync the
  changed workforce members into the database (a ``source="github"`` version per member plus a project version,
  audit, builder notifications), then push what Messer has that GitHub does not.

State lives in ``projects.github_config`` (credentials encrypted with ``messer_common.security``).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import yaml
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common import github as gh
from messer_common.db import Principal, system_session
from messer_common.db.models import FeatureFlag, Membership, Notification, Project, User, Version, Workforce
from messer_common.logging import get_logger
from messer_common.projects_repo import MergeResult, ProjectRepo, PushRejected, RepoError
from messer_common.queue import Jobs, enqueue
from messer_common.roles import at_least
from messer_common.security import DecryptionError, decrypt, encrypt, random_token
from messer_common.settings import get_settings
from messer_common.studio.agent_spec import parse_agent_code

from ..errors import ApiError, Conflict, Forbidden

log = get_logger("messer.api.github")

Mode = Literal["app", "pat"]
PUSH_DEBOUNCE_S = 5
SYNC_ATTEMPTS = 3
MAX_BLOB_BYTES = 25 * 1024 * 1024
MAX_FILES = 20_000
SYNC_AUTHOR = "Messer"
SYNC_EMAIL = "github-sync@messer.local"
_MEMBER_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789_")
_STATUS_KEYS = (
    "last_push_at",
    "last_push_sha",
    "last_pull_at",
    "last_pull_sha",
    "last_sync_at",
    "last_error",
    "last_error_at",
    "last_conflicts",
)


class SyncBusy(Exception):
    """Another sync of the same project holds the lock."""


def _api_error(exc: gh.GitHubError) -> ApiError:
    return ApiError(exc.message, code=exc.code, status_code=exc.status)


def webhook_url() -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/github/webhook"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cfg(project: Project) -> dict[str, Any]:
    return dict(project.github_config or {})


def is_connected(project: Project) -> bool:
    cfg = _cfg(project)
    return bool(project.github_repo and cfg.get("mode") in ("app", "pat") and cfg.get("branch"))


def status(project: Project, *, head: str | None = None) -> dict[str, Any]:
    cfg = _cfg(project)
    settings = gh.get_github_settings()
    connected = is_connected(project)
    mode = cfg.get("mode") if connected else None
    webhook: str | None = None
    if mode == "app":
        webhook = "app"
    elif mode == "pat":
        webhook = "auto" if cfg.get("webhook_id") else "manual"
    error = cfg.get("last_error") if connected else None
    state = "disconnected"
    if connected:
        state = "error" if error else ("synced" if cfg.get("last_sync_at") else "pending")
    return {
        "connected": connected,
        "state": state,
        "mode": mode,
        "repo": project.github_repo if connected else None,
        "repo_url": f"https://github.com/{project.github_repo}" if connected and project.github_repo else None,
        "branch": cfg.get("branch") if connected else None,
        "app_available": settings.app_configured,
        "app_install_url": (
            f"https://github.com/apps/{settings.github_app_slug}/installations/new"
            if settings.app_configured and settings.github_app_slug
            else None
        ),
        "webhook_url": webhook_url(),
        "webhook": webhook,
        "connected_at": cfg.get("connected_at") if connected else None,
        "connected_by": cfg.get("connected_by") if connected else None,
        "head": head,
        **{key: (cfg.get(key) if connected else None) for key in _STATUS_KEYS},
    }


async def _flag_allows(org_id: uuid.UUID) -> bool:
    """The ``github_sync`` feature flag (managed in /admin). A missing flag means enabled."""
    from .limits import feature_flag_enabled

    async with system_session() as s:
        if await s.get(FeatureFlag, "github_sync") is None:
            return True
        return await feature_flag_enabled(s, "github_sync", org_id)


async def connect(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    repo: str,
    branch: str | None,
    mode: Mode,
    token: str | None,
    installation_id: int | None,
) -> dict[str, Any]:
    """Connect (or reconfigure) the project's repository. Returns the status plus, in PAT mode without an
    automatically created webhook, the webhook secret (shown only once)."""
    if not await _flag_allows(project.org_id):
        raise Forbidden("La sincronización con GitHub no está disponible para tu organización", code="feature_disabled")
    try:
        owner, name = gh.parse_repo(repo)
        full = f"{owner}/{name}"
        old = _cfg(project)
        same_repo = is_connected(project) and (project.github_repo or "").lower() == full.lower()
        new_cfg: dict[str, Any] = {"mode": mode}
        if mode == "app":
            if not gh.get_github_settings().app_configured:
                raise ApiError(
                    "La GitHub App no está configurada en esta instalación de Messer; usa un token personal",
                    code="github_app_unavailable",
                )
            inst = installation_id or await gh.installation_for_repo(owner, name)
            access = await gh.installation_token(inst)
            info = await gh.repo_info(access, owner, name)
            new_cfg["installation_id"] = int(inst)
        else:
            secret_token = (token or "").strip()
            if not secret_token and same_repo and old.get("mode") == "pat" and old.get("token"):
                secret_token = decrypt(str(old["token"]))
            if not secret_token:
                raise ApiError("Pega un token personal de GitHub con acceso al repositorio", code="token_required")
            info = await gh.repo_info(secret_token, owner, name)
            new_cfg["token"] = encrypt(secret_token)
        target_branch = gh.validate_branch(branch or str(info.get("default_branch") or "main"))
    except gh.GitHubError as exc:
        raise _api_error(exc) from exc
    except DecryptionError as exc:
        raise ApiError("El token guardado no se puede descifrar; pégalo de nuevo", code="token_required") from exc

    clash = (
        await session.execute(
            select(Project.id, Project.github_config).where(
                Project.org_id == project.org_id,
                Project.id != project.id,
                Project.archived_at.is_(None),
                func.lower(Project.github_repo) == full.lower(),
            )
        )
    ).all()
    for _pid, other_cfg in clash:
        if (other_cfg or {}).get("branch") == target_branch:
            raise Conflict(f"Otro proyecto ya sincroniza {full}@{target_branch}", code="github_branch_in_use")

    new_cfg["branch"] = target_branch
    revealed_secret: str | None = None
    if mode == "pat":
        keep_hook = same_repo and old.get("mode") == "pat" and old.get("webhook_secret")
        if keep_hook:
            new_cfg["webhook_secret"] = old["webhook_secret"]
            new_cfg["webhook_id"] = old.get("webhook_id")
        else:
            secret = random_token(32)
            new_cfg["webhook_secret"] = encrypt(secret)
            try:
                hook_id = await gh.create_webhook(
                    decrypt(new_cfg["token"]), owner, name, url=webhook_url(), secret=secret
                )
            except gh.GitHubError as exc:
                log.info("github.webhook_create_failed", project_id=str(project.id), code=exc.code)
                hook_id = None
            new_cfg["webhook_id"] = hook_id
            if hook_id is None:
                revealed_secret = secret
        if old.get("mode") == "pat" and old.get("webhook_id") and not keep_hook:
            await _delete_old_hook(project.github_repo, old)
    if same_repo and old.get("branch") == target_branch:
        for key in (*_STATUS_KEYS, "connected_at", "connected_by"):
            if key in old:
                new_cfg[key] = old[key]
    new_cfg.setdefault("connected_at", _now())
    new_cfg.setdefault("connected_by", principal.email or (str(principal.user_id) if principal.user_id else None))
    project.github_repo = full
    project.github_config = new_cfg
    repo_obj = ProjectRepo.for_project(str(project.id))
    gh.mark_connected(repo_obj, {"repo": full, "branch": target_branch})
    await audit.record(
        session,
        action="github.connected",
        principal=principal,
        entity_type="project",
        entity_id=project.id,
        diff={"repo": full, "branch": target_branch, "mode": mode},
    )
    await session.flush()
    await enqueue_sync(project.id, reason="connect")
    out = status(project, head=await repo_head(repo_obj))
    if revealed_secret:
        out["webhook_secret"] = revealed_secret
    return out


async def _delete_old_hook(full: str | None, cfg: dict[str, Any]) -> None:
    if not full or not cfg.get("webhook_id") or not cfg.get("token"):
        return
    try:
        owner, name = gh.parse_repo(full)
        await gh.delete_webhook(decrypt(str(cfg["token"])), owner, name, int(cfg["webhook_id"]))
    except (gh.GitHubError, DecryptionError, ValueError) as exc:
        log.info("github.webhook_delete_failed", repo=full, error=str(exc))


async def disconnect(session: AsyncSession, principal: Principal, project: Project) -> None:
    if not project.github_repo and not project.github_config:
        return
    cfg = _cfg(project)
    if cfg.get("mode") == "pat":
        await _delete_old_hook(project.github_repo, cfg)
    previous = project.github_repo
    project.github_repo = None
    project.github_config = {}
    gh.mark_connected(ProjectRepo.for_project(str(project.id)), None)
    await audit.record(
        session,
        action="github.disconnected",
        principal=principal,
        entity_type="project",
        entity_id=project.id,
        diff={"repo": previous},
    )


async def rotate_webhook_secret(session: AsyncSession, principal: Principal, project: Project) -> str:
    cfg = _cfg(project)
    if not is_connected(project) or cfg.get("mode") != "pat":
        raise ApiError("Solo los proyectos conectados con token personal tienen secreto propio", code="not_pat")
    secret = random_token(32)
    cfg["webhook_secret"] = encrypt(secret)
    if cfg.get("webhook_id"):
        await _delete_old_hook(project.github_repo, cfg)
        cfg["webhook_id"] = None
    project.github_config = cfg
    await audit.record(
        session,
        action="github.webhook_secret_rotated",
        principal=principal,
        entity_type="project",
        entity_id=project.id,
    )
    return secret


async def repo_head(repo: ProjectRepo) -> str | None:
    if not repo.exists:
        return None
    try:
        return await repo.head()
    except RepoError:
        return None


async def enqueue_sync(project_id: uuid.UUID | str, *, reason: str, after: str | None = None) -> str | None:
    """``commit``: debounced per project (one job per 5-second window, deferred so bursts of commits push once);
    ``connect``: deferred so the job sees the committed configuration; ``pull``: one job per pushed commit."""
    pid = str(project_id)
    if reason == "pull":
        return await enqueue(
            Jobs.GITHUB_PULL, pid, after, _job_id=f"github-pull:{pid}:{after or uuid.uuid4().hex}", _defer_by=1
        )
    if reason == "commit":
        bucket = int(time.time() // PUSH_DEBOUNCE_S)
        return await enqueue(Jobs.GITHUB_PUSH, pid, _job_id=f"github-push:{pid}:{bucket}", _defer_by=PUSH_DEBOUNCE_S)
    return await enqueue(Jobs.GITHUB_PUSH, pid, _job_id=f"github-push:{pid}:{reason}:{uuid.uuid4().hex}", _defer_by=2)


async def on_commit(project_id: str, sha: str) -> None:
    """``ProjectRepo`` commit hook: debounced push for projects connected to GitHub (marker file check, no DB)."""
    if not gh.is_marked(project_id, get_settings().projects_dir):
        return
    await enqueue_sync(project_id, reason="commit")


# ------------------------------------------------------------------------------------------- webhook


async def handle_webhook(body: bytes, *, event: str, signature: str | None) -> tuple[int, dict[str, Any]]:
    """Route a GitHub delivery to the connected projects whose secret verifies the signature."""
    try:
        payload = json.loads(body or b"{}")
    except json.JSONDecodeError:
        return 400, {"error": {"code": "invalid_json", "message": "Cuerpo JSON no válido", "details": {}}}
    if not isinstance(payload, dict):
        return 400, {"error": {"code": "invalid_json", "message": "Cuerpo JSON no válido", "details": {}}}
    repository = payload.get("repository") or {}
    full = str(repository.get("full_name") or "") if isinstance(repository, dict) else ""
    app_secret = gh.get_github_settings().github_webhook_secret
    async with system_session() as s:
        candidates = (
            (
                await s.execute(
                    select(Project).where(
                        func.lower(Project.github_repo) == full.lower(), Project.archived_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
            if full
            else []
        )
        verified: list[Project] = []
        for project in candidates:
            if not is_connected(project):
                continue
            cfg = _cfg(project)
            secret = app_secret
            if cfg.get("mode") == "pat":
                try:
                    secret = decrypt(str(cfg.get("webhook_secret") or ""))
                except DecryptionError:
                    continue
            if gh.verify_signature(secret, body, signature):
                verified.append(project)
        app_ok = bool(app_secret) and gh.verify_signature(app_secret, body, signature)
        if not verified:
            if app_ok:
                return 202, {"accepted": False, "reason": "not_connected"}
            return 401, {"error": {"code": "invalid_signature", "message": "Firma no válida", "details": {}}}
        if event == "ping":
            return 200, {"ok": True, "projects": len(verified)}
        if event != "push":
            return 202, {"accepted": False, "reason": "ignored_event"}
        ref = str(payload.get("ref") or "")
        after = str(payload.get("after") or "")
        queued: list[str] = []
        for project in verified:
            cfg = _cfg(project)
            if ref != f"refs/heads/{cfg.get('branch')}":
                continue
            if payload.get("deleted"):
                project.github_config = {
                    **cfg,
                    "last_error": f"La rama {cfg.get('branch')} se ha eliminado en GitHub",
                    "last_error_at": _now(),
                }
                continue
            if after and after == cfg.get("last_push_sha"):
                continue  # the echo of Messer's own push
            job = await enqueue_sync(project.id, reason="pull", after=after or None)
            queued.append(str(project.id))
            log.info("github.push_received", project_id=str(project.id), after=after, job_id=job)
    return 202, {"accepted": bool(queued), "projects": queued}


# ---------------------------------------------------------------------------------------------- sync


async def _record(project_id: uuid.UUID, repo_full: str, **fields: Any) -> None:
    async with system_session() as s:
        project = await s.get(Project, project_id, with_for_update=True)
        if project is None or (project.github_repo or "").lower() != repo_full.lower() or not is_connected(project):
            return  # disconnected (or reconnected elsewhere) while syncing
        cfg = _cfg(project)
        for key, value in fields.items():
            if value is None:
                cfg.pop(key, None)
            else:
                cfg[key] = value
        project.github_config = cfg


async def _token(cfg: dict[str, Any]) -> str:
    if cfg.get("mode") == "app":
        return await gh.installation_token(int(cfg["installation_id"]))
    return decrypt(str(cfg["token"]))


async def _vet_tree(repo: ProjectRepo, sha: str) -> None:
    """Refuse incoming trees Messer cannot run safely: symlinks, submodules, huge files."""
    entries = await repo.tree_entries(sha)
    if len(entries) > MAX_FILES:
        raise gh.GitHubError(f"El repositorio tiene más de {MAX_FILES} archivos", code="github_too_many_files")
    for entry in entries:
        if entry.mode == "120000":
            raise gh.GitHubError(f"Messer no admite enlaces simbólicos: {entry.path}", code="github_symlink")
        if entry.mode == "160000" or entry.type == "commit":
            raise gh.GitHubError(f"Messer no admite submódulos: {entry.path}", code="github_submodule")
        if entry.size is not None and entry.size > MAX_BLOB_BYTES:
            raise gh.GitHubError(f"El archivo {entry.path} supera 25 MB", code="github_file_too_large")


async def sync_project(project_id: uuid.UUID, *, reason: str) -> dict[str, Any]:
    """Two-way sync of one project with its GitHub branch (run by the worker)."""
    async with system_session() as s:
        project = await s.get(Project, project_id)
        if project is None or project.archived_at is not None or not is_connected(project):
            return {"status": "not_connected"}
        cfg = _cfg(project)
        full = str(project.github_repo)
    repo = ProjectRepo.for_project(str(project_id))
    if not repo.exists:
        return {"status": "no_repository"}
    gh.mark_connected(repo, {"repo": full, "branch": cfg["branch"]})
    from messer_common.events import get_redis

    lock = get_redis().lock(f"github-sync:{project_id}", timeout=600, blocking_timeout=5)
    if not await lock.acquire():
        raise SyncBusy(str(project_id))
    try:
        return await _sync_locked(project_id, repo, full, cfg, reason)
    finally:
        try:
            await lock.release()
        except Exception:  # lock expired: nothing to release
            log.warning("github.lock_release_failed", project_id=str(project_id))


async def _sync_locked(
    project_id: uuid.UUID, repo: ProjectRepo, full: str, cfg: dict[str, Any], reason: str
) -> dict[str, Any]:
    owner, name = gh.parse_repo(full)
    branch = str(cfg["branch"])
    result: dict[str, Any] = {"status": "ok", "reason": reason, "pulled": None, "pushed": None, "conflicts": []}
    try:
        pending = cfg.get("pending_apply")
        if isinstance(pending, dict) and pending.get("old") and pending.get("new"):
            applied = await apply_incoming(
                project_id,
                MergeResult(old_head=pending["old"], new_head=pending["new"], kind="merge"),
                remote_sha=str(pending.get("remote") or pending["new"]),
            )
            await _record(project_id, full, pending_apply=None)
            result["pulled"] = applied
        remote = gh.git_remote(owner, name, await _token(cfg))
        for _attempt in range(SYNC_ATTEMPTS):
            remote_sha = await repo.fetch_remote(remote, branch)
            head = await repo.head()
            if remote_sha and remote_sha != head and not await repo.is_ancestor(remote_sha, head):
                await _vet_tree(repo, remote_sha)
                merge = await repo.merge_commit(
                    remote_sha,
                    message=f"Merge GitHub {full}@{branch} into Messer",
                    author=SYNC_AUTHOR,
                    email=SYNC_EMAIL,
                )
                if merge.kind != "up_to_date":
                    await _record(
                        project_id,
                        full,
                        pending_apply={"old": merge.old_head, "new": merge.new_head, "remote": remote_sha},
                    )
                    applied = await apply_incoming(project_id, merge, remote_sha=remote_sha)
                    await _record(
                        project_id,
                        full,
                        pending_apply=None,
                        last_pull_at=_now(),
                        last_pull_sha=remote_sha,
                        last_conflicts=merge.conflicts,
                    )
                    result["pulled"] = applied
                    result["conflicts"] = merge.conflicts
                head = merge.new_head
            if remote_sha != head:
                try:
                    await repo.push_remote(remote, branch, head)
                except PushRejected:
                    continue  # GitHub moved between fetch and push: merge again
                await _record(project_id, full, last_push_at=_now(), last_push_sha=head)
                result["pushed"] = head
            break
        else:
            raise RepoError("GitHub ha recibido cambios durante la sincronización; se reintentará")
    except (gh.GitHubError, RepoError, DecryptionError) as exc:
        message = exc.message if isinstance(exc, gh.GitHubError) else str(exc)
        if isinstance(exc, DecryptionError):
            message = "No se pueden descifrar las credenciales de GitHub; vuelve a conectar el repositorio"
        log.warning("github.sync_failed", project_id=str(project_id), reason=reason, error=message)
        await _record(project_id, full, last_error=message[:500], last_error_at=_now())
        return {**result, "status": "error", "error": message}
    await _record(project_id, full, last_sync_at=_now(), last_error=None, last_error_at=None)
    return result


# ------------------------------------------------------------------------------- incoming → database


def _valid_member_name(name: str) -> bool:
    return 0 < len(name) <= 63 and name[0].isalpha() and name[0].islower() and set(name) <= _MEMBER_NAME_CHARS


def _parse_workflow(code: str) -> dict[str, Any] | None:
    """Workflow code → Studio config via ``messer_common.studio.workflow_spec`` when available; else code mode."""
    try:
        from messer_common.studio import workflow_spec  # type: ignore[attr-defined]
    except ImportError:
        return None
    parser = getattr(workflow_spec, "parse_workflow_code", None)
    if parser is None:
        return None
    try:
        parsed = parser(code)
    except Exception:  # a parser failure only means code mode
        return None
    if parsed is None:
        return None
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump(mode="json")  # type: ignore[no-any-return]
    return parsed if isinstance(parsed, dict) else None


async def _next_version(s: AsyncSession, entity_type: str, entity_id: uuid.UUID) -> int:
    last = (
        await s.execute(
            select(func.max(Version.version)).where(Version.entity_type == entity_type, Version.entity_id == entity_id)
        )
    ).scalar_one()
    return int(last or 0) + 1


async def apply_incoming(project_id: uuid.UUID, merge: MergeResult, *, remote_sha: str) -> dict[str, Any]:
    """Sync the workforce members changed between ``merge.old_head`` and ``merge.new_head`` into the database."""
    repo = ProjectRepo.for_project(str(project_id))
    head = merge.new_head
    changed = await repo.changed_files(merge.old_head, head)
    names = sorted({p.split("/")[1] for p in changed if p.startswith("workforce/") and p.count("/") >= 2})
    tip = await repo.commit_info(remote_sha)
    summary: dict[str, Any] = {
        "commit": head,
        "files": len(changed),
        "created": [],
        "updated": [],
        "deleted": [],
        "ignored": [],
        "conflicts": merge.conflicts,
    }
    async with system_session() as s:
        project = await s.get(Project, project_id)
        if project is None:
            return summary
        for name in names:
            if not _valid_member_name(name):
                summary["ignored"].append(name)
                continue
            await _sync_member(s, repo, project, name, head, tip.message, summary)
        number = await _next_version(s, "project", project.id)
        s.add(
            Version(
                org_id=project.org_id,
                project_id=project.id,
                entity_type="project",
                entity_id=project.id,
                version=number,
                git_commit=head,
                snapshot_json={"files": await repo.list_files(head), "github": {"remote": remote_sha}},
                author_id=None,
                message=f"GitHub: {tip.message}"[:500],
                source="github",
            )
        )
        summary["project_version"] = number
        await audit.record(
            s,
            action="github.pulled",
            org_id=project.org_id,
            entity_type="project",
            entity_id=project.id,
            diff={
                "commit": head,
                "remote": remote_sha,
                "author": tip.author,
                "created": summary["created"],
                "updated": summary["updated"],
                "deleted": summary["deleted"],
                "conflicts": merge.conflicts,
            },
        )
        await _notify(s, project, summary, tip.author)
    return summary


async def _sync_member(
    s: AsyncSession, repo: ProjectRepo, project: Project, name: str, head: str, subject: str, summary: dict[str, Any]
) -> None:
    base = f"workforce/{name}"
    member = (
        await s.execute(select(Workforce).where(Workforce.project_id == project.id, Workforce.name == name))
    ).scalar_one_or_none()
    manifest_raw = await repo.read(f"{base}/messer.yaml", head)
    try:
        manifest = yaml.safe_load(manifest_raw) if manifest_raw else {}
    except yaml.YAMLError:
        manifest = {}
    manifest = manifest if isinstance(manifest, dict) else {}
    files = set(await repo.list_files(head, prefix=f"{base}/"))
    kind = str(manifest.get("_type") or "")
    if kind not in ("agent", "workflow"):
        kind = "agent" if f"{base}/agent.py" in files else ("workflow" if f"{base}/workflow.py" in files else "")
    code_file = f"{base}/{'agent.py' if kind == 'agent' else 'workflow.py'}" if kind else ""
    if not kind or code_file not in files:
        if member is not None:
            await s.delete(member)
            summary["deleted"].append(name)
            await audit.record(
                s,
                action="workforce.deleted",
                org_id=project.org_id,
                entity_type="workforce",
                entity_id=member.id,
                diff={"name": name, "source": "github"},
            )
        return
    code = await repo.read(code_file, head) or ""
    config: dict[str, Any] | None = None
    if kind == "agent":
        parsed = parse_agent_code(code)
        if parsed is not None and parsed.name == name:
            config = parsed.model_dump(mode="json")
    else:
        config = _parse_workflow(code)
    source_mode = "config" if config is not None else "code"
    created = member is None
    if member is None:
        member_id = uuid.uuid4()
        raw_id = manifest.get("_id")
        try:
            candidate = uuid.UUID(str(raw_id)) if raw_id else None
        except ValueError:
            candidate = None
        if candidate is not None and await s.get(Workforce, candidate) is None:
            member_id = candidate
        member = Workforce(
            id=member_id,
            org_id=project.org_id,
            project_id=project.id,
            kind=kind,
            name=name,
            description=str((config or {}).get("description") or ""),
            path=base,
            config_json=config or {},
            source_mode=source_mode,
        )
        s.add(member)
        await s.flush()
        summary["created"].append(name)
    else:
        member.kind = kind
        member.source_mode = source_mode
        if config is not None:
            member.config_json = config
            if config.get("description") is not None:
                member.description = str(config["description"])
        summary["updated"].append(name)
    number = await _next_version(s, "workforce", member.id)
    s.add(
        Version(
            org_id=project.org_id,
            project_id=project.id,
            entity_type="workforce",
            entity_id=member.id,
            version=number,
            git_commit=head,
            snapshot_json={"config": member.config_json, "code": code, "source_mode": source_mode},
            author_id=None,
            message=f"GitHub: {subject}"[:500],
            source="github",
        )
    )
    member.current_version = number
    await audit.record(
        s,
        action="workforce.created" if created else "workforce.version_saved",
        org_id=project.org_id,
        entity_type="workforce",
        entity_id=member.id,
        diff={"name": name, "version": number, "commit": head, "source": "github", "source_mode": source_mode},
    )


async def _notify(s: AsyncSession, project: Project, summary: dict[str, Any], author: str) -> None:
    members = [*summary["created"], *summary["updated"], *summary["deleted"]]
    if members:
        body = f"{author} ha cambiado {', '.join(members[:5])}" + ("…" if len(members) > 5 else "")
    else:
        body = f"{author} ha enviado cambios ({summary['files']} archivos)"
    if summary["conflicts"]:
        body += f". Conflictos resueltos a favor de Messer: {', '.join(summary['conflicts'][:5])}"
    url = f"{get_settings().messer_web_url.rstrip('/')}/app/projects/{project.id}/settings"
    rows = (
        await s.execute(
            select(Membership.role, User.id)
            .join(User, User.id == Membership.user_id)
            .where(Membership.org_id == project.org_id)
        )
    ).all()
    for role, user_id in rows:
        if not at_least(role, "builder"):
            continue
        s.add(
            Notification(
                org_id=project.org_id,
                user_id=user_id,
                kind="github_sync",
                payload={
                    "title": f"Cambios desde GitHub en «{project.name}»",
                    "body": body,
                    "url": url,
                    "project_id": str(project.id),
                    "commit": summary["commit"],
                },
            )
        )
