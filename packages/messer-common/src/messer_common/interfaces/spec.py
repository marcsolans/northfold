"""Interface specification: the JSON stored in ``interfaces/<slug>/interface.json`` of a project repository.

An interface is a set of screens laid out on a 12-column grid. Each screen holds components from the
``@messer/ui`` data library (data table, chart, KPI, form, chat, record list, calendar, file upload, action
button, approvals inbox), and each component is bound to its data or behaviour:

* ``knowledge_sql``    — a read-only SQL query on a knowledge base (``$1…$n`` parameters only)
* ``knowledge_search`` — hybrid/vector/keyword search over one or more knowledge bases
* ``agent``            — a workforce agent (chat, or a prompt built from a form / button / row)
* ``workflow``         — a workforce workflow, with an ``input_mapping`` from form fields, rows, files…
* ``approvals``        — the project's approvals inbox
* ``static``           — inline data

The Composer *composes* this JSON (it never writes screens from scratch), so every model forbids unknown
fields and :func:`messer_common.interfaces.validation.validate_interface` reports precise, located errors.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainValidator,
    WithJsonSchema,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

SPEC_VERSION = 1
GRID_COLUMNS = 12
MAX_GRID_ROW = 500
MAX_STATIC_BYTES = 256 * 1024

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$"
ID_PATTERN = r"^[a-z][a-z0-9_-]{0,63}$"
NAME_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"  # workforce member, form field and input names
EXTENSION_PATTERN = r"^\.[a-z0-9]{1,10}$"
CURRENCY_PATTERN = r"^[A-Z]{3}$"
HEX_COLOR_PATTERN = r"^#[0-9A-Fa-f]{6}$"

Role = Literal["viewer", "builder", "admin", "owner"]
InterfaceKind = Literal["app", "chat"]
ComponentType = Literal[
    "data_table",
    "chart",
    "kpi",
    "form",
    "chat",
    "record_list",
    "calendar",
    "file_upload",
    "action_button",
    "approvals_inbox",
]
COMPONENT_TYPES: tuple[str, ...] = (
    "data_table",
    "chart",
    "kpi",
    "form",
    "chat",
    "record_list",
    "calendar",
    "file_upload",
    "action_button",
    "approvals_inbox",
)
BINDING_KINDS: tuple[str, ...] = ("knowledge_sql", "knowledge_search", "agent", "workflow", "approvals", "static")

# Values a SQL parameter or a workflow input can take from the request context.
CONTEXT_KEYS: tuple[str, ...] = (
    "today",
    "now",
    "month_start",
    "month_end",
    "year_start",
    "user_id",
    "user_email",
)
# ``$source.key`` references accepted by workflow input mappings.
REFERENCE_SOURCES: tuple[str, ...] = ("form", "row", "input", "file", "user", "context")
FILE_KEYS: tuple[str, ...] = ("id", "filename", "kb_id", "mime", "size")
USER_KEYS: tuple[str, ...] = ("id", "email")
_REFERENCE_RE = re.compile(r"^\$(?P<source>[a-z]+)\.(?P<key>[A-Za-z_][A-Za-z0-9_]{0,119})$")

Scalar = str | int | float | bool | None


class SpecModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------------------------------------ values


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def _sql_param(value: Any) -> Any:
    """A SQL parameter: a literal scalar, ``{"input": name, "default": …}`` or ``{"context": key}``."""
    if _is_scalar(value):
        return value
    if isinstance(value, dict):
        keys = set(value)
        if "input" in keys:
            extra = keys - {"input", "default"}
            if extra:
                raise PydanticCustomError(
                    "sql_param", "Campos no admitidos en el parámetro: {fields}", {"fields": ", ".join(sorted(extra))}
                )
            name = value["input"]
            if not isinstance(name, str) or not re.match(NAME_PATTERN, name):
                raise PydanticCustomError(
                    "sql_param", "«input» debe ser un nombre en minúsculas (letras, números y _), p. ej. «estado»"
                )
            if not _is_scalar(value.get("default")):
                raise PydanticCustomError("sql_param", "«default» debe ser un texto, número, booleano o null")
            return {"input": name, "default": value.get("default")}
        if "context" in keys:
            if keys != {"context"}:
                raise PydanticCustomError("sql_param", "Un parámetro de contexto solo admite el campo «context»")
            if value["context"] not in CONTEXT_KEYS:
                raise PydanticCustomError(
                    "sql_param",
                    "Contexto desconocido «{value}»; usa uno de: {allowed}",
                    {"value": str(value["context"]), "allowed": ", ".join(CONTEXT_KEYS)},
                )
            return {"context": value["context"]}
    raise PydanticCustomError(
        "sql_param",
        'Parámetro no válido: usa un valor literal, {"input": "nombre", "default": …} o {"context": "today"}',
    )


SCALAR_SCHEMA: dict[str, Any] = {
    "anyOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "null"}]
}

SqlParam = Annotated[
    Any,
    PlainValidator(_sql_param),
    WithJsonSchema(
        {
            "description": "Valor literal, valor introducido por el usuario o valor de contexto (nunca se "
            "interpola en el SQL: siempre viaja como parámetro $n).",
            "anyOf": [
                *SCALAR_SCHEMA["anyOf"],
                {
                    "type": "object",
                    "properties": {"input": {"type": "string", "pattern": NAME_PATTERN}, "default": SCALAR_SCHEMA},
                    "required": ["input"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {"context": {"enum": list(CONTEXT_KEYS)}},
                    "required": ["context"],
                    "additionalProperties": False,
                },
            ],
        }
    ),
]


def parse_reference(value: str) -> tuple[str, str] | None:
    """``"$form.importe"`` → ``("form", "importe")``; ``None`` for literal strings (``"$$x"`` is the literal "$x")."""
    if not value.startswith("$") or value.startswith("$$"):
        return None
    match = _REFERENCE_RE.match(value)
    if match is None:
        raise ValueError(value)
    return match["source"], match["key"]


def _mapping_value(value: Any) -> Any:
    if not _is_scalar(value):
        raise PydanticCustomError(
            "mapping_value", "El valor debe ser un texto, número, booleano, null o una referencia $"
        )
    if isinstance(value, str):
        try:
            ref = parse_reference(value)
        except ValueError:
            raise PydanticCustomError(
                "mapping_reference",
                "Referencia no válida «{value}»: usa $form.campo, $row.columna, $input.nombre, $file.id, $user.email o "
                "$context.today (escribe $$ para un $ literal)",
                {"value": value},
            ) from None
        if ref is not None:
            source, key = ref
            if source not in REFERENCE_SOURCES:
                raise PydanticCustomError(
                    "mapping_reference",
                    "Origen desconocido «${source}»; usa uno de: {allowed}",
                    {"source": source, "allowed": ", ".join(f"${s}" for s in REFERENCE_SOURCES)},
                )
            allowed = {"file": FILE_KEYS, "user": USER_KEYS, "context": CONTEXT_KEYS}.get(source)
            if allowed is not None and key not in allowed:
                raise PydanticCustomError(
                    "mapping_reference",
                    "«${source}.{key}» no existe; usa: {allowed}",
                    {"source": source, "key": key, "allowed": ", ".join(f"${source}.{k}" for k in allowed)},
                )
    return value


MappingValue = Annotated[
    Any,
    PlainValidator(_mapping_value),
    WithJsonSchema(
        {
            "description": "Literal o referencia: $form.<campo>, $row.<columna>, $input.<nombre>, "
            "$file.<id|filename|kb_id|mime|size>, $user.<id|email>, $context.<today|now|month_start|…>. "
            "Usa $$ para un $ literal.",
            **SCALAR_SCHEMA,
        }
    ),
]


def _scalar(value: Any) -> Any:
    if not _is_scalar(value):
        raise PydanticCustomError("scalar", "Debe ser un texto, número, booleano o null")
    return value


ScalarValue = Annotated[Any, PlainValidator(_scalar), WithJsonSchema(SCALAR_SCHEMA)]


# ------------------------------------------------------------------------------------------------ theme / auth


class Theme(SpecModel):
    accent: str = Field(default="#D52B1E", pattern=HEX_COLOR_PATTERN, description="Color de acento (#RRGGBB)")
    mode: Literal["system", "light", "dark"] = "system"
    density: Literal["comfortable", "compact"] = "comfortable"
    logo_url: str | None = Field(default=None, max_length=2000)

    @field_validator("logo_url")
    @classmethod
    def _logo(cls, value: str | None) -> str | None:
        if value and not (value.startswith("https://") or (value.startswith("/") and not value.startswith("//"))):
            raise PydanticCustomError("logo_url", "El logo debe ser una URL https:// o una ruta relativa /…")
        return value or None


class Auth(SpecModel):
    required: bool | None = Field(
        default=None,
        description="Exigir una sesión de Messer con acceso a la organización. Por defecto: sí en apps, no en chats.",
    )
    roles: list[Role] = Field(default_factory=list, max_length=4, description="Roles admitidos (vacío = cualquiera)")

    @field_validator("roles")
    @classmethod
    def _unique_roles(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class Grid(SpecModel):
    x: int = Field(ge=0, le=GRID_COLUMNS - 1, description="Columna inicial (0–11)")
    y: int = Field(ge=0, le=MAX_GRID_ROW, description="Fila inicial (0…)")
    w: int = Field(ge=1, le=GRID_COLUMNS, description="Ancho en columnas (1–12)")
    h: int = Field(ge=1, le=40, description="Alto en filas")

    @model_validator(mode="after")
    def _fits(self) -> Grid:
        if self.x + self.w > GRID_COLUMNS:
            raise PydanticCustomError(
                "grid_overflow",
                "El componente se sale de la rejilla: x + w = {total} y el máximo son 12 columnas",
                {"total": self.x + self.w},
            )
        return self

    def overlaps(self, other: Grid) -> bool:
        return (
            self.x < other.x + other.w
            and other.x < self.x + self.w
            and self.y < other.y + other.h
            and other.y < self.y + self.h
        )


# ------------------------------------------------------------------------------------------------ bindings


class KnowledgeSqlBinding(SpecModel):
    kind: Literal["knowledge_sql"]
    kb_id: uuid.UUID
    sql: str = Field(min_length=1, max_length=20_000, description="Una consulta de lectura con parámetros $1…$n")
    params: list[SqlParam] = Field(default_factory=list, max_length=50)
    limit: int = Field(default=500, ge=1, le=5000)


class KnowledgeSearchBinding(SpecModel):
    kind: Literal["knowledge_search"]
    kb_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    query: str = Field(default="", max_length=2000, description="Consulta por defecto")
    query_input: str | None = Field(
        default="search", pattern=NAME_PATTERN, description="Entrada que sustituye a la consulta (caja de búsqueda)"
    )
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"
    k: int = Field(default=8, ge=1, le=50)

    @field_validator("kb_ids")
    @classmethod
    def _unique(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(value))


class AgentBinding(SpecModel):
    kind: Literal["agent"]
    workforce: str = Field(pattern=NAME_PATTERN, description="Nombre del agente en workforce/")
    prompt: str | None = Field(
        default=None,
        max_length=8000,
        description="Plantilla del mensaje para formularios, botones y filas: {{form.campo}}, {{row.columna}}, "
        "{{file.filename}}, {{user.email}}",
    )


class WorkflowBinding(SpecModel):
    kind: Literal["workflow"]
    workforce: str = Field(pattern=NAME_PATTERN, description="Nombre del flujo en workforce/")
    input_mapping: dict[str, MappingValue] = Field(
        default_factory=dict, description="Parámetro del flujo → literal o referencia ($form.x, $row.y, …)"
    )

    @field_validator("input_mapping")
    @classmethod
    def _keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(value) > 50:
            raise PydanticCustomError("too_long", "Como máximo 50 parámetros")
        for key in value:
            if not re.match(NAME_PATTERN, key):
                raise PydanticCustomError(
                    "mapping_key", "«{key}» no es un nombre de parámetro válido (minúsculas, números y _)", {"key": key}
                )
        return value


class ApprovalsBinding(SpecModel):
    kind: Literal["approvals"] = "approvals"
    project: str = Field(default="current", description='"current" o el id del proyecto de la interfaz')
    status: Literal["pending", "all"] = "pending"

    @field_validator("project")
    @classmethod
    def _project(cls, value: str) -> str:
        if value != "current":
            try:
                uuid.UUID(value)
            except ValueError:
                raise PydanticCustomError("approvals_project", 'Usa "current" o el id (UUID) del proyecto') from None
        return value


class StaticBinding(SpecModel):
    kind: Literal["static"]
    data: list[dict[str, Any]] | dict[str, Any] = Field(description="Filas (lista de objetos) o un único objeto")

    @field_validator("data")
    @classmethod
    def _size(cls, value: Any) -> Any:
        size = len(json.dumps(value, default=str))
        if size > MAX_STATIC_BYTES:
            raise PydanticCustomError(
                "static_too_large",
                "Los datos estáticos ocupan {size} bytes; el máximo son {max} (usa una base de conocimiento)",
                {"size": size, "max": MAX_STATIC_BYTES},
            )
        return value


TabularBinding = Annotated[KnowledgeSqlBinding | KnowledgeSearchBinding | StaticBinding, Field(discriminator="kind")]
QueryBinding = Annotated[KnowledgeSqlBinding | StaticBinding, Field(discriminator="kind")]
RunBinding = Annotated[WorkflowBinding | AgentBinding, Field(discriminator="kind")]


# ------------------------------------------------------------------------------------------------ props

Format = Literal["text", "number", "currency", "percent", "date", "datetime", "boolean", "badge"]


class Option(SpecModel):
    value: str = Field(max_length=200)
    label: str = Field(min_length=1, max_length=200)


class Column(SpecModel):
    key: str = Field(min_length=1, max_length=120, description="Nombre de la columna en los datos")
    label: str | None = Field(default=None, max_length=120)
    format: Format = "text"
    align: Literal["left", "center", "right"] | None = None


class Filter(SpecModel):
    name: str = Field(pattern=NAME_PATTERN, description='Nombre de la entrada ({"input": nombre} en los parámetros)')
    label: str = Field(min_length=1, max_length=80)
    type: Literal["text", "select", "date", "number"] = "text"
    options: list[Option] = Field(default_factory=list, max_length=100)
    default: ScalarValue = None

    @model_validator(mode="after")
    def _options(self) -> Filter:
        if self.type == "select" and not self.options:
            raise PydanticCustomError("filter_options", "Un filtro de tipo select necesita «options»")
        return self


class RowAction(SpecModel):
    label: str = Field(min_length=1, max_length=60)
    binding: RunBinding
    confirm: str | None = Field(default=None, max_length=300, description="Texto de confirmación antes de ejecutar")


def _unique_names(items: list[Any], attr: str, what: str) -> None:
    seen: set[str] = set()
    for item in items:
        value = getattr(item, attr)
        if value in seen:
            raise PydanticCustomError("duplicate", "{what} «{value}» está repetido", {"what": what, "value": value})
        seen.add(value)


class DataTableProps(SpecModel):
    columns: list[Column] = Field(default_factory=list, max_length=30, description="Vacío = todas las columnas")
    page_size: int = Field(default=10, ge=5, le=100)
    searchable: bool = False
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    row_action: RowAction | None = None
    empty_text: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _unique(self) -> DataTableProps:
        _unique_names(self.columns, "key", "La columna")
        _unique_names(self.filters, "name", "El filtro")
        return self


class ChartProps(SpecModel):
    chart: Literal["bar", "line", "pie", "area"] = "bar"
    x: str | None = Field(default=None, max_length=120, description="Columna del eje X (por defecto, la primera)")
    y: list[str] = Field(default_factory=list, max_length=6, description="Series (por defecto, columnas numéricas)")
    stacked: bool = False
    format: Literal["number", "currency", "percent"] = "number"
    currency: str = Field(default="EUR", pattern=CURRENCY_PATTERN)
    legend: bool = True
    filters: list[Filter] = Field(default_factory=list, max_length=6)


class KpiProps(SpecModel):
    value: str | None = Field(default=None, max_length=120, description="Columna del valor (por defecto, la primera)")
    format: Literal["number", "currency", "percent", "text"] = "number"
    currency: str = Field(default="EUR", pattern=CURRENCY_PATTERN)
    decimals: int | None = Field(default=None, ge=0, le=4)
    delta: str | None = Field(default=None, max_length=120, description="Columna con la variación")
    delta_format: Literal["number", "percent"] = "percent"
    trend: Literal["up_is_good", "down_is_good"] = "up_is_good"
    hint: str | None = Field(default=None, max_length=200)


class FormField(SpecModel):
    name: str = Field(pattern=NAME_PATTERN)
    label: str = Field(min_length=1, max_length=120)
    type: Literal["text", "textarea", "number", "email", "date", "select", "checkbox"] = "text"
    required: bool = False
    placeholder: str | None = Field(default=None, max_length=200)
    help: str | None = Field(default=None, max_length=300)
    options: list[Option] = Field(default_factory=list, max_length=100)
    default: ScalarValue = None
    min: float | None = None
    max: float | None = None
    max_length: int | None = Field(default=None, ge=1, le=10_000)

    @model_validator(mode="after")
    def _consistent(self) -> FormField:
        if self.type == "select" and not self.options:
            raise PydanticCustomError("field_options", "Un campo de tipo select necesita «options»")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise PydanticCustomError("field_range", "«min» no puede ser mayor que «max»")
        return self


class FormProps(SpecModel):
    fields: list[FormField] = Field(min_length=1, max_length=30)
    submit_label: str | None = Field(default=None, max_length=60)
    success_message: str | None = Field(default=None, max_length=300)
    reset_on_submit: bool = True

    @model_validator(mode="after")
    def _unique(self) -> FormProps:
        _unique_names(self.fields, "name", "El campo")
        return self


class ChatProps(SpecModel):
    greeting: str | None = Field(default=None, max_length=1000)
    placeholder: str | None = Field(default=None, max_length=200)
    suggestions: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(default_factory=list, max_length=6)


class RecordListProps(SpecModel):
    title_field: str | None = Field(default=None, max_length=120)
    subtitle_field: str | None = Field(default=None, max_length=120)
    meta_fields: list[str] = Field(default_factory=list, max_length=6)
    badge_field: str | None = Field(default=None, max_length=120)
    page_size: int = Field(default=10, ge=5, le=100)
    searchable: bool = False
    filters: list[Filter] = Field(default_factory=list, max_length=6)
    row_action: RowAction | None = None
    empty_text: str | None = Field(default=None, max_length=200)


class CalendarProps(SpecModel):
    date_field: str = Field(min_length=1, max_length=120, description="Columna con la fecha (o inicio)")
    end_field: str | None = Field(default=None, max_length=120)
    title_field: str | None = Field(default=None, max_length=120)
    view: Literal["month", "agenda"] = "month"


class FileUploadProps(SpecModel):
    kb_id: uuid.UUID = Field(description="Base de conocimiento donde se ingieren los archivos")
    accept: list[Annotated[str, Field(pattern=EXTENSION_PATTERN)]] = Field(default_factory=list, max_length=20)
    max_mb: int = Field(default=20, ge=1, le=100)
    multiple: bool = True
    label: str | None = Field(default=None, max_length=120)
    help: str | None = Field(default=None, max_length=300)


class ActionButtonProps(SpecModel):
    label: str = Field(min_length=1, max_length=60)
    variant: Literal["primary", "secondary", "danger"] = "primary"
    confirm: str | None = Field(default=None, max_length=300)
    success_message: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=300)


class ApprovalsInboxProps(SpecModel):
    page_size: int = Field(default=10, ge=5, le=100)


# ------------------------------------------------------------------------------------------------ components


class ComponentBase(SpecModel):
    id: str = Field(pattern=ID_PATTERN, description="Identificador único en la interfaz")
    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=300)
    grid: Grid


class DataTableComponent(ComponentBase):
    type: Literal["data_table"]
    props: DataTableProps = Field(default_factory=DataTableProps)
    binding: TabularBinding


class ChartComponent(ComponentBase):
    type: Literal["chart"]
    props: ChartProps = Field(default_factory=ChartProps)
    binding: QueryBinding


class KpiComponent(ComponentBase):
    type: Literal["kpi"]
    props: KpiProps = Field(default_factory=KpiProps)
    binding: QueryBinding


class FormComponent(ComponentBase):
    type: Literal["form"]
    props: FormProps
    binding: RunBinding


class ChatComponent(ComponentBase):
    type: Literal["chat"]
    props: ChatProps = Field(default_factory=ChatProps)
    binding: Annotated[AgentBinding, Field(description="El agente que responde")]


class RecordListComponent(ComponentBase):
    type: Literal["record_list"]
    props: RecordListProps = Field(default_factory=RecordListProps)
    binding: TabularBinding


class CalendarComponent(ComponentBase):
    type: Literal["calendar"]
    props: CalendarProps
    binding: QueryBinding


class FileUploadComponent(ComponentBase):
    type: Literal["file_upload"]
    props: FileUploadProps
    binding: Annotated[WorkflowBinding | None, Field(description="Flujo opcional que se ejecuta tras cada archivo")] = (
        None
    )


class ActionButtonComponent(ComponentBase):
    type: Literal["action_button"]
    props: ActionButtonProps
    binding: RunBinding


class ApprovalsInboxComponent(ComponentBase):
    type: Literal["approvals_inbox"]
    props: ApprovalsInboxProps = Field(default_factory=ApprovalsInboxProps)
    binding: ApprovalsBinding = Field(default_factory=ApprovalsBinding)


Component = Annotated[
    DataTableComponent
    | ChartComponent
    | KpiComponent
    | FormComponent
    | ChatComponent
    | RecordListComponent
    | CalendarComponent
    | FileUploadComponent
    | ActionButtonComponent
    | ApprovalsInboxComponent,
    Field(discriminator="type"),
]
AnyComponent = (
    DataTableComponent
    | ChartComponent
    | KpiComponent
    | FormComponent
    | ChatComponent
    | RecordListComponent
    | CalendarComponent
    | FileUploadComponent
    | ActionButtonComponent
    | ApprovalsInboxComponent
)

# Bindings that produce data (served by the data endpoint) vs. bindings that run something.
DATA_COMPONENTS = ("data_table", "chart", "kpi", "record_list", "calendar", "approvals_inbox")
RUN_COMPONENTS = ("form", "action_button")


class Screen(SpecModel):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    layout: Literal["grid"] = "grid"
    components: list[Component] = Field(default_factory=list, max_length=60)


class InterfaceSpec(SpecModel):
    version: Literal[1] = SPEC_VERSION
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=SLUG_PATTERN, description="Carpeta interfaces/<slug>/ y parte de la URL pública")
    kind: InterfaceKind = "app"
    description: str = Field(default="", max_length=500)
    theme: Theme = Field(default_factory=Theme)
    auth: Auth = Field(default_factory=Auth)
    screens: list[Screen] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _consistent(self) -> InterfaceSpec:
        if self.kind == "chat":
            comps = [c for s in self.screens for c in s.components]
            if len(self.screens) != 1 or len(comps) != 1 or comps[0].type != "chat":
                raise PydanticCustomError(
                    "chat_shape",
                    "Una interfaz de tipo chat tiene exactamente una pantalla con un único componente «chat»",
                )
        if self.auth.required is None:
            self.auth.required = self.kind == "app"
        if self.auth.roles and not self.auth.required:
            raise PydanticCustomError("auth_roles", "«auth.roles» solo tiene sentido con «auth.required»: true")
        return self

    # ------------------------------------------------------------------ helpers
    def components(self) -> list[AnyComponent]:
        return [c for s in self.screens for c in s.components]

    def component(self, component_id: str) -> AnyComponent | None:
        return next((c for c in self.components() if c.id == component_id), None)

    @property
    def requires_login(self) -> bool:
        return bool(self.auth.required)

    @property
    def chat_agent(self) -> str | None:
        """The agent of a chat interface (also indexed as ``interfaces.workforce_name``)."""
        if self.kind != "chat":
            return None
        comp = self.components()[0]
        return comp.binding.workforce if isinstance(comp, ChatComponent) else None

    def knowledge_base_ids(self) -> set[uuid.UUID]:
        out: set[uuid.UUID] = set()
        for comp in self.components():
            binding = comp.binding
            if isinstance(binding, KnowledgeSqlBinding):
                out.add(binding.kb_id)
            elif isinstance(binding, KnowledgeSearchBinding):
                out.update(binding.kb_ids)
            if isinstance(comp, FileUploadComponent):
                out.add(comp.props.kb_id)
        return out

    def workforce_names(self) -> set[str]:
        out: set[str] = set()
        for comp in self.components():
            for binding in (comp.binding, _row_action_binding(comp)):
                if isinstance(binding, AgentBinding | WorkflowBinding):
                    out.add(binding.workforce)
        return out

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=False)


def _row_action_binding(comp: AnyComponent) -> Any:
    if isinstance(comp, DataTableComponent | RecordListComponent) and comp.props.row_action is not None:
        return comp.props.row_action.binding
    return None


def run_binding_for(comp: AnyComponent, *, row_action: bool = False) -> AgentBinding | WorkflowBinding | None:
    """The binding an action of ``comp`` runs (form/button submit, file post-processing or a row action)."""
    if row_action:
        binding = _row_action_binding(comp)
    else:
        binding = comp.binding
    return binding if isinstance(binding, AgentBinding | WorkflowBinding) else None


def json_schema() -> dict[str, Any]:
    """JSON Schema of ``interface.json`` (served to the Composer and the editor)."""
    schema = InterfaceSpec.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://messer.local/schemas/interface.v1.json"
    schema["title"] = "Messer interface"
    return schema
