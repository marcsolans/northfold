"""Validation of ``interface.json`` with precise, located errors (the Composer fixes its JSON from them).

``validate_interface(data)`` accepts a dict or JSON text and returns an :class:`InterfaceSpec`, or raises
:class:`InterfaceValidationError` whose ``issues`` are ``{"path", "code", "message"}`` entries such as
``screens[0].components[2].binding.params`` → "La consulta usa $2 pero solo hay 1 parámetro".

Two layers:

1. structure — the pydantic models in :mod:`.spec` (types, required fields, discriminated unions, grid);
2. semantics — checks that need more than one field: every ``knowledge_sql`` query is a single read-only
   statement whose ``$n`` placeholders match ``params`` (the same static analysis the read-only executor uses),
   SQL ``{"input": …}`` parameters that no filter of the component provides, chart/KPI column references.

References to knowledge bases and workforce members are checked against the project by the API (they may
be created later by other Composer builders), and reported as warnings.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from pydantic import ValidationError

from ..knowledge.errors import SqlRejected
from ..knowledge.sqlcheck import analyze
from .spec import (
    BINDING_KINDS,
    COMPONENT_TYPES,
    ChartComponent,
    DataTableComponent,
    InterfaceSpec,
    KnowledgeSqlBinding,
    RecordListComponent,
)

# Placeholder schema name for static SQL checks (the real schema is set by the executor's search_path).
_STATIC_SCHEMA = "kb_static_check"
# Inputs every data component may receive without declaring a filter.
BUILTIN_INPUTS = {"search"}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class InterfaceValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "; ".join(f"{i.path}: {i.message}" for i in issues[:5])
        more = f" (y {len(issues) - 5} más)" if len(issues) > 5 else ""
        super().__init__(f"La interfaz no es válida: {summary}{more}")

    def to_list(self) -> list[dict[str, str]]:
        return [i.to_dict() for i in self.issues]


# ------------------------------------------------------------------------------------------------ paths


def format_path(loc: tuple[int | str, ...]) -> str:
    """pydantic ``loc`` → ``screens[0].components[1].binding.kb_id`` (discriminator tags removed)."""
    out = ""
    prev: int | str | None = None
    prev2: int | str | None = None
    for part in loc:
        is_tag = isinstance(part, str) and (
            (part in COMPONENT_TYPES and isinstance(prev, int) and prev2 == "components")
            or (part in BINDING_KINDS and prev == "binding")
        )
        if not is_tag:
            if isinstance(part, int):
                out += f"[{part}]"
            elif part.startswith("function-") or part in ("str", "int", "float", "bool", "none"):
                pass
            else:
                out += f".{part}" if out else str(part)
        prev2, prev = prev, part
    return out or "$"


def _field_name(loc: tuple[int | str, ...]) -> str:
    for part in reversed(loc):
        if isinstance(part, str):
            return part
    return "valor"


_MESSAGES: dict[str, str] = {
    "missing": "Falta el campo obligatorio «{field}»",
    "extra_forbidden": "El campo «{field}» no existe aquí",
    "string_type": "Debe ser un texto",
    "int_type": "Debe ser un número entero",
    "int_parsing": "Debe ser un número entero",
    "int_from_float": "Debe ser un número entero",
    "float_type": "Debe ser un número",
    "float_parsing": "Debe ser un número",
    "bool_type": "Debe ser true o false",
    "bool_parsing": "Debe ser true o false",
    "uuid_type": "Debe ser un UUID",
    "uuid_parsing": "Debe ser un UUID",
    "dict_type": "Debe ser un objeto",
    "model_type": "Debe ser un objeto",
    "model_attributes_type": "Debe ser un objeto",
    "list_type": "Debe ser una lista",
}


def _message(err: Mapping[str, Any]) -> str:
    kind = str(err.get("type", ""))
    loc = tuple(err.get("loc", ()))
    ctx: dict[str, Any] = dict(err.get("ctx") or {})
    if kind in _MESSAGES:
        return _MESSAGES[kind].format(field=_field_name(loc))
    if kind == "literal_error":
        return f"Valor no válido; se espera {ctx.get('expected', '')}"
    if kind == "union_tag_invalid":
        return (
            f"«{ctx.get('tag')}» no es un «{ctx.get('discriminator', '').strip(chr(39))}» válido aquí; "
            f"usa uno de: {str(ctx.get('expected_tags', '')).replace(chr(39), '')}"
        )
    if kind == "union_tag_not_found":
        return f"Falta el campo «{str(ctx.get('discriminator', '')).strip(chr(39))}» que indica el tipo"
    if kind == "string_too_short":
        return "No puede estar vacío" if ctx.get("min_length") == 1 else f"Mínimo {ctx.get('min_length')} caracteres"
    if kind == "string_too_long":
        return f"Máximo {ctx.get('max_length')} caracteres"
    if kind == "string_pattern_mismatch":
        return f"Formato no válido (debe cumplir {ctx.get('pattern')})"
    if kind == "too_short":
        return f"Debe tener al menos {ctx.get('min_length')} elemento(s)"
    if kind == "too_long":
        return f"Como máximo {ctx.get('max_length')} elementos"
    if kind in ("greater_than_equal", "greater_than"):
        return f"Debe ser {'≥' if kind == 'greater_than_equal' else '>'} {ctx.get('ge', ctx.get('gt'))}"
    if kind in ("less_than_equal", "less_than"):
        return f"Debe ser {'≤' if kind == 'less_than_equal' else '<'} {ctx.get('le', ctx.get('lt'))}"
    message = str(err.get("msg", "Valor no válido"))
    return message.removeprefix("Value error, ")


def issues_from_pydantic(exc: ValidationError) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    seen: set[tuple[str, str]] = set()
    for err in exc.errors(include_url=False):
        path = format_path(tuple(err.get("loc", ())))
        message = _message(err)
        key = (path, message)
        if key in seen:
            continue
        seen.add(key)
        issues.append(ValidationIssue(path=path, code=str(err.get("type", "invalid")), message=message))
    return issues


# ------------------------------------------------------------------------------------------------ semantics


def _sql_issues(binding: KnowledgeSqlBinding, base: str, declared_inputs: set[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        analysis = analyze(binding.sql, own_schema=_STATIC_SCHEMA)
    except SqlRejected as exc:
        return [ValidationIssue(path=f"{base}.sql", code=exc.code, message=exc.message)]
    if analysis.is_explain:
        issues.append(ValidationIssue(f"{base}.sql", "sql_explain", "Las interfaces no admiten EXPLAIN"))
    count = len(binding.params)
    if analysis.max_param > count:
        issues.append(
            ValidationIssue(
                f"{base}.params",
                "sql_params",
                f"La consulta usa ${analysis.max_param} pero solo hay {count} parámetro(s) en «params»",
            )
        )
    elif analysis.max_param < count:
        issues.append(
            ValidationIssue(
                f"{base}.params",
                "sql_params",
                f"Hay {count} parámetro(s) en «params» pero la consulta solo usa hasta ${analysis.max_param}",
            )
        )
    else:
        missing = sorted(set(range(1, analysis.max_param + 1)) - analysis.params_used)
        if missing:
            issues.append(
                ValidationIssue(f"{base}.sql", "sql_params", f"La consulta no usa ${missing[0]}; numera sin huecos")
            )
    for i, param in enumerate(binding.params):
        if isinstance(param, dict) and "input" in param and param["input"] not in declared_inputs | BUILTIN_INPUTS:
            if param.get("default") is None:
                issues.append(
                    ValidationIssue(
                        f"{base}.params[{i}]",
                        "unknown_input",
                        f"Ningún filtro del componente se llama «{param['input']}»; añade el filtro o un «default»",
                    )
                )
    return issues


def _layout_issues(spec: InterfaceSpec) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    screens: dict[str, int] = {}
    components: dict[str, str] = {}
    for si, screen in enumerate(spec.screens):
        if screen.id in screens:
            issues.append(
                ValidationIssue(
                    f"screens[{si}].id",
                    "duplicate_screen",
                    f"La pantalla «{screen.id}» está repetida (screens[{screens[screen.id]}])",
                )
            )
        screens.setdefault(screen.id, si)
        for ci, comp in enumerate(screen.components):
            base = f"screens[{si}].components[{ci}]"
            if comp.id in components:
                issues.append(
                    ValidationIssue(
                        f"{base}.id",
                        "duplicate_component",
                        f"El id «{comp.id}» ya se usa en {components[comp.id]}; los ids son únicos en toda la interfaz",
                    )
                )
            components.setdefault(comp.id, base)
            for pi, other in enumerate(screen.components[:ci]):
                if comp.grid.overlaps(other.grid):
                    issues.append(
                        ValidationIssue(
                            f"{base}.grid",
                            "grid_overlap",
                            f"«{comp.id}» se solapa con «{other.id}» (screens[{si}].components[{pi}]); cambia x/y o "
                            "reduce w/h",
                        )
                    )
    return issues


def semantic_issues(spec: InterfaceSpec) -> list[ValidationIssue]:
    issues = _layout_issues(spec)
    for si, screen in enumerate(spec.screens):
        for ci, comp in enumerate(screen.components):
            base = f"screens[{si}].components[{ci}]"
            filters: set[str] = set()
            if isinstance(comp, DataTableComponent | RecordListComponent | ChartComponent):
                filters = {f.name for f in comp.props.filters}
            if isinstance(comp.binding, KnowledgeSqlBinding):
                issues.extend(_sql_issues(comp.binding, f"{base}.binding", filters))
            if isinstance(comp, ChartComponent) and comp.props.x and comp.props.x in comp.props.y:
                issues.append(
                    ValidationIssue(f"{base}.props.y", "chart_axes", "La columna del eje X no puede ser también serie")
                )
    return issues


# ------------------------------------------------------------------------------------------------ entry point


def _load(data: Any) -> Any:
    if isinstance(data, bytes | bytearray):
        data = bytes(data).decode("utf-8", errors="replace")
    if isinstance(data, str):
        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise InterfaceValidationError(
                [
                    ValidationIssue(
                        "$", "invalid_json", f"JSON no válido en la línea {exc.lineno}, columna {exc.colno}: {exc.msg}"
                    )
                ]
            ) from exc
    return data


def validate_interface(data: Any) -> InterfaceSpec:
    """Parse and validate an interface definition (dict or JSON text). Raises :class:`InterfaceValidationError`."""
    raw = _load(data)
    if not isinstance(raw, Mapping):
        raise InterfaceValidationError([ValidationIssue("$", "invalid_type", "La interfaz debe ser un objeto JSON")])
    try:
        spec = InterfaceSpec.model_validate(dict(raw))
    except ValidationError as exc:
        raise InterfaceValidationError(issues_from_pydantic(exc)) from exc
    issues = semantic_issues(spec)
    if issues:
        raise InterfaceValidationError(issues)
    return spec


def check_interface(data: Any) -> tuple[InterfaceSpec | None, list[ValidationIssue]]:
    """Non-raising variant: ``(spec, [])`` or ``(None, issues)``."""
    try:
        return validate_interface(data), []
    except InterfaceValidationError as exc:
        return None, exc.issues
