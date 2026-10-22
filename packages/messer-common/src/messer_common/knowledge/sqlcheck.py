"""Strict static checks for read-only SQL (console and agents).

A small PostgreSQL lexer (comments, all string forms, quoted identifiers, parameters) feeds rules that
reject anything that is not exactly one read-only query, before the statement reaches the database:

* one statement only; it must start with SELECT, WITH, VALUES, TABLE, ``(`` or EXPLAIN of those;
* no ``SELECT … INTO``, no data-modifying CTEs, no row locks (``FOR UPDATE/SHARE``), no ``ONLY``;
* no functions that change settings or roles, read files, large objects, other databases or the
  catalog (``set_config``, ``query_to_xml``, ``pg_read_file``, ``lo_*``, ``dblink``, most ``pg_*``);
* no system catalog relations (``pg_*``) and no other knowledge base schema (``kb_<other>``);
* ``embed('text')`` / ``embed($n)`` calls are located so they can be replaced by a computed vector.

The database enforces the same boundaries again (read-only transaction, per-knowledge-base reader role,
``statement_timeout``); these checks give clear errors and close gaps such as ``set_config('role', …)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .errors import SqlRejected

TokenKind = Literal["word", "qident", "string", "number", "param", "op", "punct"]


@dataclass(slots=True)
class Token:
    kind: TokenKind
    value: str  # lowercased for words; exact text for quoted identifiers; decoded value for strings
    start: int
    end: int


_IDENT_RE = re.compile(r"[A-Za-z_\u0080-￿][A-Za-z0-9_$\u0080-￿]*")
_NUMBER_RE = re.compile(
    r"0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?|\.\d[\d_]*(?:[eE][+-]?\d+)?"
)
_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
_PARAM_RE = re.compile(r"\$(\d+)")
_OP_CHARS = set("+-*/<>=~!@#%^&|`?")


def _read_quoted(sql: str, i: int, quote: str, backslash: bool) -> tuple[str, int]:
    """Read a quoted literal starting at ``sql[i] == quote``; returns (decoded inner text, end index)."""
    j = i + 1
    out: list[str] = []
    n = len(sql)
    while j < n:
        ch = sql[j]
        if backslash and ch == "\\" and j + 1 < n:
            nxt = sql[j + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(nxt, nxt))
            j += 2
            continue
        if ch == quote:
            if j + 1 < n and sql[j + 1] == quote:
                out.append(quote)
                j += 2
                continue
            return "".join(out), j + 1
        out.append(ch)
        j += 1
    raise SqlRejected("Hay una cadena o identificador sin cerrar", code="sql_unterminated")


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if sql.startswith("/*", j):
                    depth += 1
                    j += 2
                elif sql.startswith("*/", j):
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth:
                raise SqlRejected("Hay un comentario sin cerrar", code="sql_unterminated")
            i = j
            continue
        if ch in "uU" and sql.startswith('&"', i + 1):
            raise SqlRejected('Los identificadores U&"…" no están permitidos', code="sql_forbidden")
        if ch in "uU" and sql.startswith("&'", i + 1):
            value, end = _read_quoted(sql, i + 2, "'", backslash=False)
            tokens.append(Token("string", value, i, end))
            i = end
            continue
        if ch in "eEbBxXnN" and i + 1 < n and sql[i + 1] == "'":
            value, end = _read_quoted(sql, i + 1, "'", backslash=ch in "eE")
            tokens.append(Token("string", value, i, end))
            i = end
            continue
        if ch == "'":
            value, end = _read_quoted(sql, i, "'", backslash=False)
            tokens.append(Token("string", value, i, end))
            i = end
            continue
        if ch == '"':
            value, end = _read_quoted(sql, i, '"', backslash=False)
            if not value:
                raise SqlRejected("Identificador vacío", code="sql_syntax")
            tokens.append(Token("qident", value, i, end))
            i = end
            continue
        if ch == "$":
            param = _PARAM_RE.match(sql, i)
            if param:
                tokens.append(Token("param", param.group(1), i, param.end()))
                i = param.end()
                continue
            tag = _DOLLAR_TAG_RE.match(sql, i)
            if tag:
                close = sql.find(tag.group(0), tag.end())
                if close < 0:
                    raise SqlRejected("Hay una cadena $$ sin cerrar", code="sql_unterminated")
                end = close + len(tag.group(0))
                tokens.append(Token("string", sql[tag.end() : close], i, end))
                i = end
                continue
            raise SqlRejected("Carácter $ inesperado", code="sql_syntax")
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            match = _NUMBER_RE.match(sql, i)
            assert match is not None
            tokens.append(Token("number", match.group(0), i, match.end()))
            i = match.end()
            continue
        ident = _IDENT_RE.match(sql, i)
        if ident:
            tokens.append(Token("word", ident.group(0).lower(), i, ident.end()))
            i = ident.end()
            continue
        if sql.startswith("::", i):
            tokens.append(Token("op", "::", i, i + 2))
            i += 2
            continue
        if ch in "(),;[].:":
            tokens.append(Token("punct", ch, i, i + 1))
            i += 1
            continue
        if ch in _OP_CHARS:
            j = i
            while j < n and sql[j] in _OP_CHARS and not sql.startswith("--", j) and not sql.startswith("/*", j):
                j += 1
            tokens.append(Token("op", sql[i:j], i, j))
            i = j
            continue
        raise SqlRejected(f"Carácter no válido en la consulta: {ch!r}", code="sql_syntax")
    return tokens


# ---------------------------------------------------------------------------------------------- rules

STATEMENT_STARTS = {"select", "with", "values", "table"}
EXPLAIN_FLAGS = {"analyze", "analyse", "verbose"}
DML_WORDS = {"insert", "update", "delete", "merge"}
ROW_LOCK_NEXT = {"update", "share", "no", "key"}

DENIED_FUNCTIONS = {
    "set_config",
    "loread",
    "lowrite",
    "nextval",
    "setval",
    "currval",
    "lastval",
    "txid_current",
    "txid_current_if_assigned",
    "dblink",
    "query_to_xml",
    "query_to_xmlschema",
    "query_to_xml_and_xmlschema",
    "cursor_to_xml",
    "cursor_to_xmlschema",
    "table_to_xml",
    "table_to_xmlschema",
    "table_to_xml_and_xmlschema",
    "schema_to_xml",
    "schema_to_xmlschema",
    "schema_to_xml_and_xmlschema",
    "database_to_xml",
    "database_to_xmlschema",
    "database_to_xml_and_xmlschema",
}
DENIED_PREFIXES = ("pg_", "lo_", "dblink_")
ALLOWED_PG_FUNCTIONS = {
    "pg_typeof",
    "pg_column_size",
    "pg_size_pretty",
    "pg_size_bytes",
    "pg_input_is_valid",
    "pg_input_error_info",
}
SEARCH_FUNCTIONS = {"kb_vector_search", "kb_text_search", "kb_hybrid_search"}


@dataclass(slots=True)
class EmbedCall:
    start: int  # character offsets of the whole ``embed(...)`` call
    end: int
    text: str | None  # literal text
    param: int | None  # or 1-based parameter number


@dataclass(slots=True)
class SqlAnalysis:
    sql: str  # without trailing semicolons
    tokens: list[Token]
    is_explain: bool
    statement_offset: int  # character offset where the inner statement starts (after EXPLAIN options)
    statement_starts_with_with: bool
    with_insert_offset: int | None  # offset right after "WITH" / "WITH RECURSIVE" when present
    max_param: int
    params_used: set[int] = field(default_factory=set)
    embed_calls: list[EmbedCall] = field(default_factory=list)
    names: set[str] = field(default_factory=set)  # unqualified identifiers (candidate relation names)
    qualified: list[tuple[str, str]] = field(default_factory=list)  # (schema, name) references
    functions: set[str] = field(default_factory=set)


def _is_name(token: Token) -> bool:
    return token.kind in ("word", "qident")


def _function_denied(name: str) -> bool:
    if name in DENIED_FUNCTIONS:
        return True
    if name in ALLOWED_PG_FUNCTIONS:
        return False
    return name.startswith(DENIED_PREFIXES)


def analyze(sql: str, *, own_schema: str) -> SqlAnalysis:
    """Validate a read-only statement and collect what the executor needs to rewrite it."""
    tokens = tokenize(sql)
    while tokens and tokens[-1].kind == "punct" and tokens[-1].value == ";":
        tokens.pop()
    if not tokens:
        raise SqlRejected("Escribe una consulta SELECT", code="sql_empty")
    if any(t.kind == "punct" and t.value == ";" for t in tokens):
        raise SqlRejected("Solo se permite una sentencia por consulta", code="sql_multiple_statements")
    text = sql[: tokens[-1].end]

    idx = 0
    is_explain = False
    first = tokens[0]
    if first.kind == "word" and first.value == "explain":
        is_explain = True
        idx = 1
        while idx < len(tokens) and tokens[idx].kind == "word" and tokens[idx].value in EXPLAIN_FLAGS:
            idx += 1
        if idx < len(tokens) and tokens[idx].kind == "punct" and tokens[idx].value == "(":
            depth = 0
            while idx < len(tokens):
                tok = tokens[idx]
                if tok.kind == "punct" and tok.value == "(":
                    depth += 1
                elif tok.kind == "punct" and tok.value == ")":
                    depth -= 1
                    if depth == 0:
                        idx += 1
                        break
                elif tok.kind not in ("word", "number", "string") and not (tok.kind == "punct" and tok.value == ","):
                    raise SqlRejected("Opciones de EXPLAIN no válidas", code="sql_syntax")
                idx += 1
        if idx >= len(tokens):
            raise SqlRejected("EXPLAIN necesita una consulta SELECT", code="sql_syntax")
    head = tokens[idx]
    if not ((head.kind == "word" and head.value in STATEMENT_STARTS) or (head.kind == "punct" and head.value == "(")):
        raise SqlRejected(
            "Solo se permiten consultas de lectura (SELECT, WITH, VALUES, TABLE o EXPLAIN)",
            code="sql_not_read_only",
        )
    with_insert_offset: int | None = None
    starts_with_with = head.kind == "word" and head.value == "with"
    if starts_with_with:
        nxt = tokens[idx + 1] if idx + 1 < len(tokens) else None
        if nxt is not None and nxt.kind == "word" and nxt.value == "recursive":
            with_insert_offset = nxt.end
        else:
            with_insert_offset = head.end

    analysis = SqlAnalysis(
        sql=text,
        tokens=tokens,
        is_explain=is_explain,
        statement_offset=head.start,
        statement_starts_with_with=starts_with_with,
        with_insert_offset=with_insert_offset,
        max_param=0,
    )

    count = len(tokens)
    for i, tok in enumerate(tokens):
        prev = tokens[i - 1] if i > 0 else None
        nxt = tokens[i + 1] if i + 1 < count else None
        if tok.kind == "param":
            number = int(tok.value)
            if number < 1 or number > 100:
                raise SqlRejected("Los parámetros van de $1 a $100", code="sql_params")
            analysis.params_used.add(number)
            analysis.max_param = max(analysis.max_param, number)
            continue
        if tok.kind == "word":
            if tok.value == "into":
                raise SqlRejected("SELECT … INTO no está permitido", code="sql_not_read_only")
            if tok.value == "only" and not (prev is not None and prev.kind == "word" and prev.value in ("row", "rows")):
                raise SqlRejected("ONLY no está permitido en la consola", code="sql_forbidden")
            if tok.value == "for" and nxt is not None and nxt.kind == "word" and nxt.value in ROW_LOCK_NEXT:
                raise SqlRejected(
                    "Los bloqueos de filas (FOR UPDATE/SHARE) no están permitidos", code="sql_not_read_only"
                )
            if tok.value in DML_WORDS and prev is not None and prev.kind == "punct" and prev.value == "(":
                raise SqlRejected("Las CTE que modifican datos no están permitidas", code="sql_not_read_only")
        if not _is_name(tok):
            continue
        is_call = nxt is not None and nxt.kind == "punct" and nxt.value == "("
        qualified_after = nxt is not None and nxt.kind == "punct" and nxt.value == "."
        qualified_before = prev is not None and prev.kind == "punct" and prev.value == "."
        name = tok.value

        if is_call:
            # Calls written as schema.function(...) are checked on the function name.
            if _function_denied(name):
                raise SqlRejected(f"La función {name}() no está permitida", code="sql_forbidden_function")
            analysis.functions.add(name)
            if name == "embed" and not qualified_before:
                analysis.embed_calls.append(_embed_call(tokens, i))
            continue
        if qualified_after:
            schema = name
            target = tokens[i + 2] if i + 2 < count else None
            if schema == "pg_catalog":
                after = tokens[i + 3] if i + 3 < count else None
                if not (target is not None and _is_name(target) and after is not None and after.value == "("):
                    raise SqlRejected("No se permite consultar el catálogo del sistema", code="sql_forbidden")
                continue
            if schema.startswith("pg_"):
                raise SqlRejected("No se permite consultar el catálogo del sistema", code="sql_forbidden")
            if schema.startswith("kb_") and schema != own_schema:
                raise SqlRejected("Solo puedes consultar las tablas de esta base de conocimiento", code="sql_scope")
            if target is not None and _is_name(target):
                analysis.qualified.append((schema, target.value))
            continue
        if qualified_before:
            continue
        if name.startswith("pg_"):
            raise SqlRejected("No se permite consultar el catálogo del sistema", code="sql_forbidden")
        analysis.names.add(name)
    return analysis


def _embed_call(tokens: list[Token], i: int) -> EmbedCall:
    try:
        open_, arg, close = tokens[i + 1], tokens[i + 2], tokens[i + 3]
    except IndexError as exc:
        raise SqlRejected("embed() necesita un texto: embed('…')", code="sql_embed") from exc
    if not (open_.value == "(" and close.kind == "punct" and close.value == ")"):
        raise SqlRejected("embed() solo acepta un texto literal o un parámetro", code="sql_embed")
    if arg.kind == "string":
        if not arg.value.strip():
            raise SqlRejected("embed() necesita un texto no vacío", code="sql_embed")
        return EmbedCall(tokens[i].start, close.end, arg.value, None)
    if arg.kind == "param":
        return EmbedCall(tokens[i].start, close.end, None, int(arg.value))
    raise SqlRejected("embed() solo acepta un texto literal o un parámetro", code="sql_embed")


def replace_spans(sql: str, replacements: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping (start, end, text) replacements."""
    out: list[str] = []
    cursor = 0
    for start, end, text in sorted(replacements):
        if start < cursor:
            raise ValueError("overlapping replacements")
        out.append(sql[cursor:start])
        out.append(text)
        cursor = end
    out.append(sql[cursor:])
    return "".join(out)


