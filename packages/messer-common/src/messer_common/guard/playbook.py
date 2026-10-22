"""Guard playbook: the per-agent behaviour contract (spec 7.13).

A playbook is a list of **policies** plus an optional JSON Schema for the agent's final answers. Each policy is
either a *turn policy* (decides how a model call is served: route to the small or large model, or answer
deterministically) or a *tool policy* (``tool_action``: allow, deny or require approval for the model's tool
calls, optionally only when argument constraints hold).

* ``match`` — structural checks on the request, resolved deterministically (kind of the last message, tool
  results present, regular expressions on the user's text, length, first turn).
* ``condition`` — natural language, decided by three independent votes of the small model and combined per
  ``confirmation`` (``none``: one vote suffices, ``majority``: two of three, ``unanimous``: all three).
  Policies without a condition never call a model.
* ``requires`` / ``provides`` — facts of the conversation. Built-in facts: ``tool:<name>`` once a tool returned a
  successful result in the conversation, ``approval:<name>`` once a human approved that tool in the conversation.
  Policies add their own facts (``provides``) when they apply.

Stored in ``guard_playbooks.playbook`` (one per workforce member) and enforced by the runtime model gateway.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..models_config import guard_models, price_seeds
from ..studio.agent_spec import BUILTIN_TOOLS, AgentConfig, ToolConfig

PLAYBOOK_VERSION = 1
MAX_POLICIES = 100

POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,62}$")
FACT_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,62}(:[A-Za-z0-9_.\-*]{1,120})?$")
BUILTIN_FACT_PREFIXES = ("tool:", "approval:")

Operator = Literal["<", "<=", ">", ">=", "==", "!=", "in", "not_in", "contains", "matches", "exists", "missing"]
NUMERIC_OPS = ("<", "<=", ">", ">=")
Action = Literal["allow", "deny", "require_approval"]
Confirmation = Literal["none", "majority", "unanimous"]
ModelChoice = Literal["small", "large"]
LastMessage = Literal["any", "user_text", "tool_result"]

_SIDE_EFFECT_VERBS = re.compile(
    r"(^|_)(create|send|delete|remove|update|issue|emit|cancel|refund|pay|charge|book|post|write|insert|upsert|"
    r"approve|reject|transfer|submit|crear|enviar|borrar|eliminar|actualizar|emitir|anular|cancelar|pagar|"
    r"reembolsar|reservar|abonar)(_|$)"
)


def _check_regex(pattern: str) -> str:
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Expresión regular no válida: {exc}") from exc
    return pattern


class ArgConstraint(BaseModel):
    """A check on one argument of a tool call (``arg`` is a dotted path into the call's input)."""

    model_config = ConfigDict(extra="forbid")

    arg: str = Field(min_length=1, max_length=200)
    op: Operator
    value: Any = None

    @model_validator(mode="after")
    def _value_fits_operator(self) -> ArgConstraint:
        if self.op in NUMERIC_OPS and (isinstance(self.value, bool) or not isinstance(self.value, int | float)):
            raise ValueError(f"El operador {self.op} necesita un valor numérico")
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            raise ValueError(f"El operador {self.op} necesita una lista de valores")
        if self.op == "matches":
            if not isinstance(self.value, str):
                raise ValueError("El operador matches necesita una expresión regular")
            _check_regex(self.value)
        if self.op in ("exists", "missing"):
            self.value = None
        return self


class ToolAction(BaseModel):
    """What happens to the model's calls of ``tool`` (a tool name or an fnmatch pattern such as ``crm_*``).

    * ``allow`` — calls are allowed when every constraint holds and blocked otherwise.
    * ``deny`` — calls are blocked when every constraint holds (no constraints: always).
    * ``require_approval`` — when every constraint holds the call needs a human: it goes ahead only if the tool is
      approval-gated in the agent (the engine pauses the run) or a human already approved it in this conversation
      (``approval:<tool>``); otherwise Guard blocks it.
    """

    model_config = ConfigDict(extra="forbid")

    tool: str = Field(min_length=1, max_length=120)
    action: Action
    constraints: list[ArgConstraint] = Field(default_factory=list, max_length=20)
    message: str | None = Field(default=None, max_length=1000)

    @field_validator("message")
    @classmethod
    def _blank_message(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None


class TurnMatch(BaseModel):
    """Deterministic, structural checks on the request. Every field that is set must hold."""

    model_config = ConfigDict(extra="forbid")

    last_message: LastMessage = "any"
    tool_results: list[str] = Field(default_factory=list, max_length=20)
    text_patterns: list[str] = Field(default_factory=list, max_length=20)
    text_excludes: list[str] = Field(default_factory=list, max_length=20)
    min_chars: int | None = Field(default=None, ge=0, le=1_000_000)
    max_chars: int | None = Field(default=None, ge=0, le=1_000_000)
    first_turn: bool | None = None

    @field_validator("text_patterns", "text_excludes")
    @classmethod
    def _valid_patterns(cls, v: list[str]) -> list[str]:
        return [_check_regex(p) for p in v]

    def is_empty(self) -> bool:
        return (
            self.last_message == "any"
            and not self.tool_results
            and not self.text_patterns
            and not self.text_excludes
            and self.min_chars is None
            and self.max_chars is None
            and self.first_turn is None
        )


class Policy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=63)
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    condition: str | None = Field(default=None, max_length=2000)
    match: TurnMatch = Field(default_factory=TurnMatch)
    requires: list[str] = Field(default_factory=list, max_length=20)
    provides: list[str] = Field(default_factory=list, max_length=20)
    model: ModelChoice | None = None
    tool_action: ToolAction | None = None
    confirmation: Confirmation = "majority"
    response: str | None = Field(default=None, max_length=4000)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not POLICY_ID_RE.match(v):
            raise ValueError("El id debe usar minúsculas, números, guiones o guiones bajos y empezar por letra")
        return v

    @field_validator("condition", "response")
    @classmethod
    def _blank_is_none(cls, v: str | None) -> str | None:
        return v.strip() or None if v is not None else None

    @field_validator("requires", "provides")
    @classmethod
    def _valid_facts(cls, v: list[str]) -> list[str]:
        for fact in v:
            if not FACT_RE.match(fact):
                raise ValueError(f"Hecho no válido: «{fact}» (usa p. ej. identidad_verificada o approval:crear_abono)")
        return list(dict.fromkeys(v))

    @model_validator(mode="after")
    def _coherent(self) -> Policy:
        if self.response and self.tool_action:
            raise ValueError("Una política con respuesta fija no puede tener acción sobre herramientas")
        return self

    @property
    def kind(self) -> Literal["turn", "tool"]:
        return "tool" if self.tool_action is not None else "turn"


class Playbook(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = PLAYBOOK_VERSION
    enabled: bool = False
    small_model: str
    large_model: str
    policies: list[Policy] = Field(default_factory=list, max_length=MAX_POLICIES)
    output_schema: dict[str, Any] | None = None

    @field_validator("version")
    @classmethod
    def _known_version(cls, v: int) -> int:
        if v != PLAYBOOK_VERSION:
            raise ValueError(f"Versión de playbook no soportada: {v}")
        return v

    @field_validator("small_model", "large_model")
    @classmethod
    def _routable_model(cls, v: str) -> str:
        if "/" not in v:
            raise ValueError("El modelo debe tener el formato proveedor/modelo")
        if not v.startswith("anthropic/"):
            raise ValueError("Guard solo enruta modelos anthropic/* (el gateway habla la API Messages)")
        return v

    @field_validator("output_schema")
    @classmethod
    def _valid_schema(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if not v:
            return None
        try:
            Draft202012Validator.check_schema(v)
        except SchemaError as exc:
            raise ValueError(f"El esquema JSON de salida no es válido: {exc.message}") from exc
        return v

    @model_validator(mode="after")
    def _unique_ids(self) -> Playbook:
        seen: set[str] = set()
        for policy in self.policies:
            if policy.id in seen:
                raise ValueError(f"Id de política repetido: «{policy.id}»")
            seen.add(policy.id)
        return self

    def model_for(self, choice: ModelChoice) -> str:
        return self.small_model if choice == "small" else self.large_model

    def turn_policies(self) -> list[Policy]:
        return [p for p in self.policies if p.enabled and p.tool_action is None]

    def tool_policies(self, tool_name: str) -> list[Policy]:
        return [
            p
            for p in self.policies
            if p.enabled and p.tool_action is not None and tool_matches(p.tool_action.tool, tool_name)
        ]


def tool_matches(pattern: str, name: str) -> bool:
    return pattern == name or fnmatch.fnmatchcase(name, pattern)


def empty_playbook(*, enabled: bool = False) -> Playbook:
    small, large = guard_models()
    return Playbook(enabled=enabled, small_model=small, large_model=large)


# ------------------------------------------------------------------------------------------- agent tools


@dataclass(slots=True)
class ToolInfo:
    """A tool as the model sees it, with what Guard needs to know about it."""

    name: str
    kind: str  # builtin | connector | custom
    label: str
    side_effect: bool
    gated: bool  # the engine pauses the run for human approval before it executes
    input_schema: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "side_effect": self.side_effect,
            "gated": self.gated,
            "input_schema": self.input_schema,
        }


def tool_name(tool: ToolConfig) -> str:
    if tool.type == "connector":
        return tool.name or re.sub(r"[^a-zA-Z0-9_]", "_", tool.key)
    return tool.key


def _looks_side_effect(name: str) -> bool:
    return bool(_SIDE_EFFECT_VERBS.search(name.lower()))


def tools_from_config(config: dict[str, Any] | AgentConfig | None) -> list[ToolInfo]:
    """Tools of an agent configuration (Studio config or the last parseable config of a code-mode agent)."""
    if config is None:
        return []
    raw = config.tools if isinstance(config, AgentConfig) else (config.get("tools") or [])
    out: list[ToolInfo] = []
    for item in raw:
        try:
            tool = item if isinstance(item, ToolConfig) else ToolConfig.model_validate(item)
        except ValidationError:
            continue
        name = tool_name(tool)
        if tool.type == "builtin":
            meta = BUILTIN_TOOLS.get(tool.key, {})
            side_effect = bool(meta.get("side_effect", False))
            # send_email always gates; http_request gates every non-GET request.
            gated = tool.requires_approval or tool.key in ("send_email", "http_request")
            label = str(meta.get("label") or tool.key)
        else:
            side_effect = tool.requires_approval or _looks_side_effect(name)
            gated = tool.requires_approval
            label = tool.description or name
        out.append(
            ToolInfo(
                name=name,
                kind=tool.type,
                label=label,
                side_effect=side_effect,
                gated=gated,
                input_schema=tool.input_schema,
            )
        )
    return out


def known_models() -> list[dict[str, str]]:
    return [
        {"id": seed.model, "label": seed.display_name} for seed in price_seeds() if seed.model.startswith("anthropic/")
    ]


# ------------------------------------------------------------------------------------------- validation


@dataclass(slots=True)
class Issue:
    level: Literal["error", "warning"]
    path: str
    code: str
    message: str
    params: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "params": self.params,
        }


@dataclass(slots=True)
class ValidationResult:
    playbook: Playbook | None
    issues: list[Issue]

    @property
    def ok(self) -> bool:
        return self.playbook is not None and not any(i.level == "error" for i in self.issues)


_PYDANTIC_MESSAGES = {
    "missing": "Campo obligatorio",
    "extra_forbidden": "Campo no reconocido",
    "string_type": "Debe ser un texto",
    "string_too_short": "No puede estar vacío",
    "string_too_long": "Demasiado largo",
    "bool_type": "Debe ser verdadero o falso",
    "bool_parsing": "Debe ser verdadero o falso",
    "int_type": "Debe ser un número entero",
    "int_parsing": "Debe ser un número entero",
    "list_type": "Debe ser una lista",
    "dict_type": "Debe ser un objeto",
    "model_type": "Debe ser un objeto",
    "literal_error": "Valor no permitido",
    "too_long": "Demasiados elementos",
    "greater_than_equal": "Valor demasiado pequeño",
    "less_than_equal": "Valor demasiado grande",
}


def _path(loc: tuple[int | str, ...]) -> str:
    return ".".join(str(p) for p in loc)


def _schema_issues(exc: ValidationError) -> list[Issue]:
    issues: list[Issue] = []
    for err in exc.errors(include_url=False):
        kind = str(err.get("type", "value_error"))
        if kind == "value_error":
            message = str(err.get("msg", "")).removeprefix("Value error, ")
        else:
            message = _PYDANTIC_MESSAGES.get(kind, str(err.get("msg", "Valor no válido")))
        issues.append(Issue("error", _path(tuple(err.get("loc", ()))), f"schema.{kind}", message))
    return issues


def _numeric_props(schema: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    props = (schema or {}).get("properties") or {}
    return {k: v for k, v in props.items() if isinstance(v, dict) and v.get("type") in ("number", "integer")}


def validate_playbook(data: Any, *, tools: list[ToolInfo] | None = None) -> ValidationResult:
    """Schema errors (the playbook cannot be stored) plus warnings against the agent's current tools."""
    try:
        playbook = Playbook.model_validate(data)
    except ValidationError as exc:
        return ValidationResult(None, _schema_issues(exc))
    issues: list[Issue] = []
    known = {m["id"] for m in known_models()}
    for key in ("small_model", "large_model"):
        model = getattr(playbook, key)
        if model not in known:
            issues.append(
                Issue("warning", key, "unknown_model", f"{model} no está en el catálogo de modelos", {"model": model})
            )

    provided = {f for p in playbook.policies for f in p.provides}
    by_name = {t.name: t for t in tools or []}
    for i, policy in enumerate(playbook.policies):
        base = f"policies.{i}"
        for j, fact in enumerate(policy.requires):
            if not fact.startswith(BUILTIN_FACT_PREFIXES) and fact not in provided:
                issues.append(
                    Issue(
                        "warning",
                        f"{base}.requires.{j}",
                        "fact_never_provided",
                        f"Ninguna política establece «{fact}»: la condición nunca se cumplirá",
                        {"fact": fact},
                    )
                )
        if policy.tool_action is None and policy.model is None and policy.response is None and not policy.provides:
            issues.append(
                Issue("warning", base, "noop_policy", "La política no enruta, no responde ni establece hechos")
            )
        if policy.tool_action is None and policy.match.is_empty() and policy.condition is None:
            issues.append(
                Issue(
                    "warning",
                    f"{base}.match",
                    "matches_every_turn",
                    "Sin coincidencia ni condición: se aplica a todos los turnos y oculta las políticas siguientes",
                )
            )
        action = policy.tool_action
        if action is None or tools is None:
            continue
        matching = [t for t in by_name.values() if tool_matches(action.tool, t.name)]
        if not matching:
            issues.append(
                Issue(
                    "warning",
                    f"{base}.tool_action.tool",
                    "unknown_tool",
                    f"El agente no tiene ninguna herramienta «{action.tool}»",
                    {"tool": action.tool},
                )
            )
            continue
        if action.action == "require_approval":
            for t in matching:
                if not t.gated:
                    issues.append(
                        Issue(
                            "warning",
                            f"{base}.tool_action.action",
                            "approval_not_gated",
                            f"«{t.name}» no requiere aprobación en el agente: Guard bloqueará estas llamadas salvo que "
                            "un humano ya las haya aprobado. Marca «requiere aprobación» en la herramienta.",
                            {"tool": t.name},
                        )
                    )
        for k, constraint in enumerate(action.constraints):
            root = constraint.arg.split(".", 1)[0]
            for t in matching:
                props = (t.input_schema or {}).get("properties")
                if not isinstance(props, dict):
                    continue
                if root not in props:
                    issues.append(
                        Issue(
                            "warning",
                            f"{base}.tool_action.constraints.{k}.arg",
                            "unknown_arg",
                            f"«{t.name}» no tiene el argumento «{root}»",
                            {"tool": t.name, "arg": root},
                        )
                    )
                elif constraint.op in NUMERIC_OPS and root not in _numeric_props(t.input_schema):
                    issues.append(
                        Issue(
                            "warning",
                            f"{base}.tool_action.constraints.{k}.op",
                            "non_numeric_arg",
                            f"«{root}» no es numérico en «{t.name}»",
                            {"tool": t.name, "arg": root},
                        )
                    )
    return ValidationResult(playbook, issues)
