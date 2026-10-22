"""Agent configuration (local data sources and allowed paths) and enrollment state.

Configuration file (YAML), looked up in ``--config``, ``$MESSER_AGENT_CONFIG``, ``/etc/messer-agent/agent.yaml``
and ``~/.config/messer-agent/agent.yaml``::

    sources:
      erp:                       # name used in Messer when creating the connection
        type: postgresql         # postgresql | mysql | sqlserver
        dsn_env: ERP_DSN         # or: dsn: postgresql://reader:…@10.0.0.5:5432/erp
    paths:                       # folders whose files may be listed and copied into knowledge bases
      - /srv/documentos
    max_file_mb: 25
    max_concurrency: 8

Connection strings stay on this machine: only source names and types are reported to Messer.
"""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SOURCE_TYPES = ("postgresql", "mysql", "sqlserver")


class ConfigError(ValueError):
    pass


@dataclass(slots=True)
class Source:
    name: str
    type: str
    dsn: str = field(repr=False)


@dataclass(slots=True)
class AgentConfig:
    sources: dict[str, Source] = field(default_factory=dict)
    paths: list[Path] = field(default_factory=list)
    max_file_mb: int = 25
    max_concurrency: int = 8
    path: Path | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "sources": [{"name": s.name, "type": s.type} for s in self.sources.values()],
            "paths": [str(p) for p in self.paths],
        }


def default_config_paths() -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("MESSER_AGENT_CONFIG"):
        paths.append(Path(os.environ["MESSER_AGENT_CONFIG"]))
    paths.append(Path("/etc/messer-agent/agent.yaml"))
    paths.append(Path.home() / ".config" / "messer-agent" / "agent.yaml")
    return paths


def parse_config(data: dict[str, Any], *, origin: Path | None = None) -> AgentConfig:
    if not isinstance(data, dict):
        raise ConfigError("El archivo de configuración debe ser un objeto YAML")
    sources: dict[str, Source] = {}
    for name, raw in (data.get("sources") or {}).items():
        if not isinstance(raw, dict):
            raise ConfigError(f"Origen «{name}»: formato no válido")
        kind = str(raw.get("type") or "").lower()
        if kind not in SOURCE_TYPES:
            raise ConfigError(f"Origen «{name}»: tipo «{kind}» no admitido ({', '.join(SOURCE_TYPES)})")
        dsn = raw.get("dsn")
        if not dsn and raw.get("dsn_env"):
            dsn = os.environ.get(str(raw["dsn_env"]))
            if not dsn:
                raise ConfigError(f"Origen «{name}»: la variable {raw['dsn_env']} no está definida")
        if not dsn:
            raise ConfigError(f"Origen «{name}»: falta «dsn» o «dsn_env»")
        sources[str(name)] = Source(name=str(name), type=kind, dsn=str(dsn))
    paths = []
    for raw_path in data.get("paths") or []:
        resolved = Path(str(raw_path)).expanduser().resolve()
        paths.append(resolved)
    max_file_mb = int(data.get("max_file_mb") or 25)
    max_concurrency = int(data.get("max_concurrency") or 8)
    if max_file_mb < 1 or max_concurrency < 1:
        raise ConfigError("max_file_mb y max_concurrency deben ser positivos")
    return AgentConfig(
        sources=sources, paths=paths, max_file_mb=max_file_mb, max_concurrency=max_concurrency, path=origin
    )


def load_config(path: str | Path | None = None) -> AgentConfig:
    candidates = [Path(path)] if path else default_config_paths()
    for candidate in candidates:
        if candidate.exists():
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            return parse_config(data, origin=candidate)
    if path:
        raise ConfigError(f"No existe el archivo de configuración {path}")
    return AgentConfig()


# ----------------------------------------------------------------------------- enrollment state


@dataclass(slots=True)
class AgentState:
    api: str
    agent_id: str
    agent_secret: str = field(repr=False)
    org_id: str = ""
    connect_path: str = "/api/v1/connector-agents/connect"

    @property
    def ws_url(self) -> str:
        base = self.api.rstrip("/")
        if base.startswith("https://"):
            base = "wss://" + base[len("https://") :]
        elif base.startswith("http://"):
            base = "ws://" + base[len("http://") :]
        return base + self.connect_path


def state_dir() -> Path:
    if os.environ.get("MESSER_AGENT_STATE_DIR"):
        return Path(os.environ["MESSER_AGENT_STATE_DIR"])
    if os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        return Path("/etc/messer-agent")
    return Path.home() / ".config" / "messer-agent"


def state_path() -> Path:
    return state_dir() / "credentials.json"


def save_state(state: AgentState, path: Path | None = None) -> Path:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    payload = {
        "api": state.api,
        "agent_id": state.agent_id,
        "agent_secret": state.agent_secret,
        "org_id": state.org_id,
        "connect_path": state.connect_path,
    }
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, target)
    return target


def load_state(path: Path | None = None) -> AgentState | None:
    target = path or state_path()
    if not target.exists():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    return AgentState(
        api=str(data["api"]),
        agent_id=str(data["agent_id"]),
        agent_secret=str(data["agent_secret"]),
        org_id=str(data.get("org_id") or ""),
        connect_path=str(data.get("connect_path") or "/api/v1/connector-agents/connect"),
    )
