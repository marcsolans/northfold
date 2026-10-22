# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Configuration of the standalone platform, read from the environment of the ``platform`` container."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(slots=True)
class StandaloneConfig:
    data_dir: Path
    """Exported, read-only data: ``knowledge/<kb_id>/{kb.json,chunks.jsonl,tables/*}``."""
    state_dir: Path
    """Writable state: traces, uploaded files, email outbox, SQLite copies of the tables."""
    token: str = ""
    """Bearer token every caller must present (members get it as ``MESSER_API_KEY``). Empty disables auth."""
    org_id: str | None = None
    project_id: str | None = None
    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    public_url: str = "http://localhost:8000"
    manifest_path: Path | None = None
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = True
    email_from: str = "Messer <no-reply@localhost>"
    sql_row_limit: int = 1000
    sql_timeout_ms: int = 5000

    @property
    def model_mode(self) -> str:
        return "anthropic" if self.anthropic_api_key else "offline"

    @classmethod
    def from_env(cls) -> StandaloneConfig:
        env = os.environ
        data_dir = Path(env.get("MESSER_STANDALONE_DATA_DIR", "data")).resolve()
        manifest = env.get("MESSER_STANDALONE_MANIFEST")
        return cls(
            data_dir=data_dir,
            state_dir=Path(env.get("MESSER_STANDALONE_STATE_DIR", "state")).resolve(),
            token=env.get("MESSER_STANDALONE_TOKEN", ""),
            org_id=env.get("MESSER_ORG_ID") or None,
            project_id=env.get("MESSER_PROJECT_ID") or None,
            anthropic_api_key=env.get("ANTHROPIC_API_KEY", "").strip(),
            anthropic_base_url=env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/"),
            public_url=env.get("MESSER_STANDALONE_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
            manifest_path=Path(manifest).resolve() if manifest else data_dir.parent / "messer-export.json",
            smtp_host=env.get("SMTP_HOST", ""),
            smtp_port=int(env.get("SMTP_PORT", "587") or 587),
            smtp_user=env.get("SMTP_USER", ""),
            smtp_password=env.get("SMTP_PASSWORD", ""),
            smtp_tls=_bool(env.get("SMTP_TLS", "true")),
            email_from=env.get("EMAIL_FROM", "Messer <no-reply@localhost>"),
            sql_row_limit=int(env.get("MESSER_STANDALONE_SQL_ROW_LIMIT", "1000") or 1000),
            sql_timeout_ms=int(env.get("MESSER_STANDALONE_SQL_TIMEOUT_MS", "5000") or 5000),
        )
