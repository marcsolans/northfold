"""Read-only statement guard for customer databases.

Defense in depth on top of read-only transactions: a statement is accepted only if it is a single
query that starts with a read keyword and contains no write/DDL/privilege keyword outside string
literals, quoted identifiers and comments.
"""

from __future__ import annotations

import re

READ_KEYWORDS = {"select", "with", "values", "table", "show", "explain", "describe", "desc"}

# Verbs that change data, schema or privileges. Read-only transactions (and a final rollback on SQL Server)
# already block writes; rejecting them up front gives a clear error and covers data-modifying CTEs.
# Non-reserved words that are common column names (comment, start, replace…) are deliberately absent.
FORBIDDEN_KEYWORDS = {
    "insert",
    "update",
    "delete",
    "merge",
    "truncate",
    "create",
    "alter",
    "drop",
    "grant",
    "revoke",
    "exec",
    "execute",
    "call",
    "into",
}

FORBIDDEN_FUNCTIONS = re.compile(
    r"\b(pg_sleep\w*|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|pg_read_file|"
    r"pg_read_binary_file|pg_ls_\w+|pg_stat_file|pg_advisory\w*|pg_try_advisory\w*|pg_notify|lo_\w+|dblink\w*|"
    r"set_config|nextval|setval|query_to_xml\w*|sleep|benchmark|get_lock|release_lock|load_file|xp_\w+|sp_\w+|"
    r"openrowset|opendatasource|openquery|openxml)\s*\(",
    re.IGNORECASE,
)

# EXPLAIN ANALYZE executes the statement.
_EXPLAIN_ANALYZE = re.compile(r"^\s*explain\s*(\(([^)]*\b)?analy[sz]e\b|analy[sz]e\b)", re.IGNORECASE)


class StatementRejected(ValueError):
    """Raised when a statement is not a single read-only query."""


def strip_literals(sql: str, dialect: str = "postgresql") -> str:
    """Replace string literals, quoted identifiers and comments with spaces (keeps statement structure)."""
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "#" and dialect == "mysql":
            end = sql.find("\n", i)  # MySQL comment
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            if end == -1:
                raise StatementRejected("Comentario sin cerrar")
            i = end + 2
            out.append(" ")
        elif ch in ("'", '"') or (ch == "`" and dialect == "mysql") or (ch == "[" and dialect == "sqlserver"):
            close = "]" if ch == "[" else ch
            # Backslash escapes exist in MySQL strings and PostgreSQL E'' strings only.
            backslash = ch == "'" and (dialect == "mysql" or (i > 0 and sql[i - 1] in "eE"))
            j = i + 1
            while j < n:
                if sql[j] == close:
                    if j + 1 < n and sql[j + 1] == close:
                        j += 2
                        continue
                    break
                if backslash and sql[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                j += 1
            if j >= n:
                raise StatementRejected("Literal sin cerrar")
            out.append(" '' " if ch == "'" else " x ")
            i = j + 1
        elif ch == "$" and dialect == "postgresql" and _dollar_tag(sql, i) is not None:
            tag = _dollar_tag(sql, i) or "$$"
            end = sql.find(tag, i + len(tag))
            if end == -1:
                raise StatementRejected("Literal sin cerrar")
            out.append(" '' ")
            i = end + len(tag)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


_DOLLAR_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _dollar_tag(sql: str, i: int) -> str | None:
    m = _DOLLAR_RE.match(sql, i)
    return m.group(0) if m else None


def check_read_only(sql: str, dialect: str = "postgresql") -> str:
    """Validate ``sql``; returns it without a trailing semicolon. Raises :class:`StatementRejected`."""
    text = sql.strip()
    if not text:
        raise StatementRejected("La consulta está vacía")
    stripped = strip_literals(text, dialect).strip()
    while stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
        text = text.rstrip()
        if text.endswith(";"):
            text = text[:-1].rstrip()
    if ";" in stripped:
        raise StatementRejected("Solo se permite una sentencia por consulta")
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", stripped)
    if not words:
        raise StatementRejected("La consulta no es válida")
    first = words[0].lower()
    if first not in READ_KEYWORDS:
        raise StatementRejected("Solo se permiten consultas de lectura (SELECT, WITH, SHOW, EXPLAIN)")
    lowered = {w.lower() for w in words}
    bad = sorted(lowered & FORBIDDEN_KEYWORDS)
    if bad:
        raise StatementRejected(f"Sentencia no permitida en modo solo lectura: {bad[0].upper()}")
    if FORBIDDEN_FUNCTIONS.search(stripped):
        raise StatementRejected("La consulta usa una función no permitida en modo solo lectura")
    if _EXPLAIN_ANALYZE.match(stripped):
        raise StatementRejected("EXPLAIN ANALYZE ejecuta la consulta y no está permitido")
    return text


_PARAM_RE = re.compile(r"\$(\d+)")


def to_format_params(
    sql: str, params: list[object] | None, dialect: str = "postgresql"
) -> tuple[str, list[object] | None]:
    """Convert ``$1, $2`` placeholders to the ``%s`` paramstyle used by psycopg, PyMySQL and pytds.

    Placeholders inside literals, quoted identifiers and comments are left alone; literal ``%`` signs
    are doubled when parameters are bound.
    """
    if not params:
        if _PARAM_RE.search(strip_literals(sql, dialect)):
            raise StatementRejected("La consulta usa parámetros $n pero no se han proporcionado valores")
        return sql, None
    out: list[str] = []
    ordered: list[object] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n and not (sql[j] == ch and not (j + 1 < n and sql[j + 1] == ch)):
                if sql[j] == ch:
                    j += 2
                    continue
                j += 1
            out.append(sql[i : j + 1].replace("%", "%%"))
            i = j + 1
        elif ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            end = n if end == -1 else end
            out.append(sql[i:end].replace("%", "%%"))
            i = end
        elif ch == "/" and nxt == "*":
            end = sql.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.append(sql[i:end].replace("%", "%%"))
            i = end
        elif ch == "$" and nxt.isdigit():
            m = _PARAM_RE.match(sql, i)
            assert m is not None
            index = int(m.group(1))
            if index < 1 or index > len(params):
                raise StatementRejected(f"Falta el valor del parámetro ${index}")
            ordered.append(params[index - 1])
            out.append("%s")
            i = m.end()
        elif ch == "%":
            out.append("%%")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out), ordered
