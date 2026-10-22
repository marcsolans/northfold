"""Knowledge table column types: names, inference from uploaded data, value coercion, identifiers.

Logical types (contract §3): ``text | integer | numeric | boolean | date | timestamp | json``, stored as
``text | bigint | numeric | boolean | date | timestamptz | jsonb``. Number and date parsing accepts the
Spanish (``1.234,56``, ``31/12/2025``) and English (``1,234.56``, ``2025-12-31``) formats, exactly like
the ``messer.kb_try_*`` SQL helpers used when a column changes type.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

LogicalType = Literal["text", "integer", "numeric", "boolean", "date", "timestamp", "json"]
LOGICAL_TYPES: tuple[LogicalType, ...] = ("text", "integer", "numeric", "boolean", "date", "timestamp", "json")
PG_TYPES: dict[str, str] = {
    "text": "text",
    "integer": "bigint",
    "numeric": "numeric",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "timestamptz",
    "json": "jsonb",
}
PG_TO_LOGICAL: dict[str, LogicalType] = {
    "text": "text",
    "character varying": "text",
    "character": "text",
    "bigint": "integer",
    "integer": "integer",
    "smallint": "integer",
    "numeric": "numeric",
    "double precision": "numeric",
    "real": "numeric",
    "boolean": "boolean",
    "date": "date",
    "timestamp with time zone": "timestamp",
    "timestamp without time zone": "timestamp",
    "jsonb": "json",
    "json": "json",
}
# SQL used to convert an existing column (cast through text) when its type changes.
CONVERSIONS: dict[str, str] = {
    "text": "{col}::text",
    "integer": "messer.kb_try_bigint({col}::text)",
    "numeric": "messer.kb_try_numeric({col}::text)",
    "boolean": "messer.kb_try_bool({col}::text)",
    "date": "messer.kb_try_date({col}::text)",
    "timestamp": "messer.kb_try_timestamptz({col}::text)",
    "json": "messer.kb_try_jsonb({col}::text)",
}

ROW_ID = "_row_id"
RESERVED_TABLES = {"documents", "chunks", "entities"}

# PostgreSQL reserved key words (cannot be used as unquoted column/table names) plus a few that confuse users.
PG_RESERVED = frozenset(
    """
    all analyse analyze and any array as asc asymmetric authorization binary both case cast check collate collation
    column concurrently constraint create cross current_catalog current_date current_role current_schema current_time
    current_timestamp current_user default deferrable desc distinct do else end except false fetch for foreign freeze
    from full grant group having ilike in initially inner intersect into is isnull join lateral leading left like limit
    localtime localtimestamp natural not notnull null offset on only or order outer overlaps placing primary references
    returning right select session_user similar some symmetric system_user table tablesample then to trailing true
    union unique user using variadic verbose when where window with
    """.split()
)


class CoercionError(ValueError):
    pass


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def sanitize_identifier(name: str, *, fallback: str = "column") -> str:
    """snake_case, ASCII, at most 63 bytes, never a reserved word, never starting with a digit."""
    value = _strip_accents(str(name)).lower()
    value = re.sub(r"[^a-z0-9]+", "_", value).strip("_")
    value = re.sub(r"_+", "_", value)
    if not value:
        value = fallback
    if value[0].isdigit():
        value = f"c_{value}"
    value = value[:63].rstrip("_") or fallback
    if value in PG_RESERVED:
        value = f"{value}_"
    return value


def unique_identifiers(names: list[str], *, fallback: str = "column") -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for i, name in enumerate(names, start=1):
        base = sanitize_identifier(name, fallback=f"{fallback}_{i}")
        if base == ROW_ID:
            base = "row_id"
        candidate = base
        n = 2
        while candidate in seen:
            suffix = f"_{n}"
            candidate = base[: 63 - len(suffix)] + suffix
            n += 1
        seen.add(candidate)
        out.append(candidate)
    return out


# ---------------------------------------------------------------------------------------------- parsing

_INT_RE = re.compile(r"^[+-]?\d+$")
_NUM_SPACES = re.compile(r"[\s ]")
_CURRENCY_RE = re.compile(r"^[€$£]|[€$£%]$")
_DOT_THOUSANDS = (re.compile(r"^[+-]?\d{1,3}(\.\d{3}){2,}(,\d+)?$"), re.compile(r"^[+-]?\d{1,3}(\.\d{3})+,\d+$"))
_COMMA_THOUSANDS = (re.compile(r"^[+-]?\d{1,3}(,\d{3}){2,}(\.\d+)?$"), re.compile(r"^[+-]?\d{1,3}(,\d{3})+\.\d+$"))
_COMMA_DECIMAL = re.compile(r"^[+-]?\d+,\d+$")
_PLAIN_NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EU_DATE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")
_ISO_TS = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}(:?\d{2})?)?$")
_EU_TS = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?$")
TRUE_WORDS = {"true", "t", "yes", "y", "si", "sí", "s", "verdadero", "1"}
FALSE_WORDS = {"false", "f", "no", "n", "falso", "0"}
BOOL_INFER_WORDS = {"true", "false", "yes", "no", "si", "sí", "verdadero", "falso"}


def parse_numeric(value: str) -> Decimal | None:
    s = _NUM_SPACES.sub("", value.strip())
    s = _CURRENCY_RE.sub("", s)
    if not s:
        return None
    if any(r.match(s) for r in _DOT_THOUSANDS):
        s = s.replace(".", "").replace(",", ".")
    elif any(r.match(s) for r in _COMMA_THOUSANDS):
        s = s.replace(",", "")
    elif _COMMA_DECIMAL.match(s):
        s = s.replace(",", ".")
    if not _PLAIN_NUMBER.match(s):
        return None
    try:
        number = Decimal(s)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def parse_bool(value: str) -> bool | None:
    s = value.strip().lower()
    if s in TRUE_WORDS:
        return True
    if s in FALSE_WORDS:
        return False
    return None


def parse_date(value: str) -> date | None:
    s = value.strip()
    try:
        if _ISO_DATE.match(s):
            return date.fromisoformat(s)
        m = _EU_DATE.match(s)
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None
    ts = parse_timestamp(s)
    return ts.astimezone(UTC).date() if ts else None


def parse_timestamp(value: str) -> datetime | None:
    s = value.strip()
    try:
        if _ISO_DATE.match(s):
            return datetime.combine(date.fromisoformat(s), time(), tzinfo=UTC)
        if _ISO_TS.match(s):
            parsed = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T", 1))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        m = _EU_TS.match(s)
        if m:
            return datetime(
                int(m.group(3)),
                int(m.group(2)),
                int(m.group(1)),
                int(m.group(4)),
                int(m.group(5)),
                int(m.group(6) or 0),
                tzinfo=UTC,
            )
        m = _EU_DATE.match(s)
        if m:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=UTC)
    except ValueError:
        return None
    return None


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


# ---------------------------------------------------------------------------------------------- inference


def _infer_strings(values: list[str]) -> LogicalType:
    def all_match(check: Any) -> bool:
        return all(check(v) for v in values)

    stripped = [v.strip() for v in values]
    if all(_INT_RE.match(v) for v in stripped):
        leading_zero = any(len(v.lstrip("+-")) > 1 and v.lstrip("+-").startswith("0") for v in stripped)
        if not leading_zero and all(-(2**63) <= int(v) < 2**63 for v in stripped):
            return "integer"
        return "text"
    if all_match(lambda v: parse_numeric(v) is not None):
        if any(len(v.lstrip("+-")) > 1 and v.lstrip("+-")[0] == "0" and v.lstrip("+-")[1].isdigit() for v in stripped):
            return "text"
        return "numeric"
    if all(v.lower() in BOOL_INFER_WORDS for v in stripped):
        return "boolean"
    if all(_ISO_DATE.match(v) or _EU_DATE.match(v) for v in stripped) and all_match(
        lambda v: parse_date(v) is not None
    ):
        return "date"
    if all(_ISO_TS.match(v) or _EU_TS.match(v) or _ISO_DATE.match(v) for v in stripped) and all_match(
        lambda v: parse_timestamp(v) is not None
    ):
        return "timestamp"
    if all(v[:1] in "{[" for v in stripped):
        try:
            for v in stripped:
                json.loads(v)
            return "json"
        except ValueError:
            return "text"
    return "text"


def infer_type(values: list[Any]) -> LogicalType:
    """Narrowest logical type that represents every non-empty value."""
    present = [v for v in values if not _is_empty(v)]
    if not present:
        return "text"
    if all(isinstance(v, bool) for v in present):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return "integer"
    if all(isinstance(v, int | float | Decimal) and not isinstance(v, bool) for v in present):
        if all(float(v).is_integer() for v in present) and all(abs(float(v)) < 2**53 for v in present):
            return "integer"
        return "numeric"
    if all(isinstance(v, datetime) for v in present):
        return "date" if all(v.time() == time() for v in present) else "timestamp"
    if all(isinstance(v, date) and not isinstance(v, datetime) for v in present):
        return "date"
    if all(isinstance(v, dict | list) for v in present):
        return "json"
    if all(isinstance(v, str) for v in present):
        return _infer_strings(present)
    return _infer_strings([_to_text(v) for v in present])


def infer_columns(columns: list[str], rows: list[list[Any]], *, sample: int = 20000) -> list[LogicalType]:
    sampled = rows[:sample]
    return [infer_type([row[i] if i < len(row) else None for row in sampled]) for i in range(len(columns))]


# ---------------------------------------------------------------------------------------------- coercion


def _to_text(value: Any) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def coerce(value: Any, logical: str) -> Any:
    """Python value for a column of ``logical`` type; empty → None; raises CoercionError when invalid."""
    if _is_empty(value):
        return None
    if logical == "text":
        return _to_text(value)
    if logical == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float | Decimal) and float(value).is_integer():
            return int(value)
        number = parse_numeric(str(value))
        if number is None or number != number.to_integral_value():
            raise CoercionError(f"«{value}» no es un número entero")
        return int(number)
    if logical == "numeric":
        if isinstance(value, bool):
            raise CoercionError(f"«{value}» no es un número")
        if isinstance(value, int | Decimal):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(repr(value))
        number = parse_numeric(str(value))
        if number is None:
            raise CoercionError(f"«{value}» no es un número")
        return number
    if logical == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in (0, 1):
            return bool(value)
        parsed = parse_bool(str(value))
        if parsed is None:
            raise CoercionError(f"«{value}» no es sí/no")
        return parsed
    if logical == "date":
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        parsed_date = parse_date(str(value))
        if parsed_date is None:
            raise CoercionError(f"«{value}» no es una fecha")
        return parsed_date
    if logical == "timestamp":
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, date):
            return datetime.combine(value, time(), tzinfo=UTC)
        parsed_ts = parse_timestamp(str(value))
        if parsed_ts is None:
            raise CoercionError(f"«{value}» no es una fecha y hora")
        return parsed_ts
    if logical == "json":
        if isinstance(value, dict | list | int | float | bool):
            return value
        try:
            return json.loads(str(value))
        except ValueError as exc:
            raise CoercionError(f"«{value}» no es JSON válido") from exc
    raise CoercionError(f"tipo desconocido {logical}")


@dataclass(slots=True)
class ColumnSpec:
    name: str
    type: LogicalType
    nullable: bool = True
    comment: str | None = None
    pk: bool = False
    source_name: str | None = None  # original header / key before sanitizing

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "type": self.type, "nullable": self.nullable, "pk": self.pk}
        if self.comment:
            data["comment"] = self.comment
        if self.source_name and self.source_name != self.name:
            data["source_name"] = self.source_name
        return data


def logical_type(value: str) -> LogicalType:
    lowered = value.strip().lower()
    aliases: dict[str, LogicalType] = {
        "string": "text",
        "varchar": "text",
        "int": "integer",
        "bigint": "integer",
        "number": "numeric",
        "float": "numeric",
        "decimal": "numeric",
        "double": "numeric",
        "bool": "boolean",
        "datetime": "timestamp",
        "timestamptz": "timestamp",
        "jsonb": "json",
        "object": "json",
    }
    if lowered in LOGICAL_TYPES:
        return lowered  # type: ignore[return-value]
    if lowered in aliases:
        return aliases[lowered]
    raise CoercionError(f"Tipo de columna no válido: {value}")
