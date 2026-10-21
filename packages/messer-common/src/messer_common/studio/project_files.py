"""Files of a Messer project repository.

```
messer.project.yaml      metadata, environments, allowed models, channels
knowledge.yaml           linked knowledge bases
triggers.yaml            workflow triggers
workforce/<name>/        agent.py | workflow.py, messer.yaml, evals/*.yaml, tools.py (optional)
interfaces/<name>/       interface.json
pyproject.toml           runnable outside Messer (`messer start`, docker compose)
```
"""

from __future__ import annotations

from typing import Any

import yaml

from .agent_spec import AgentConfig, render_agent_code


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def project_manifest(*, project_id: str, name: str, description: str, default_tier: str) -> str:
    return "# Messer project manifest\n" + _yaml(
        {
            "id": project_id,
            "name": name,
            "description": description,
            "default_model_tier": default_tier,
            "environments": ["development", "production"],
            "allowed_models": [],
            "channels": [],
        }
    )


def initial_project_files(*, project_id: str, name: str, description: str, default_tier: str) -> dict[str, str]:
    return {
        "messer.project.yaml": project_manifest(
            project_id=project_id, name=name, description=description, default_tier=default_tier
        ),
        "knowledge.yaml": "# Knowledge bases linked to this project\n" + _yaml({"knowledge_bases": []}),
        "triggers.yaml": "# Workflow triggers\n" + _yaml({"triggers": []}),
        "workforce/__init__.py": "",
        "interfaces/.gitkeep": "",
        "pyproject.toml": (
            "[project]\n"
            f'name = "{project_id}"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.12"\n'
            'dependencies = ["messer-core[server,evals]"]\n'
        ),
        ".gitignore": "__pycache__/\n.venv/\n.env\n*.pyc\n",
        "README.md": (
            f"# {name}\n\n{description}\n\n"
            "Proyecto de Messer. Todo es código: `workforce/` contiene los agentes y flujos, `interfaces/` las "
            "pantallas y `knowledge.yaml` / `triggers.yaml` sus enlaces y disparadores.\n\n"
            "Ejecutar en local: `messer start` (o `docker compose up` en la exportación).\n"
        ),
    }


def member_manifest(*, member_id: str, kind: str, source_mode: str, config: dict[str, Any] | None) -> str:
    entry = "agent.py::agent" if kind == "agent" else "workflow.py::workflow"
    data: dict[str, Any] = {"_id": member_id, "_type": kind, "fqn": entry, "studio": {"source_mode": source_mode}}
    if config is not None:
        data["studio"]["config"] = config
    return "# Messer workforce member. The Studio reads and writes this file.\n" + _yaml(data)


def agent_member_files(*, member_id: str, config: AgentConfig, source_mode: str = "config") -> dict[str, str]:
    base = f"workforce/{config.name}"
    return {
        f"{base}/__init__.py": "",
        f"{base}/agent.py": render_agent_code(config),
        f"{base}/messer.yaml": member_manifest(
            member_id=member_id, kind="agent", source_mode=source_mode, config=config.model_dump(mode="json")
        ),
        f"{base}/evals/basic.yaml": _yaml(
            [
                {
                    "name": f"{config.name}_responde",
                    "description": "El agente responde a un saludo sin errores",
                    "runnable": "../agent.py::agent",
                    "tags": ["smoke"],
                    "params": {"prompt": "Hola"},
                    "output": {"min_length!": 1},
                }
            ]
        ),
    }
