# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Local persistence of the standalone platform: run traces (JSONL), uploaded files and outgoing email."""

from __future__ import annotations

import json
import mimetypes
import re
import smtplib
import ssl
import threading
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any

from .config import StandaloneConfig

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
FILE_MAX_BYTES = 50 * 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TraceStore:
    """Every stored trace is appended to ``traces/traces.jsonl``; the latest trace of each run is also kept in
    ``traces/runs/<run_id>.json`` so conversations continue (``parent_id`` memory)."""

    def __init__(self, state_dir: Path) -> None:
        self.dir = state_dir / "traces"
        self.runs = self.dir / "runs"
        self.log = self.dir / "traces.jsonl"
        self._lock = threading.Lock()

    @staticmethod
    def valid_run_id(run_id: str) -> bool:
        return bool(_SAFE_RUN_ID.match(run_id))

    def get(self, run_id: str) -> Any:
        path = self.runs / f"{run_id}.json"
        if not self.valid_run_id(run_id) or not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("trace")

    def put(self, run_id: str, *, project_id: str, parent_id: str | None, trace: Any) -> None:
        record = {
            "run_id": run_id,
            "project_id": project_id,
            "parent_id": parent_id,
            "stored_at": _now(),
            "trace": trace,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock:
            self.runs.mkdir(parents=True, exist_ok=True)
            tmp = self.runs / f".{run_id}.{uuid.uuid4().hex}.tmp"
            tmp.write_text(line, encoding="utf-8")
            tmp.replace(self.runs / f"{run_id}.json")
            with self.log.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.runs.is_dir():
            return []
        paths = sorted(self.runs.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        out: list[dict[str, Any]] = []
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            trace = data.get("trace")
            spans = (
                trace if isinstance(trace, list) else list((trace or {}).values()) if isinstance(trace, dict) else []
            )
            out.append(
                {
                    "run_id": data.get("run_id"),
                    "parent_id": data.get("parent_id"),
                    "stored_at": data.get("stored_at"),
                    "spans": len(spans),
                }
            )
        return out


class FileStore:
    def __init__(self, state_dir: Path, public_url: str) -> None:
        self.dir = state_dir / "files"
        self.public_url = public_url.rstrip("/")

    def put(self, filename: str, data: bytes, content_type: str | None) -> dict[str, Any]:
        name = _SAFE_NAME.sub("_", (filename or "file").rsplit("/", 1)[-1])[:120].strip("._") or "file"
        mime = content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        key = f"{uuid.uuid4().hex}/{name}"
        target = self.dir / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {
            "id": key,
            "name": name,
            "content_type": mime,
            "content_length": len(data),
            "created_at": _now(),
            "expires_at": None,
            "url": f"{self.public_url}/files/{key}",
        }

    def path(self, key: str) -> Path | None:
        parts = key.split("/")
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[0]) or parts[1] in ("", ".", ".."):
            return None
        target = (self.dir / parts[0] / parts[1]).resolve()
        if self.dir.resolve() not in target.parents or not target.is_file():
            return None
        return target


class Mailer:
    """SMTP when ``SMTP_HOST`` is set, otherwise the message is written to ``outbox.jsonl`` (and logged)."""

    def __init__(self, config: StandaloneConfig) -> None:
        self.config = config
        self.outbox = config.state_dir / "outbox.jsonl"
        self._lock = threading.Lock()

    def send(self, *, to: str, subject: str, body: str) -> dict[str, Any]:
        message_id = make_msgid(domain="messer.local")
        if self.config.smtp_host:
            msg = EmailMessage()
            msg["From"] = self.config.email_from
            msg["To"] = to
            msg["Subject"] = subject
            msg["Message-ID"] = message_id
            msg.set_content(body)
            with smtplib.SMTP(self.config.smtp_host, self.config.smtp_port, timeout=20) as smtp:
                if self.config.smtp_tls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.config.smtp_user:
                    smtp.login(self.config.smtp_user, self.config.smtp_password)
                smtp.send_message(msg)
            return {"sent": True, "to": to, "delivery": "smtp", "message_id": message_id}
        record = {"at": _now(), "to": to, "subject": subject, "body": body, "message_id": message_id}
        with self._lock:
            self.outbox.parent.mkdir(parents=True, exist_ok=True)
            with self.outbox.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {
            "sent": False,
            "to": to,
            "delivery": "log",
            "message_id": message_id,
            "note": "SMTP_HOST no está configurado: el email se ha guardado en state/outbox.jsonl",
        }
