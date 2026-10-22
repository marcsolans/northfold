"""Turn bindings into executable requests: SQL parameters, workflow inputs and agent prompts.

User input never reaches SQL text: every value becomes a positional parameter (``$n``) of the read-only
executor. Inputs are coerced to scalars and length-limited.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .spec import FormComponent, FormField, KnowledgeSqlBinding, WorkflowBinding, parse_reference

MAX_INPUT_CHARS = 2000
MAX_INPUTS = 50
_TEMPLATE_RE = re.compile(r"\{\{\s*([a-z]+)\.([A-Za-z_][A-Za-z0-9_]{0,119})\s*\}\}")
DEFAULT_TZ = ZoneInfo("Europe/Madrid")


class BindingInputError(ValueError):
    """An input value cannot be used (wrong type, too long, missing required field). Spanish message."""

    def __init__(self, message: str, *, field_name: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.field_name = field_name


@dataclass(slots=True)
class RequestContext:
    """Who is using the interface and what they sent."""

    user_id: str | None = None
    user_email: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    form: dict[str, Any] = field(default_factory=dict)
    row: dict[str, Any] = field(default_factory=dict)
    file: dict[str, Any] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))


def clean_scalar(value: Any, *, name: str = "valor") -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        if len(value) > MAX_INPUT_CHARS:
            raise BindingInputError(f"«{name}» supera {MAX_INPUT_CHARS} caracteres", field_name=name)
        return value
    raise BindingInputError(f"«{name}» debe ser un texto, número o booleano", field_name=name)


def clean_values(values: dict[str, Any] | None, *, what: str = "entradas") -> dict[str, Any]:
    values = values or {}
    if len(values) > MAX_INPUTS:
        raise BindingInputError(f"Demasiadas {what} (máximo {MAX_INPUTS})")
    return {str(k)[:120]: clean_scalar(v, name=str(k)) for k, v in values.items()}


def context_value(key: str, ctx: RequestContext) -> Any:
    local = ctx.now.astimezone(DEFAULT_TZ)
    today = local.date()
    if key == "today":
        return today.isoformat()
    if key == "now":
        return ctx.now.isoformat()
    if key == "month_start":
        return today.replace(day=1).isoformat()
    if key == "month_end":
        first_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return (first_next - timedelta(days=1)).isoformat()
    if key == "year_start":
        return date(today.year, 1, 1).isoformat()
    if key == "user_id":
        return ctx.user_id
    if key == "user_email":
        return ctx.user_email
    raise BindingInputError(f"Contexto desconocido «{key}»")


def sql_params(binding: KnowledgeSqlBinding, ctx: RequestContext) -> list[Any]:
    """Positional parameters for a knowledge_sql binding (inputs fall back to their default)."""
    out: list[Any] = []
    for param in binding.params:
        if isinstance(param, dict) and "input" in param:
            raw = ctx.inputs.get(param["input"])
            value = param.get("default") if raw in (None, "") else clean_scalar(raw, name=param["input"])
            out.append(value)
        elif isinstance(param, dict) and "context" in param:
            out.append(context_value(param["context"], ctx))
        else:
            out.append(param)
    return out


def reference_value(source: str, key: str, ctx: RequestContext) -> Any:
    if source == "form":
        return ctx.form.get(key)
    if source == "row":
        return ctx.row.get(key)
    if source == "input":
        return ctx.inputs.get(key)
    if source == "file":
        return ctx.file.get(key)
    if source == "user":
        return ctx.user_id if key == "id" else ctx.user_email
    if source == "context":
        return context_value(key, ctx)
    raise BindingInputError(f"Origen desconocido «${source}»")


def workflow_input(binding: WorkflowBinding, ctx: RequestContext) -> dict[str, Any]:
    """Workflow params from ``input_mapping``; without a mapping, the form values (or the row) as they are."""
    if not binding.input_mapping:
        return dict(ctx.form or ctx.row or ctx.inputs)
    params: dict[str, Any] = {}
    for name, value in binding.input_mapping.items():
        if isinstance(value, str):
            ref = parse_reference(value)
            if ref is not None:
                params[name] = reference_value(*ref, ctx)
                continue
            if value.startswith("$$"):
                value = value[1:]
        params[name] = value
    return params


def render_prompt(template: str, ctx: RequestContext) -> str:
    def sub(match: re.Match[str]) -> str:
        source, key = match.group(1), match.group(2)
        try:
            value = reference_value(source, key, ctx)
        except BindingInputError:
            return match.group(0)
        return "" if value is None else str(value)

    return _TEMPLATE_RE.sub(sub, template)


def default_prompt(*, title: str | None, values: dict[str, Any], labels: dict[str, str] | None = None) -> str:
    """Prompt for an agent bound to a form/row without a template: one ``label: value`` line per field."""
    labels = labels or {}
    lines = [f"{labels.get(k, k)}: {'' if v is None else v}" for k, v in values.items()]
    head = f"{title}\n" if title else ""
    return head + "\n".join(lines)


def _coerce_field(spec: FormField, raw: Any) -> Any:
    if raw in (None, "") and spec.type != "checkbox":
        return None
    if spec.type == "checkbox":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() in ("true", "1", "on", "yes", "sí", "si")
    if spec.type == "number":
        number: float | None = None
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            number = float(raw)
        elif isinstance(raw, str):
            try:
                number = float(raw.replace(",", ".").strip())
            except ValueError:
                number = None
        if number is not None and number != number:  # NaN
            number = None
        if number is None:
            raise BindingInputError(f"«{spec.label}» debe ser un número", field_name=spec.name)
        if spec.min is not None and number < spec.min:
            raise BindingInputError(f"«{spec.label}» debe ser ≥ {spec.min:g}", field_name=spec.name)
        if spec.max is not None and number > spec.max:
            raise BindingInputError(f"«{spec.label}» debe ser ≤ {spec.max:g}", field_name=spec.name)
        return int(number) if number.is_integer() else number
    text = str(clean_scalar(raw, name=spec.name)).strip()
    if spec.max_length is not None and len(text) > spec.max_length:
        raise BindingInputError(f"«{spec.label}» admite {spec.max_length} caracteres", field_name=spec.name)
    if spec.type == "email" and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", text):
        raise BindingInputError(f"«{spec.label}» no es un email válido", field_name=spec.name)
    if spec.type == "date":
        try:
            date.fromisoformat(text[:10])
        except ValueError:
            raise BindingInputError(f"«{spec.label}» no es una fecha válida", field_name=spec.name) from None
        return text[:10]
    if spec.type == "select" and text not in {o.value for o in spec.options}:
        raise BindingInputError(f"«{spec.label}»: opción no válida", field_name=spec.name)
    return text


def form_values(component: FormComponent, values: dict[str, Any] | None) -> dict[str, Any]:
    """Validate submitted values against the form fields (required, types, ranges). Unknown keys are dropped."""
    values = values or {}
    out: dict[str, Any] = {}
    for spec in component.props.fields:
        value = _coerce_field(spec, values.get(spec.name, spec.default))
        if spec.required and (value is None or value == "" or value is False):
            raise BindingInputError(f"«{spec.label}» es obligatorio", field_name=spec.name)
        out[spec.name] = value
    return out
