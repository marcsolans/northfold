"""Studio workflows: graph ↔ ``workflow.py`` (+ ``layout.json``, ``nodes.py``) in the project repository."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import Project, Workforce
from messer_common.studio.project_files import member_manifest
from messer_common.studio.workflow_spec import (
    CUSTOM_NODES_FILE,
    LAYOUT_FILE,
    RUNTIME_FILE,
    CustomFunction,
    Position,
    WorkflowConfig,
    auto_layout,
    custom_function_stub,
    custom_nodes_template,
    layout_json,
    load_stored_config,
    parse_custom_nodes,
    parse_layout,
    parse_workflow_code,
    remove_custom_function,
    render_layout,
    starter_config,
    stored_config,
    validate_workflow,
    with_positions,
    workflow_member_files,
)

from ..errors import ApiError, Conflict
from . import projects as svc

_FUNCTION_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(slots=True)
class WorkflowState:
    member: Workforce
    config: WorkflowConfig | None
    viewport: dict[str, float]
    positions: dict[str, Position]
    code: str
    custom_code: str
    custom_functions: list[CustomFunction]
    custom_error: dict[str, Any] | None
    commit: str


def _syntax_error(exc: SyntaxError, filename: str) -> ApiError:
    return ApiError(
        f"Error de sintaxis en {filename}, línea {exc.lineno}: {exc.msg}",
        code="syntax_error",
        details={"file": filename, "line": exc.lineno, "column": exc.offset},
    )


def _check_syntax(code: str, filename: str) -> None:
    try:
        compile(code, filename, "exec")
    except SyntaxError as exc:
        raise _syntax_error(exc, filename) from exc


async def members_by_kind(session: AsyncSession, project: Project, exclude: str | None = None) -> dict[str, str]:
    rows = (
        await session.execute(select(Workforce.name, Workforce.kind).where(Workforce.project_id == project.id))
    ).all()
    return {name: kind for name, kind in rows if name != exclude}


async def get_workflow(session: AsyncSession, project: Project, name: str) -> Workforce:
    member = await svc.get_member(session, project, name)
    if member.kind != "workflow":
        raise ApiError(f"«{name}» es un agente, no un flujo", code="not_a_workflow", status_code=404)
    return member


async def _custom_code(project: Project, member: Workforce) -> str:
    return await svc.repo_for(project).read_working(f"{member.path}/{CUSTOM_NODES_FILE}") or ""


def _functions(code: str) -> tuple[list[CustomFunction], dict[str, Any] | None]:
    try:
        return parse_custom_nodes(code), None
    except SyntaxError as exc:
        return [], {"message": exc.msg, "line": exc.lineno, "column": exc.offset}


async def load_state(session: AsyncSession, project: Project, member: Workforce) -> WorkflowState:
    repo = svc.repo_for(project)
    code = await repo.read_working(f"{member.path}/workflow.py") or ""
    positions, viewport = parse_layout(await repo.read_working(f"{member.path}/{LAYOUT_FILE}"))
    config = load_stored_config(member.config_json) if member.source_mode == "config" else None
    if config is not None:
        missing = auto_layout(config)
        config = with_positions(config, {**missing, **positions})
    custom_code = await _custom_code(project, member)
    functions, error = _functions(custom_code)
    return WorkflowState(
        member=member,
        config=config,
        viewport=viewport,
        positions=positions,
        code=code,
        custom_code=custom_code,
        custom_functions=functions,
        custom_error=error,
        commit=await repo.head(),
    )


def _invalid(issues: list[dict[str, Any]]) -> ApiError:
    return ApiError(
        issues[0]["message"] if len(issues) == 1 else f"El flujo tiene {len(issues)} problemas",
        code="invalid_workflow",
        details={"issues": issues},
    )


async def _validated(
    session: AsyncSession, project: Project, member_name: str, config: WorkflowConfig, functions: list[str]
) -> WorkflowConfig:
    if config.name != member_name:
        raise ApiError("El nombre de un flujo no se puede cambiar; duplica el flujo", code="rename_unsupported")
    members = await members_by_kind(session, project, exclude=member_name)
    issues = validate_workflow(config, members=members, custom_functions=functions)
    if issues:
        raise _invalid(issues)
    return config.model_copy(update={"custom_nodes": functions})


async def create_workflow(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    *,
    name: str,
    description: str = "",
    template: str = "blank",
    config: WorkflowConfig | None = None,
) -> Workforce:
    exists = (
        await session.execute(select(Workforce.id).where(Workforce.project_id == project.id, Workforce.name == name))
    ).first()
    if exists is not None:
        raise Conflict(f"Ya existe «{name}» en este proyecto", code="name_taken")
    cfg = (
        config.model_copy(update={"name": name}) if config is not None else starter_config(template, name, description)
    )
    if description and not cfg.description:
        cfg = cfg.model_copy(update={"description": description})
    nodes_code = custom_nodes_template(name)
    functions = [f.name for f in parse_custom_nodes(nodes_code)]
    members = await members_by_kind(session, project)
    issues = validate_workflow(cfg, members=members, custom_functions=functions)
    if issues:
        raise _invalid(issues)
    given = {n.id: n.position for n in cfg.nodes if n.position is not None}
    cfg = with_positions(cfg.model_copy(update={"custom_nodes": functions}), {**auto_layout(cfg), **given})
    member = Workforce(
        org_id=project.org_id,
        project_id=project.id,
        kind="workflow",
        name=name,
        description=cfg.description,
        path=f"workforce/{name}",
        config_json=stored_config(cfg),
        source_mode="config",
    )
    session.add(member)
    await session.flush()
    author = await svc.author_for(session, principal)
    await svc.repo_for(project).write(
        workflow_member_files(member_id=str(member.id), config=cfg, nodes_code=nodes_code),
        message=f"Add workflow {name}",
        author=author.name,
        email=author.email,
    )
    await audit.record(
        session,
        action="workforce.created",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"name": name, "kind": "workflow", "template": template},
    )
    return member


async def update_graph(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    member: Workforce,
    config: WorkflowConfig,
    viewport: dict[str, Any] | None,
    message: str | None = None,
) -> str:
    """Save the canvas: regenerates ``workflow.py`` (config mode) and writes ``layout.json``."""
    functions, error = _functions(await _custom_code(project, member))
    if error is not None and any(n.type == "custom" for n in config.nodes):
        raise ApiError(
            "Corrige el error de sintaxis de nodes.py antes de guardar", code="custom_nodes_invalid", details=error
        )
    cfg = await _validated(session, project, member.name, config, [f.name for f in functions])
    files: dict[str, str | bytes | None] = dict(
        workflow_member_files(member_id=str(member.id), config=cfg, viewport=viewport)
    )
    author = await svc.author_for(session, principal)
    commit = await svc.repo_for(project).write(
        files, message=message or f"Update {member.name} workflow", author=author.name, email=author.email
    )
    member.config_json = stored_config(cfg)
    member.description = cfg.description
    member.source_mode = "config"
    await audit.record(
        session,
        action="workforce.updated",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"kind": "workflow", "nodes": len(cfg.nodes), "edges": len(cfg.edges), "commit": commit},
    )
    return commit


async def update_code(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, code: str
) -> tuple[str, str]:
    """Write hand-edited ``workflow.py``. Returns (commit, source_mode); the canvas follows when it parses back."""
    _check_syntax(code, f"{member.path}/workflow.py")
    parsed = parse_workflow_code(code)
    if parsed is not None and parsed.name != member.name:
        parsed = None
    if parsed is not None:
        functions, _ = _functions(await _custom_code(project, member))
        members = await members_by_kind(session, project, exclude=member.name)
        if validate_workflow(parsed, members=members, custom_functions=[f.name for f in functions]):
            parsed = None
        else:
            parsed = parsed.model_copy(update={"custom_nodes": [f.name for f in functions]})
    source_mode = "config" if parsed is not None else "code"
    repo = svc.repo_for(project)
    files: dict[str, str | bytes | None] = {f"{member.path}/workflow.py": code}
    if parsed is not None:
        positions, viewport = parse_layout(await repo.read_working(f"{member.path}/{LAYOUT_FILE}"))
        laid_out = with_positions(parsed, {**auto_layout(parsed), **positions})
        files[f"{member.path}/{LAYOUT_FILE}"] = render_layout(laid_out, viewport)
    files[f"{member.path}/messer.yaml"] = member_manifest(
        member_id=str(member.id),
        kind="workflow",
        source_mode=source_mode,
        config=stored_config(parsed) if parsed is not None else member.config_json,
    )
    author = await svc.author_for(session, principal)
    commit = await repo.write(files, message=f"Edit {member.name} code", author=author.name, email=author.email)
    member.source_mode = source_mode
    if parsed is not None:
        member.config_json = stored_config(parsed)
        member.description = parsed.description
    await audit.record(
        session,
        action="workforce.code_edited",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"kind": "workflow", "source_mode": source_mode, "commit": commit},
    )
    return commit, source_mode


async def update_layout(
    session: AsyncSession,
    principal: Principal,
    project: Project,
    member: Workforce,
    positions: dict[str, Position],
    viewport: dict[str, Any] | None,
) -> str:
    """Positions and viewport only (``workflow.py`` is untouched)."""
    repo = svc.repo_for(project)
    current, current_view = parse_layout(await repo.read_working(f"{member.path}/{LAYOUT_FILE}"))
    merged = {**current, **positions}
    view = {**current_view, **(viewport or {})}
    config = load_stored_config(member.config_json) if member.source_mode == "config" else None
    if config is not None:
        known = {n.id for n in config.nodes}
        merged = {k: v for k, v in merged.items() if k in known}
    text = layout_json(merged, view)
    author = await svc.author_for(session, principal)
    return await repo.write(
        {f"{member.path}/{LAYOUT_FILE}": text},
        message=f"Move {member.name} nodes",
        author=author.name,
        email=author.email,
    )


# ------------------------------------------------------------------------------------------ custom nodes


def _used_functions(member: Workforce) -> dict[str, list[str]]:
    config = load_stored_config(member.config_json) if member.source_mode == "config" else None
    used: dict[str, list[str]] = {}
    for n in config.nodes if config else []:
        if n.type == "custom":
            used.setdefault(str(n.config.get("function") or ""), []).append(n.id)
    return used


async def _write_custom(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, code: str, message: str
) -> list[CustomFunction]:
    _check_syntax(code, f"{member.path}/{CUSTOM_NODES_FILE}")
    functions = parse_custom_nodes(code)
    names = {f.name for f in functions}
    missing = {fn: ids for fn, ids in _used_functions(member).items() if fn not in names}
    if missing:
        fn, ids = next(iter(missing.items()))
        raise Conflict(
            f"La función «{fn}» la usan los nodos {', '.join(ids)}; quítalos del lienzo antes de borrarla",
            code="function_in_use",
            details={"function": fn, "nodes": ids},
        )
    files: dict[str, str | bytes | None] = {f"{member.path}/{CUSTOM_NODES_FILE}": code}
    config = load_stored_config(member.config_json) if member.source_mode == "config" else None
    if config is not None:
        repo = svc.repo_for(project)
        positions, viewport = parse_layout(await repo.read_working(f"{member.path}/{LAYOUT_FILE}"))
        updated = with_positions(config.model_copy(update={"custom_nodes": [f.name for f in functions]}), positions)
        generated = workflow_member_files(member_id=str(member.id), config=updated, viewport=viewport)
        files[f"{member.path}/workflow.py"] = generated[f"{member.path}/workflow.py"]
        files[f"{member.path}/messer.yaml"] = generated[f"{member.path}/messer.yaml"]
        files[f"{member.path}/{RUNTIME_FILE}"] = generated[f"{member.path}/{RUNTIME_FILE}"]
        member.config_json = stored_config(updated)
    author = await svc.author_for(session, principal)
    await svc.repo_for(project).write(files, message=message, author=author.name, email=author.email)
    await audit.record(
        session,
        action="workforce.custom_nodes_updated",
        principal=principal,
        entity_type="workforce",
        entity_id=member.id,
        diff={"functions": sorted(names)},
    )
    return functions


async def save_custom_nodes(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, code: str
) -> list[CustomFunction]:
    return await _write_custom(session, principal, project, member, code, f"Edit {member.name} custom nodes")


async def add_custom_node(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, name: str, description: str
) -> list[CustomFunction]:
    if not _FUNCTION_NAME.match(name):
        raise ApiError("El nombre usa minúsculas, números y guiones bajos, empezando por letra", code="invalid_name")
    code = await _custom_code(project, member)
    functions, error = _functions(code)
    if error is not None:
        raise ApiError(
            "nodes.py tiene un error de sintaxis; corrígelo primero", code="custom_nodes_invalid", details=error
        )
    if any(f.name == name for f in functions):
        raise Conflict(f"Ya existe la función «{name}»", code="name_taken")
    base = code if code.strip() else "from typing import Any\n"
    if "from typing import Any" not in base and "import typing" not in base:
        base = "from typing import Any\n\n" + base
    new_code = base.rstrip() + "\n" + custom_function_stub(name, description)
    return await _write_custom(session, principal, project, member, new_code, f"Add custom node {name}")


async def remove_custom_node(
    session: AsyncSession, principal: Principal, project: Project, member: Workforce, name: str
) -> list[CustomFunction]:
    code = await _custom_code(project, member)
    try:
        new_code = remove_custom_function(code, name)
    except SyntaxError as exc:
        raise _syntax_error(exc, CUSTOM_NODES_FILE) from exc
    except KeyError as exc:
        raise ApiError(f"No existe la función «{name}»", code="not_found", status_code=404) from exc
    return await _write_custom(session, principal, project, member, new_code, f"Remove custom node {name}")
