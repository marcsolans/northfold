"""``messer create``: a new project from the CLI templates (``packages/messer-core/cli/init-templates``), laid out
like a Messer project repository so that ``messer push`` imports it as-is (agents arrive in config mode)."""

from __future__ import annotations

import re
import uuid
from importlib import resources
from pathlib import Path

MEMBER_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
RESERVED = {"ui", "api", "workforce", "all"}


class ScaffoldError(Exception):
    pass


def templates_dir() -> Path:
    """Templates shipped in the wheel (``messer_cli/init_templates``) or, in a source checkout, the CLI's own."""
    packaged = resources.files("messer_cli") / "init_templates"
    if packaged.is_dir():
        return Path(str(packaged))
    source = Path(__file__).resolve().parents[3] / "messer-core" / "cli" / "init-templates"
    if source.is_dir():
        return source
    raise ScaffoldError("No se encuentran las plantillas de proyecto (init-templates)")


def _template(name: str, **values: str) -> str:
    text = (templates_dir() / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def validate_member_name(name: str) -> str:
    if not MEMBER_NAME.match(name) or name in RESERVED:
        raise ScaffoldError(
            f"Nombre no válido: «{name}». Usa minúsculas, números y guiones bajos, empezando por una letra "
            f"(y no {', '.join(sorted(RESERVED))})."
        )
    return name


def member_files(kind: str, name: str, model: str) -> dict[str, str]:
    validate_member_name(name)
    base = f"workforce/{name}"
    code = "agent.py" if kind == "agent" else "workflow.py"
    return {
        f"{base}/__init__.py": "",
        f"{base}/{code}": _template(code, name=name, model=model),
        f"{base}/messer.yaml": _template(
            "messer.yaml", id=str(uuid.uuid4()), type=kind, fully_qualified_name=f"{code}::{kind}"
        ),
        f"{base}/evals/basic.yaml": _template(f"{kind}_eval.yaml", name=name),
    }


def project_files(project_name: str, members: list[tuple[str, str]], model: str) -> dict[str, str]:
    slug = re.sub(r"[^a-z0-9-]+", "-", project_name.lower()).strip("-") or "messer-project"
    files: dict[str, str] = {
        "messer.project.yaml": _template("messer.project.yaml", project_name=project_name.replace('"', "'")),
        "knowledge.yaml": "# Knowledge bases linked to this project\nknowledge_bases: []\n",
        "triggers.yaml": "# Workflow triggers\ntriggers: []\n",
        "workforce/__init__.py": "",
        "interfaces/.gitkeep": "",
        "pyproject.toml": _template("pyproject.toml", app_name=slug),
        ".gitignore": _template("gitignore"),
        "README.md": _template("README.md", project_name=project_name),
    }
    seen: set[str] = set()
    for kind, name in members:
        if name in seen:
            raise ScaffoldError(f"Nombre repetido: {name}")
        seen.add(name)
        files.update(member_files(kind, name, model))
    return files


def write_project(target: Path, files: dict[str, str], *, allow_existing: bool = False) -> list[Path]:
    """Write the files; refuses a non-empty directory unless ``allow_existing`` (never overwrites a file)."""
    if target.exists() and any(target.iterdir()) and not allow_existing:
        raise ScaffoldError(f"El directorio {target} no está vacío")
    clashes = [rel for rel in files if (target / rel).exists()]
    if clashes:
        raise ScaffoldError(f"Ya existe: {clashes[0]}")
    written: list[Path] = []
    for rel, content in sorted(files.items()):
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def discover_members(project_dir: Path) -> list[tuple[str, str, str]]:
    """(name, kind, fqn) of every workforce member (``workforce/<name>/messer.yaml``)."""
    import yaml

    found: list[tuple[str, str, str]] = []
    base = project_dir / "workforce"
    for manifest in sorted(base.glob("*/messer.yaml")) if base.is_dir() else []:
        name = manifest.parent.name
        if not MEMBER_NAME.match(name):
            continue
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        data = data if isinstance(data, dict) else {}
        kind = str(data.get("_type") or ("agent" if (manifest.parent / "agent.py").exists() else "workflow"))
        default = "agent.py::agent" if kind == "agent" else "workflow.py::workflow"
        fqn = str(data.get("fqn") or default)
        file_part, _, attr = fqn.partition("::")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*\.py$", file_part) or not re.match(r"^[A-Za-z_]\w*$", attr):
            file_part, _, attr = default.partition("::")
        if (manifest.parent / file_part).is_file():
            found.append((name, kind, f"{file_part}::{attr}"))
    return found


def find_project_root(start: Path) -> Path:
    """The nearest directory with ``messer.project.yaml`` or ``workforce/`` (the project root)."""
    for candidate in [start, *start.parents]:
        if (candidate / "messer.project.yaml").is_file() or (candidate / "workforce").is_dir():
            return candidate
    raise ScaffoldError("No estás dentro de un proyecto de Messer (no hay workforce/ ni messer.project.yaml)")
