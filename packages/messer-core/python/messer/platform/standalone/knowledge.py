# Added by Messer: standalone platform for exported projects (see NOTICE).
"""Knowledge bases of an exported project.

Layout written by the Messer export (``data/knowledge/``)::

    index.json                         {"knowledge_bases": [{"id", "name", "description"}]}
    <kb_id>/kb.json                    {"id", "name", "description", "files": [...], "tables": [...]}
    <kb_id>/chunks.jsonl               {"id", "file_id", "filename", "ordinal", "content", "heading",
                                        "page_from", "page_to", "metadata"} per line
    <kb_id>/tables/<name>.csv          rows (header = column names, empty cell = NULL)
    <kb_id>/tables/<name>.schema.json  {"name", "description", "columns": [{"name", "type", ...}], "primary_key"}

Search is keyword (BM25) over the chunks: there is no vector index offline, so ``vector`` and ``hybrid`` requests
are served by the same ranking. SQL runs on a read-only SQLite copy of the tables (rebuilt when the export
changes): one ``SELECT``/``WITH`` statement, enforced by the SQL check, a read-only connection and an authorizer.
"""

from __future__ import annotations

import csv
import json
import math
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_WORD = re.compile(r"\w+", re.UNICODE)
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
SQLITE_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "numeric": "REAL",
    "boolean": "INTEGER",
    "date": "TEXT",
    "timestamp": "TEXT",
    "json": "TEXT",
}
_TRUE = {"true", "t", "1", "yes", "y", "si", "sí"}
_FALSE = {"false", "f", "0", "no", "n"}


class KnowledgeError(Exception):
    def __init__(self, message: str, *, code: str = "invalid_request", status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def tokenize(text: str) -> list[str]:
    """Lower-case, accent-free words with a light stem (plural ``s`` dropped, truncated to 6 characters) so
    «facturas» matches «factura» and «condiciones» matches «condición»."""
    out: list[str] = []
    for word in _WORD.findall(_normalize(text)):
        if len(word) < 2:
            continue
        if len(word) > 3 and word.endswith("s") and not word.isdigit():
            word = word[:-1]
        out.append(word[:6] if not word.isdigit() else word)
    return out


@dataclass(slots=True)
class Bm25Index:
    docs: list[dict[str, Any]]
    k1: float = 1.2
    b: float = 0.75
    lengths: list[int] = field(default_factory=list)
    postings: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    avgdl: float = 0.0

    def __post_init__(self) -> None:
        for i, doc in enumerate(self.docs):
            text = " ".join(str(doc.get(k) or "") for k in ("heading", "content", "filename"))
            terms = Counter(tokenize(text))
            self.lengths.append(sum(terms.values()))
            for term, tf in terms.items():
                self.postings.setdefault(term, []).append((i, tf))
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0

    def search(self, query: str, k: int) -> list[tuple[float, dict[str, Any]]]:
        n = len(self.docs)
        if not n:
            return []
        scores: dict[int, float] = {}
        for term in set(tokenize(query)):
            plist = self.postings.get(term)
            if not plist:
                continue
            idf = math.log(1 + (n - len(plist) + 0.5) / (len(plist) + 0.5))
            for doc, tf in plist:
                norm = (
                    tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lengths[doc] / (self.avgdl or 1)))
                )
                scores[doc] = scores.get(doc, 0.0) + idf * norm
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
        return [(round(score, 6), self.docs[doc]) for doc, score in ranked]