def params_in(sql: str) -> set[int]:
    """Parameter numbers referenced by a (rewritten) statement."""
    return {int(t.value) for t in tokenize(sql) if t.kind == "param"}


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_expression(expr: str) -> None:
    """Checks for a policy row filter: one boolean expression, read-only, no system access."""
    tokens = tokenize(expr)
    if not tokens:
        raise SqlRejected("El filtro de filas está vacío", code="policy_filter")
    depth = 0
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.kind == "punct" and tok.value == ";":
            raise SqlRejected("El filtro no puede contener ';'", code="policy_filter")
        if tok.kind == "punct" and tok.value == "(":
            depth += 1
        elif tok.kind == "punct" and tok.value == ")":
            depth -= 1
            if depth < 0:
                raise SqlRejected("Paréntesis desequilibrados en el filtro", code="policy_filter")
        if tok.kind == "param":
            raise SqlRejected("El filtro no puede usar parámetros $n", code="policy_filter")
        if tok.kind == "word" and tok.value in {
            "select",
            "into",
            "union",
            "with",
            "insert",
            "update",
            "delete",
            "merge",
        }:
            raise SqlRejected(
                "El filtro debe ser una condición sobre las columnas, sin subconsultas", code="policy_filter"
            )
        if _is_name(tok):
            is_call = nxt is not None and nxt.kind == "punct" and nxt.value == "("
            if is_call and (_function_denied(tok.value) or tok.value == "embed"):
                raise SqlRejected(f"La función {tok.value}() no está permitida en filtros", code="policy_filter")
            if not is_call and tok.value.startswith(("pg_", "kb_")):
                raise SqlRejected("El filtro no puede referenciar otros objetos", code="policy_filter")
            if nxt is not None and nxt.kind == "punct" and nxt.value == ".":
                raise SqlRejected("Usa nombres de columna sin calificar en el filtro", code="policy_filter")
    if depth != 0:
        raise SqlRejected("Paréntesis desequilibrados en el filtro", code="policy_filter")
