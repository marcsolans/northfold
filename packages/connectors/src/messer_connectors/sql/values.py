"""Value and type conversion between database drivers, JSON (agent protocol) and knowledge tables."""

from __future__ import annotations

import base64
import datetime as dt
import math
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

KB_TYPES = ("text", "integer", "numeric", "boolean", "date", "timestamp", "json")


def to_json_value(value: Any) -> Any:
    """JSON-safe representation that keeps precision (decimals as strings, datetimes as ISO 8601)."""
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            return None
        return format(value, "f")
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode()
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [to_json_value(v) for v in value]
    return str(value)


def revive(kb_type: str, value: Any) -> Any:
    """Inverse of :func:`to_json_value` for a knowledge-table column type."""
    if value is None:
        return None
    try:
        if kb_type == "timestamp":
            if isinstance(value, dt.datetime):
                return value
            text = str(value).replace("Z", "+00:00")
            return dt.datetime.fromisoformat(text)
        if kb_type == "date":
            if isinstance(value, dt.datetime):
                return value.date()
            if isinstance(value, dt.date):
                return value
            return dt.date.fromisoformat(str(value)[:10])
        if kb_type == "numeric":
            return value if isinstance(value, Decimal) else Decimal(str(value))
        if kb_type == "integer":
            return value if isinstance(value, int) and not isinstance(value, bool) else int(str(value))
        if kb_type == "boolean":
            if isinstance(value, bool):
                return value
            if isinstance(value, int | float):
                return bool(value)
            return str(value).strip().lower() in ("1", "t", "true", "yes", "y", "si", "sí")
        if kb_type == "json":
            return value
        return value if isinstance(value, str) else str(value)
    except (ValueError, InvalidOperation):
        return None if kb_type != "text" else str(value)


def revive_row(columns: dict[str, str], row: dict[str, Any]) -> dict[str, Any]:
    return {k: revive(columns.get(k, "text"), v) for k, v in row.items()}


# ----------------------------------------------------------------------------- type mapping


def kb_type_postgres(data_type: str, udt: str | None = None) -> str:
    t = data_type.lower()
    u = (udt or "").lower()
    if t in ("smallint", "integer", "bigint") or u in ("int2", "int4", "int8"):
        return "integer"
    if t in ("numeric", "decimal", "real", "double precision", "money") or u in ("float4", "float8", "numeric"):
        return "numeric"
    if t == "boolean" or u == "bool":
        return "boolean"
    if t == "date":
        return "date"
    if t.startswith("timestamp"):
        return "timestamp"
    if t in ("json", "jsonb", "array") or u in ("json", "jsonb") or u.startswith("_"):
        return "json"
    return "text"


def kb_type_mysql(data_type: str, column_type: str | None = None) -> str:
    t = data_type.lower()
    ct = (column_type or "").lower()
    if ct.startswith("tinyint(1)") or ct == "bit(1)" or t in ("bool", "boolean"):
        return "boolean"
    if t in ("tinyint", "smallint", "mediumint", "int", "integer", "bigint", "year"):
        return "integer"
    if t in ("decimal", "numeric", "float", "double", "real"):
        return "numeric"
    if t == "date":
        return "date"
    if t in ("datetime", "timestamp"):
        return "timestamp"
    if t == "json":
        return "json"
    return "text"


def kb_type_sqlserver(data_type: str) -> str:
    t = data_type.lower()
    if t in ("int", "bigint", "smallint", "tinyint"):
        return "integer"
    if t == "bit":
        return "boolean"
    if t in ("decimal", "numeric", "money", "smallmoney", "float", "real"):
        return "numeric"
    if t == "date":
        return "date"
    if t in ("datetime", "datetime2", "smalldatetime", "datetimeoffset"):
        return "timestamp"
    return "text"


def infer_kb_type(values: list[Any]) -> str:
    """Infer a column type from Python values (CRM records, API payloads)."""
    seen = [v for v in values if v is not None and v != ""]
    if not seen:
        return "text"
    if all(isinstance(v, bool) for v in seen):
        return "boolean"
    if all(isinstance(v, int) and not isinstance(v, bool) for v in seen):
        return "integer"
    if all(isinstance(v, int | float | Decimal) and not isinstance(v, bool) for v in seen):
        return "numeric"
    if all(isinstance(v, dict | list) for v in seen):
        return "json"
    if all(isinstance(v, str) for v in seen):
        if all(_is_iso_datetime(v) for v in seen):
            return "timestamp"
        if all(_is_iso_date(v) for v in seen):
            return "date"
        if all(_is_number(v) for v in seen):
            return "numeric"
    return "text"


def _is_iso_datetime(value: str) -> bool:
    if len(value) < 16 or "T" not in value:
        return False
    try:
        dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_iso_date(value: str) -> bool:
    if len(value) != 10:
        return False
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_number(value: str) -> bool:
    if not value or value.strip() != value or (value.startswith("0") and len(value) > 1 and value[1].isdigit()):
        return False  # keep identifiers with leading zeros (postal codes, phone numbers) as text
    try:
        Decimal(value)
        return True
    except InvalidOperation:
        return False