def _strip_sql_comments(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if sql[j] == c:
                    if j + 1 < n and sql[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j == -1 else j
        elif sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            i = n if j == -1 else j + 2
            out.append(" ")
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _rewrite_outside_strings(sql: str) -> str:
    """``$1`` → ``?1`` (PostgreSQL-style parameters) and ``ILIKE`` → ``LIKE`` (SQLite's LIKE ignores case)."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        if c in ("'", '"'):
            j = i + 1
            while j < n and not (sql[j] == c and not (j + 1 < n and sql[j + 1] == c)):
                j += 2 if sql[j] == c else 1
            out.append(sql[i : j + 1])
            i = j + 1
            continue
        m = re.match(r"\$(\d+)", sql[i:])
        if m:
            out.append(f"?{m.group(1)}")
            i += len(m.group(0))
            continue
        m = re.match(r"(?i)\bilike\b", sql[i:])
        if m and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            out.append("LIKE")
            i += len(m.group(0))
            continue
        out.append(c)
        i += 1
    return "".join(out)


def check_select(sql: str) -> str:
    """Return the statement to run; refuse anything that is not exactly one read-only query."""
    body = _strip_sql_comments(sql).strip().rstrip(";").strip()
    if not body:
        raise KnowledgeError("La consulta está vacía", code="empty_sql")
    if ";" in _strip_strings(body):
        raise KnowledgeError("Solo se admite una sentencia por consulta", code="multiple_statements")
    first = body.split(None, 1)[0].lower()
    if first not in ("select", "with"):
        raise KnowledgeError("Solo se permiten consultas SELECT (solo lectura)", code="read_only")
    return _rewrite_outside_strings(body)


def _strip_strings(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", "''", sql)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _coerce(value: str, logical: str) -> Any:
    if value == "":
        return None
    if logical == "integer":
        try:
            return int(value)
        except ValueError:
            try:
                return int(float(value))
            except ValueError:
                return None
    if logical == "numeric":
        try:
            return float(value)
        except ValueError:
            return None
    if logical == "boolean":
        lowered = value.strip().lower()
        return 1 if lowered in _TRUE else 0 if lowered in _FALSE else None
    return value


_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _authorizer(action: int, arg1: str | None, *_: Any) -> int:
    if action in _ALLOWED_ACTIONS:
        if action == sqlite3.SQLITE_FUNCTION and (arg1 or "").lower() in ("load_extension", "readfile", "writefile"):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _logical_of(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "numeric"
    return "text"


class KnowledgeStore:
    def __init__(self, data_dir: Path, state_dir: Path, *, row_limit: int = 1000, timeout_ms: int = 5000) -> None:
        self.root = data_dir / "knowledge"
        self.sqlite_dir = state_dir / "sqlite"
        self.row_limit = row_limit
        self.timeout_ms = timeout_ms
        self._indexes: dict[str, Bm25Index] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ catalog
    def list(self) -> list[dict[str, Any]]:
        index = self.root / "index.json"
        if not index.is_file():
            return []
        data = json.loads(index.read_text(encoding="utf-8"))
        return list(data.get("knowledge_bases") or [])

    def _kb_dir(self, kb_id: str) -> Path:
        if not _SAFE_ID.match(kb_id) or not (self.root / kb_id / "kb.json").is_file():
            raise KnowledgeError("Base de conocimiento no encontrada en la exportación", code="not_found", status=404)
        return self.root / kb_id

    def meta(self, kb_id: str) -> dict[str, Any]:
        return json.loads((self._kb_dir(kb_id) / "kb.json").read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ search
    def _index(self, kb_id: str) -> Bm25Index:
        with self._lock:
            cached = self._indexes.get(kb_id)
            if cached is not None:
                return cached
            docs: list[dict[str, Any]] = []
            path = self._kb_dir(kb_id) / "chunks.jsonl"
            if path.is_file():
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            docs.append(json.loads(line))
            index = Bm25Index(docs)
            self._indexes[kb_id] = index
            return index

    def search(self, kb_id: str, query: str, k: int = 8) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for score, doc in self._index(kb_id).search(query, max(1, min(int(k), 50))):
            hits.append(
                {
                    "chunk_id": str(doc.get("id") or ""),
                    "file_id": str(doc.get("file_id") or ""),
                    "filename": doc.get("filename") or "",
                    "content": doc.get("content") or "",
                    "heading": doc.get("heading"),
                    "page_from": doc.get("page_from"),
                    "page_to": doc.get("page_to"),
                    "score": score,
                    "metadata": doc.get("metadata") or {},
                }
            )
        return hits

    # ------------------------------------------------------------------ SQL
    def _database(self, kb_id: str) -> Path:
        kb_dir = self._kb_dir(kb_id)
        tables_dir = kb_dir / "tables"
        sources = sorted(tables_dir.glob("*.schema.json")) if tables_dir.is_dir() else []
        target = self.sqlite_dir / f"{kb_id}.sqlite"
        newest = max(
            [p.stat().st_mtime for p in sources]
            + [
                p.with_suffix("").with_suffix(".csv").stat().st_mtime
                for p in sources
                if p.with_suffix("").with_suffix(".csv").is_file()
            ]
            + [0.0]
        )
        with self._lock:
            if target.is_file() and target.stat().st_mtime >= newest:
                return target
            self.sqlite_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.unlink(missing_ok=True)
            conn = sqlite3.connect(tmp)
            try:
                for schema_path in sources:
                    schema = json.loads(schema_path.read_text(encoding="utf-8"))
                    name = str(schema["name"])
                    columns = [c for c in schema.get("columns", []) if c.get("name")]
                    if not columns:
                        continue
                    types = {str(c["name"]): str(c.get("type") or "text") for c in columns}
                    ddl = ", ".join(f"{_quote(c)} {SQLITE_TYPES.get(t, 'TEXT')}" for c, t in types.items())
                    conn.execute(f"CREATE TABLE {_quote(name)} ({ddl})")
                    csv_path = schema_path.with_suffix("").with_suffix(".csv")
                    if not csv_path.is_file():
                        continue
                    with csv_path.open(encoding="utf-8", newline="") as fh:
                        reader = csv.reader(fh)
                        header = next(reader, None) or []
                        cols = [h for h in header if h in types]
                        idx = [header.index(c) for c in cols]
                        placeholders = ", ".join("?" for _ in cols)
                        insert = (
                            f"INSERT INTO {_quote(name)} ({', '.join(_quote(c) for c in cols)}) VALUES ({placeholders})"
                        )
                        batch: list[list[Any]] = []
                        for row in reader:
                            batch.append(
                                [
                                    _coerce(row[i] if i < len(row) else "", types[c])
                                    for c, i in zip(cols, idx, strict=True)
                                ]
                            )
                            if len(batch) >= 1000:
                                conn.executemany(insert, batch)
                                batch.clear()
                        if batch:
                            conn.executemany(insert, batch)
                conn.commit()
            finally:
                conn.close()
            tmp.replace(target)
            return target

    def tables(self, kb_id: str) -> list[dict[str, Any]]:
        return list(self.meta(kb_id).get("tables") or [])

    def query(self, kb_id: str, sql: str, params: list[Any] | None = None) -> dict[str, Any]:
        statement = check_select(sql)
        db = self._database(kb_id)
        started = time.perf_counter()
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, check_same_thread=False)
        try:
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(_authorizer)
            deadline = started + self.timeout_ms / 1000
            conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 10_000)
            try:
                cur = conn.execute(statement, list(params or []))
                rows = cur.fetchmany(self.row_limit + 1)
            except sqlite3.DatabaseError as exc:
                message = str(exc)
                if "interrupted" in message:
                    raise KnowledgeError("La consulta ha superado el tiempo máximo", code="sql_timeout") from exc
                if "not authorized" in message:
                    raise KnowledgeError("Solo se permiten consultas de solo lectura", code="read_only") from exc
                raise KnowledgeError(f"Error de SQL: {message}", code="sql_error") from exc
            columns = [d[0] for d in (cur.description or [])]
        finally:
            conn.close()
        truncated = len(rows) > self.row_limit
        rows = rows[: self.row_limit]
        column_types = ["text"] * len(columns)
        for i in range(len(columns)):
            for row in rows:
                if row[i] is not None:
                    column_types[i] = _logical_of(row[i])
                    break
        return {
            "columns": columns,
            "column_types": column_types,
            "rows": [list(r) for r in rows],
            "row_count": len(rows),
            "truncated": truncated,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            "notices": [
                "SQLite (proyecto exportado): sintaxis SQL estándar; las funciones de PostgreSQL no están disponibles."
            ],
        }
