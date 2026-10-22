"""Workflow graphs edited on the Studio canvas, and their two-way mapping to ``workflow.py``.

``render_workflow_code(config)`` generates plain engine code (``from messer import Workflow``): one ``.step`` per
node, built by the node factories of ``workflow_runtime.py`` (copied next to the workflow), with every binding
``{{node.output.path}}`` / ``{{input.field}}`` / ``{{event.path}}`` rendered into a
``get_run_context().step_span("node")`` lookup so the engine infers the dependencies and runs independent
branches in parallel. Canvas positions live in ``layout.json``.

``parse_workflow_code(code)`` maps a ``workflow.py`` back to the graph without executing it: it reads the
``STUDIO`` metadata plus every literal of the step chain (so hand edits of prompts, URLs, templates… stay in
sync), regenerates the code and accepts the result only when the regenerated step chain is identical to the
file. Anything else returns ``None`` and the Studio switches the member to *code mode* (code wins).
"""

from __future__ import annotations

import ast
import json
import keyword
import math
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..models_config import TIERS, resolve_model
from .agent_spec import BUILTIN_TOOLS

NodeType = Literal[
    "input",
    "agent",
    "llm",
    "tool",
    "connector_action",
    "knowledge_search",
    "sql_query",
    "http_request",
    "condition",
    "loop",
    "transform",
    "approval",
    "wait",
    "sub_workflow",
    "output",
    "custom",
]
NODE_TYPES: tuple[str, ...] = (
    "input",
    "agent",
    "llm",
    "tool",
    "connector_action",
    "knowledge_search",
    "sql_query",
    "http_request",
    "condition",
    "loop",
    "transform",
    "approval",
    "wait",
    "sub_workflow",
    "output",
    "custom",
)
Role = Literal["owner", "admin", "builder", "viewer"]
InputType = Literal["string", "number", "boolean", "object"]

MAX_WAIT_SECONDS = 240  # keep in sync with workflow_runtime.MAX_WAIT_SECONDS (run timeout is 300 s by default)
MAX_LOOP_ITEMS = 500
MAX_NODES = 200
RUNTIME_FILE = "workflow_runtime.py"
CUSTOM_NODES_FILE = "nodes.py"
LAYOUT_FILE = "layout.json"

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_\-]{0,63}$")
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}")
_ANY_BRACES = re.compile(r"\{\{(.*?)\}\}")
RESERVED_IDS = frozenset(
    {"input", "event", "item", "index", "wf", "workflow", "nodes", "studio", "true", "false", "null", "none", "self"}
)
_RESERVED_FIELDS = frozenset({"depends_on", "when", "while_", "runnable"})

# Parameters of the built-in tools a Tool node can call (web search only works inside an agent).
TOOL_PARAMS: dict[str, list[str]] = {
    "knowledge_search": ["query", "top_k"],
    "sql_query": ["sql", "params"],
    "read_url": ["url"],
    "calculator": ["expression"],
    "current_datetime": ["tz"],
    "http_request": ["method", "url", "body", "query"],
    "send_email": ["to", "subject", "body"],
}
LOOP_BODY_TYPES = frozenset(
    {
        "agent",
        "llm",
        "tool",
        "connector_action",
        "knowledge_search",
        "sql_query",
        "http_request",
        "transform",
        "sub_workflow",
        "custom",
    }
)


class WorkflowValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]) -> None:
        super().__init__("; ".join(i["message"] for i in issues[:5]))
        self.issues = issues


# ------------------------------------------------------------------------------------------ node configs


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="ignore")


class InputNodeConfig(_Cfg):
    """The workflow inputs are declared in ``WorkflowConfig.inputs``."""


class AgentNodeConfig(_Cfg):
    agent: str = ""
    prompt: str = ""


class LlmNodeConfig(_Cfg):
    model_tier: Literal["fast", "standard", "powerful"] | None = "standard"
    model: str | None = None
    system: str = ""
    prompt: str = ""
    json_output: bool = False
    max_tokens: int = Field(default=1024, ge=16, le=64_000)
    temperature: float | None = Field(default=None, ge=0, le=1)


class ToolNodeConfig(_Cfg):
    tool: str = "calculator"
    args: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    approver_role: Role = "admin"


class ConnectorActionNodeConfig(_Cfg):
    connection_id: str = ""
    action: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    approver_role: Role = "admin"


class KnowledgeSearchNodeConfig(_Cfg):
    kb_ids: list[str] = Field(default_factory=list)
    query: str = ""
    k: int = Field(default=5, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] = "hybrid"


class SqlQueryNodeConfig(_Cfg):
    kb_id: str = ""
    sql: str = ""
    params: list[Any] = Field(default_factory=list)


class HttpRequestNodeConfig(_Cfg):
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, Any] = Field(default_factory=dict)
    body: Any = None
    allowed_hosts: list[str] = Field(default_factory=list)
    approver_role: Role = "admin"


class ConditionNodeConfig(_Cfg):
    expression: str = ""


class LoopNodeConfig(_Cfg):
    mode: Literal["foreach", "count"] = "foreach"
    items: str = ""
    count: int = Field(default=1, ge=1, le=MAX_LOOP_ITEMS)
    body: str = ""
    max_items: int = Field(default=100, ge=1, le=MAX_LOOP_ITEMS)


class TransformNodeConfig(_Cfg):
    value: Any = ""


class ApprovalNodeConfig(_Cfg):
    prompt: str = ""
    description: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    approver_role: Role = "admin"


class WaitNodeConfig(_Cfg):
    seconds: int = Field(default=5, ge=1, le=MAX_WAIT_SECONDS)


class SubWorkflowNodeConfig(_Cfg):
    workflow: str = ""
    args: dict[str, Any] = Field(default_factory=dict)


class OutputNodeConfig(_Cfg):
    value: Any = ""


class CustomNodeConfig(_Cfg):
    function: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    approver_role: Role = "admin"


NODE_CONFIG_MODELS: dict[str, type[_Cfg]] = {
    "input": InputNodeConfig,
    "agent": AgentNodeConfig,
    "llm": LlmNodeConfig,
    "tool": ToolNodeConfig,
    "connector_action": ConnectorActionNodeConfig,
    "knowledge_search": KnowledgeSearchNodeConfig,
    "sql_query": SqlQueryNodeConfig,
    "http_request": HttpRequestNodeConfig,
    "condition": ConditionNodeConfig,
    "loop": LoopNodeConfig,
    "transform": TransformNodeConfig,
    "approval": ApprovalNodeConfig,
    "wait": WaitNodeConfig,
    "sub_workflow": SubWorkflowNodeConfig,
    "output": OutputNodeConfig,
    "custom": CustomNodeConfig,
}
NODE_CATEGORIES: dict[str, str] = {
    "input": "flow",
    "output": "flow",
    "agent": "ai",
    "llm": "ai",
    "tool": "actions",
    "connector_action": "actions",
    "http_request": "actions",
    "knowledge_search": "data",
    "sql_query": "data",
    "condition": "logic",
    "loop": "logic",
    "transform": "logic",
    "wait": "logic",
    "approval": "human",
    "sub_workflow": "flow",
    "custom": "custom",
}


# --------------------------------------------------------------------------------------------- graph


class Position(BaseModel):
    x: float = 0
    y: float = 0


class WorkflowInput(BaseModel):
    name: str
    type: InputType = "string"
    description: str = ""
    required: bool = False

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _IDENT.match(v) or keyword.iskeyword(v) or v in RESERVED_IDS or v in _RESERVED_FIELDS:
            raise ValueError("El nombre de una entrada usa minúsculas, números y guiones bajos, y empieza por letra")
        return v


class WorkflowNode(BaseModel):
    id: str
    type: NodeType
    label: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position | None = None


class WorkflowEdge(BaseModel):
    source: str
    target: str
    condition: Literal["true", "false"] | None = None


class WorkflowConfig(BaseModel):
    name: str
    description: str = Field(default="", max_length=2000)
    inputs: list[WorkflowInput] = Field(default_factory=list)
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    custom_nodes: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _IDENT.match(v):
            raise ValueError("El nombre debe usar minúsculas, números y guiones bajos, empezando por letra")
        return v

    def node(self, node_id: str) -> WorkflowNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)


def node_config(node: WorkflowNode) -> Any:
    """Typed (and defaulted) configuration of a node. Raises ``ValidationError``."""
    return NODE_CONFIG_MODELS[node.type].model_validate(node.config)


# ------------------------------------------------------------------------------------- safe expressions

_SAFE_FUNCS = frozenset({"len", "abs", "min", "max", "round", "int", "float", "str", "bool", "lower", "upper", "empty"})
_SAFE_NAMES = frozenset({"true", "false", "null", "none"})
_SAFE_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.Constant,
    ast.List,
    ast.Tuple,
    ast.Load,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
    ast.Is,
    ast.IsNot,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Mod,
    ast.Name,
    ast.Call,
)


def expression_error(expression: str) -> str | None:
    """Why a condition expression is not allowed (same rules the runtime evaluator enforces), or None."""
    names: dict[str, str] = {}

    def substitute(match: re.Match[str]) -> str:
        names.setdefault(match.group(1), f"__v{len(names)}")
        return names[match.group(1)]

    source = _PLACEHOLDER.sub(substitute, expression or "").strip()
    if not source:
        return "La condición está vacía"
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        return f"La condición no es válida: {exc.msg}"
    variables = set(names.values())
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            return f"Sintaxis no permitida en la condición: {type(node).__name__}"
        if isinstance(node, ast.Name) and not (
            node.id in variables or node.id.lower() in _SAFE_NAMES or node.id in _SAFE_FUNCS
        ):
            return f"Nombre desconocido en la condición: {node.id}. Usa enlaces como {{{{nodo.output.campo}}}}"
        if isinstance(node, ast.Call) and (
            not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_FUNCS or node.keywords
        ):
            return "Solo se permiten las funciones " + ", ".join(sorted(_SAFE_FUNCS))
    return None


# --------------------------------------------------------------------------------------------- helpers


def placeholders(template: Any) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in _PLACEHOLDER.finditer(value):
                if match.group(1) not in found:
                    found.append(match.group(1))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(template)
    return found


def _malformed(template: Any) -> list[str]:
    """``{{ ... }}`` blocks that are not valid binding paths."""
    bad: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, str):
            for match in _ANY_BRACES.finditer(value):
                if not _PLACEHOLDER.fullmatch(match.group(0)):
                    bad.append(match.group(0))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(template)
    return bad


def safe_field(key: str, taken: set[str]) -> str:
    """Python parameter name for a dict key (``from`` → ``from_``)."""
    base = re.sub(r"\W", "_", key)
    if not base or not (base[0].isalpha() or base[0] == "_"):
        base = f"f_{base}"
    if keyword.iskeyword(base) or base in _RESERVED_FIELDS or base.startswith("__"):
        base = f"{base}_"
    name, n = base, 2
    while name in taken:
        name = f"{base}_{n}"
        n += 1
    taken.add(name)
    return name


def _fields_for(keys: list[str]) -> tuple[list[str], dict[str, str]]:
    taken: set[str] = set()
    fields: list[str] = []
    aliases: dict[str, str] = {}
    for key in keys:
        name = safe_field(key, taken)
        fields.append(name)
        if name != key:
            aliases[name] = key
    return fields, aliases


def _finite(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


# ------------------------------------------------------------------------------------------- validation


def _issue(
    code: str, message: str, *, node_id: str | None = None, edge: WorkflowEdge | None = None, field: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"code": code, "message": message}
    if node_id is not None:
        out["node_id"] = node_id
    if edge is not None:
        out["edge"] = {"source": edge.source, "target": edge.target}
    if field is not None:
        out["field"] = field
    return out


class _Graph:
    """The executable DAG: every edge except a loop's body edge and its optional back edge."""

    def __init__(self, config: WorkflowConfig) -> None:
        self.config = config
        self.by_id = {n.id: n for n in config.nodes}
        self.body_of: dict[str, str] = {}  # body node id → loop id
        for n in config.nodes:
            if n.type == "loop":
                body = str(n.config.get("body") or "")
                if body and body in self.by_id and body != n.id:
                    self.body_of.setdefault(body, n.id)
        self.edges = [
            e
            for e in config.edges
            if e.source in self.by_id
            and e.target in self.by_id
            and not (self.body_of.get(e.target) == e.source or self.body_of.get(e.source) == e.target)
        ]
        self.incoming: dict[str, list[WorkflowEdge]] = {n.id: [] for n in config.nodes}
        self.outgoing: dict[str, list[WorkflowEdge]] = {n.id: [] for n in config.nodes}
        for e in self.edges:
            self.incoming[e.target].append(e)
            self.outgoing[e.source].append(e)

    def steps(self) -> list[WorkflowNode]:
        return [n for n in self.config.nodes if n.id not in self.body_of]

    def cycle(self) -> list[str] | None:
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node_id: str) -> list[str] | None:
            state[node_id] = 1
            stack.append(node_id)
            for e in self.outgoing.get(node_id, []):
                if state.get(e.target) == 1:
                    return stack[stack.index(e.target) :]
                if state.get(e.target, 0) == 0:
                    found = visit(e.target)
                    if found:
                        return found
            stack.pop()
            state[node_id] = 2
            return None

        for n in self.steps():
            if state.get(n.id, 0) == 0:
                found = visit(n.id)
                if found:
                    return found
        return None

    def ancestors(self, node_id: str) -> set[str]:
        seen: set[str] = set()
        todo = [e.source for e in self.incoming.get(node_id, [])]
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            todo.extend(e.source for e in self.incoming.get(current, []))
        return seen

    def order(self) -> list[WorkflowNode]:
        """Topological order (canvas order breaks ties), input first and outputs last."""
        steps = self.steps()
        rank = {n.id: i for i, n in enumerate(steps)}
        indegree = {n.id: len(self.incoming[n.id]) for n in steps}
        ready = sorted(
            (n.id for n in steps if indegree[n.id] == 0), key=lambda i: (self.by_id[i].type != "input", rank[i])
        )
        out: list[str] = []
        while ready:
            current = ready.pop(0)
            out.append(current)
            for e in self.outgoing[current]:
                indegree[e.target] -= 1
                if indegree[e.target] == 0:
                    ready.append(e.target)
                    ready.sort(key=lambda i: rank[i])
        ordered = [self.by_id[i] for i in out]
        return [n for n in ordered if n.type != "output"] + [n for n in ordered if n.type == "output"]


def _templates(node: WorkflowNode, cfg: Any) -> list[tuple[str, Any]]:
    """(field, template) pairs whose bindings are resolved for this node."""
    t = node.type
    if t in ("agent", "llm"):
        return [("prompt", cfg.prompt)]
    if t in ("tool", "connector_action", "sub_workflow", "custom"):
        return [(f"args.{k}", v) for k, v in cfg.args.items()]
    if t == "knowledge_search":
        return [("query", cfg.query)]
    if t == "sql_query":
        return [("params", cfg.params)]
    if t == "http_request":
        return [("url", cfg.url), ("body", cfg.body), ("query", cfg.query)]
    if t == "condition":
        return [("expression", cfg.expression)]
    if t == "loop":
        return [("items", cfg.items)] if cfg.mode == "foreach" else []
    if t in ("transform", "output"):
        return [("value", cfg.value)]
    if t == "approval":
        return [("prompt", cfg.prompt), *[(f"payload.{k}", v) for k, v in cfg.payload.items()]]
    return []


def validate_workflow(
    config: WorkflowConfig,
    *,
    members: dict[str, str] | None = None,
    custom_functions: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Every problem of the graph (empty list when it can be generated). ``members``: other workforce members
    of the project (name → kind); ``custom_functions``: public functions of ``nodes.py``."""
    issues: list[dict[str, Any]] = []
    if len(config.nodes) > MAX_NODES:
        issues.append(_issue("too_many_nodes", f"Un flujo admite como máximo {MAX_NODES} nodos"))
    seen: set[str] = set()
    for n in config.nodes:
        if not _IDENT.match(n.id) or keyword.iskeyword(n.id) or n.id in RESERVED_IDS:
            issues.append(
                _issue(
                    "invalid_id",
                    f"El identificador «{n.id}» no es válido: minúsculas, números y guiones bajos, empezando por letra"
                    " (y no puede ser input, event, item…)",
                    node_id=n.id,
                )
            )
        if n.id in seen:
            issues.append(_issue("duplicate_id", f"Hay dos nodos con el identificador «{n.id}»", node_id=n.id))
        seen.add(n.id)
    input_names = [i.name for i in config.inputs]
    if len(set(input_names)) != len(input_names):
        issues.append(_issue("duplicate_input", "Hay entradas con el mismo nombre"))
    inputs = [n for n in config.nodes if n.type == "input"]
    if len(inputs) != 1:
        issues.append(_issue("input_count", "El flujo necesita exactamente un nodo de entrada"))
    if not any(n.type == "output" for n in config.nodes):
        issues.append(_issue("no_output", "El flujo necesita al menos un nodo de salida"))

    configs: dict[str, Any] = {}
    for n in config.nodes:
        try:
            configs[n.id] = node_config(n)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first.get("loc", ()))
            issues.append(
                _issue(
                    "invalid_config",
                    f"Configuración no válida ({where}): {first.get('msg')}",
                    node_id=n.id,
                    field=where or None,
                )
            )
    if issues:
        return issues

    graph = _Graph(config)
    by_id = graph.by_id
    pairs: set[tuple[str, str]] = set()
    for e in config.edges:
        if e.source not in by_id or e.target not in by_id:
            issues.append(_issue("unknown_edge", "Una conexión apunta a un nodo que no existe", edge=e))
            continue
        if e.source == e.target:
            issues.append(_issue("self_edge", "Un nodo no puede conectarse consigo mismo", edge=e, node_id=e.source))
        if (e.source, e.target) in pairs:
            issues.append(_issue("duplicate_edge", "Conexión duplicada", edge=e, node_id=e.target))
        pairs.add((e.source, e.target))
        source, target = by_id[e.source], by_id[e.target]
        if graph.body_of.get(e.target) == e.source or graph.body_of.get(e.source) == e.target:
            continue
        if target.type == "input":
            issues.append(
                _issue(
                    "edge_into_input",
                    "El nodo de entrada no puede tener conexiones de llegada",
                    edge=e,
                    node_id=target.id,
                )
            )
        if source.type == "output":
            issues.append(
                _issue(
                    "edge_from_output",
                    "Un nodo de salida no puede tener conexiones de salida",
                    edge=e,
                    node_id=source.id,
                )
            )
        if source.type == "condition" and e.condition is None:
            issues.append(
                _issue(
                    "unlabeled_branch", "Las salidas de una condición deben ser «sí» o «no»", edge=e, node_id=source.id
                )
            )
        if source.type != "condition" and e.condition is not None:
            issues.append(
                _issue("unexpected_branch", "Solo las condiciones tienen ramas «sí» / «no»", edge=e, node_id=source.id)
            )

    # loops and their bodies
    for n in config.nodes:
        if n.type != "loop":
            continue
        cfg = configs[n.id]
        if not cfg.body or cfg.body not in by_id or cfg.body == n.id:
            issues.append(_issue("loop_body", "Elige el nodo que se repite en el bucle", node_id=n.id, field="body"))
            continue
        body = by_id[cfg.body]
        if graph.body_of.get(body.id) != n.id:
            issues.append(
                _issue("loop_body_shared", f"«{body.id}» ya es el cuerpo de otro bucle", node_id=n.id, field="body")
            )
            continue
        if body.type not in LOOP_BODY_TYPES:
            issues.append(
                _issue("loop_body_type", "Ese tipo de nodo no puede repetirse dentro de un bucle", node_id=body.id)
            )
        if (n.id, body.id) not in pairs:
            issues.append(_issue("loop_body_edge", "Conecta el bucle con el nodo que repite", node_id=n.id))
        stray = [
            e
            for e in config.edges
            if (e.target == body.id and e.source != n.id) or (e.source == body.id and e.target != n.id)
        ]
        for e in stray:
            issues.append(
                _issue(
                    "loop_body_connections",
                    "El cuerpo de un bucle solo se conecta con su bucle",
                    edge=e,
                    node_id=body.id,
                )
            )
        if cfg.mode == "foreach" and not str(cfg.items).strip():
            issues.append(_issue("loop_items", "Indica la lista que recorre el bucle", node_id=n.id, field="items"))

    if issues:
        return issues

    cycle = graph.cycle()
    if cycle:
        names = " → ".join([*cycle, cycle[0]])
        for node_id in cycle:
            issues.append(_issue("cycle", f"Hay un ciclo: {names}", node_id=node_id))
        return issues

    for n in graph.steps():
        if n.type != "input" and not graph.incoming[n.id]:
            issues.append(_issue("disconnected", "Este nodo no está conectado al flujo", node_id=n.id))

    member_kinds = members or {}
    functions = set(custom_functions) if custom_functions is not None else None
    for n in config.nodes:
        cfg = configs[n.id]
        loop_id = graph.body_of.get(n.id)
        upstream = graph.ancestors(loop_id) | {loop_id} if loop_id else graph.ancestors(n.id)
        for field, template in _templates(n, cfg):
            if not _finite(template):
                issues.append(_issue("invalid_number", "Los números deben ser finitos", node_id=n.id, field=field))
            for bad in _malformed(template):
                issues.append(_issue("invalid_binding", f"Enlace no válido: {bad}", node_id=n.id, field=field))
            for path in placeholders(template):
                problem = _binding_problem(path, n, upstream, loop_id, graph, config)
                if problem:
                    issues.append(_issue("invalid_binding", problem, node_id=n.id, field=field))
        issues.extend(_node_issues(n, cfg, member_kinds, functions, config.name))
    return issues


def _binding_problem(
    path: str, node: WorkflowNode, upstream: set[str], loop_id: str | None, graph: _Graph, config: WorkflowConfig
) -> str | None:
    root, *rest = path.split(".")
    if root == "event":
        return None
    if root == "input":
        if rest and rest[0] not in {i.name for i in config.inputs}:
            return f"La entrada «{rest[0]}» no existe ({{{{{path}}}}})"
        return None
    target = graph.by_id.get(root)
    if target is None:
        return f"El nodo «{root}» no existe ({{{{{path}}}}})"
    if root == loop_id:
        if not rest or rest[0] not in ("item", "index"):
            return f"Dentro del bucle usa {{{{{root}.item}}}} o {{{{{root}.index}}}}"
        return None
    if root in graph.body_of:
        return f"«{root}» se repite dentro de un bucle; usa la salida del bucle ({{{{{graph.body_of[root]}.output}}}})"
    if root not in upstream:
        return f"«{root}» no está antes de «{node.id}» en el flujo ({{{{{path}}}}})"
    if not rest or rest[0] != "output":
        return f"Usa {{{{{root}.output}}}} o {{{{{root}.output.campo}}}}"
    return None


def _node_issues(
    node: WorkflowNode, cfg: Any, members: dict[str, str], functions: set[str] | None, self_name: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    t = node.type

    def bad(code: str, message: str, field: str | None = None) -> None:
        out.append(_issue(code, message, node_id=node.id, field=field))

    def check_keys(container: dict[str, Any], field: str) -> None:
        for key in container:
            if not _KEY.match(key):
                bad("invalid_key", f"«{key}» no es un nombre de campo válido", field)

    if t == "agent":
        if not cfg.agent:
            bad("missing_agent", "Elige el agente", "agent")
        elif members and members.get(cfg.agent) != "agent":
            bad("unknown_agent", f"El agente «{cfg.agent}» no existe en este proyecto", "agent")
        if not cfg.prompt.strip():
            bad("missing_prompt", "Escribe el mensaje para el agente", "prompt")
    elif t == "llm":
        if not cfg.prompt.strip():
            bad("missing_prompt", "Escribe el prompt", "prompt")
        if placeholders(cfg.system):
            bad("system_bindings", "Las instrucciones de sistema no admiten enlaces; ponlos en el prompt", "system")
        if cfg.model:
            try:
                resolve_model(cfg.model)
            except ValueError:
                bad("invalid_model", "El modelo debe tener la forma proveedor/modelo", "model")
    elif t == "tool":
        if cfg.tool not in TOOL_PARAMS:
            bad("unknown_tool", f"La herramienta «{cfg.tool}» no está disponible en flujos", "tool")
        else:
            for key in cfg.args:
                if key not in TOOL_PARAMS[cfg.tool]:
                    bad("unknown_arg", f"«{key}» no es un parámetro de {cfg.tool}", f"args.{key}")
            if cfg.tool == "knowledge_search" and not cfg.options.get("kb_ids"):
                bad("missing_kb", "Elige al menos una base de conocimiento", "options.kb_ids")
            if cfg.tool == "sql_query" and not cfg.options.get("kb_id"):
                bad("missing_kb", "Elige la base de conocimiento", "options.kb_id")
    elif t == "connector_action":
        if not cfg.connection_id:
            bad("missing_connection", "Elige la conexión", "connection_id")
        if not cfg.action:
            bad("missing_action", "Elige la acción", "action")
        check_keys(cfg.args, "args")
    elif t == "knowledge_search":
        if not cfg.kb_ids:
            bad("missing_kb", "Elige al menos una base de conocimiento", "kb_ids")
        if not cfg.query.strip():
            bad("missing_query", "Escribe la consulta", "query")
    elif t == "sql_query":
        if not cfg.kb_id:
            bad("missing_kb", "Elige la base de conocimiento", "kb_id")
        sql = cfg.sql.strip().lower()
        if not sql:
            bad("missing_sql", "Escribe la consulta SQL", "sql")
        elif not (sql.startswith("select") or sql.startswith("with")):
            bad("sql_readonly", "Solo se permiten consultas SELECT (solo lectura)", "sql")
        if "{{" in cfg.sql:
            bad("sql_bindings", "No pongas enlaces dentro del SQL: usa parámetros $1, $2…", "sql")
    elif t == "http_request":
        url = cfg.url.strip()
        if not url:
            bad("missing_url", "Escribe la URL", "url")
        elif not _PLACEHOLDER.fullmatch(url) and not url.startswith(("https://", "http://")):
            bad("invalid_url", "La URL debe empezar por https:// (los enlaces van en la ruta)", "url")
    elif t == "condition":
        error = expression_error(cfg.expression)
        if error:
            bad("invalid_expression", error, "expression")
    elif t == "approval":
        check_keys(cfg.payload, "payload")
    elif t == "sub_workflow":
        if not cfg.workflow:
            bad("missing_workflow", "Elige el flujo", "workflow")
        elif cfg.workflow == self_name:
            bad("recursive_workflow", "Un flujo no puede llamarse a sí mismo", "workflow")
        elif members and members.get(cfg.workflow) != "workflow":
            bad("unknown_workflow", f"El flujo «{cfg.workflow}» no existe en este proyecto", "workflow")
        check_keys(cfg.args, "args")
    elif t == "custom":
        if not cfg.function:
            bad("missing_function", "Elige la función de nodes.py", "function")
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", cfg.function) or keyword.iskeyword(cfg.function):
            bad("invalid_function", "Nombre de función no válido", "function")
        elif functions is not None and cfg.function not in functions:
            bad("unknown_function", f"La función «{cfg.function}» no existe en nodes.py", "function")
        check_keys(cfg.args, "args")
    return out


# ---------------------------------------------------------------------------------------------- render


def _py(value: Any, indent: int = 0) -> str:
    """Python literal for JSON-compatible values (multi-line for large containers)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | tuple):
        items = [_py(v, indent + 4) for v in value]
        flat = "[" + ", ".join(items) + "]"
        if len(flat) + indent <= 100 and "\n" not in flat:
            return flat
        pad = " " * (indent + 4)
        return "[\n" + "".join(f"{pad}{i},\n" for i in items) + " " * indent + "]"
    if isinstance(value, dict):
        items = [f"{_py(str(k))}: {_py(v, indent + 4)}" for k, v in value.items()]
        flat = "{" + ", ".join(items) + "}"
        if len(flat) + indent <= 100 and "\n" not in flat:
            return flat
        pad = " " * (indent + 4)
        return "{\n" + "".join(f"{pad}{i},\n" for i in items) + " " * indent + "}"
    raise TypeError(f"unsupported literal {type(value)}")


class _Step:
    """How one node is written: ``wf.<factory>("<id>", *args, **static)`` plus bound fields (templates)."""

    def __init__(
        self,
        factory: str,
        node_id: str,
        *,
        args: list[str] | None = None,
        static: dict[str, Any] | None = None,
        inputs: dict[str, Any] | None = None,
        binders: dict[str, str] | None = None,
        body: _Step | None = None,
        body_inputs: dict[str, Any] | None = None,
    ) -> None:
        self.factory = factory
        self.node_id = node_id
        self.args = args or []
        self.static = static or {}
        self.inputs = inputs or {}
        self.binders = binders or {}
        self.body = body
        self.body_inputs = body_inputs

    def call(self, indent: int) -> str:
        parts = [_py(self.node_id), *self.args]
        for key, value in self.static.items():
            parts.append(f"{key}={_py(value, indent)}")
        if self.body is not None:
            parts.append(f"body={self.body.call(indent + 4)}")
            parts.append(f"body_inputs={_py(self.body_inputs or {}, indent + 4)}")
        flat = f"wf.{self.factory}(" + ", ".join(parts) + ")"
        if len(flat) + indent <= 110 and "\n" not in flat:
            return flat
        pad = " " * (indent + 4)
        return f"wf.{self.factory}(\n" + "".join(f"{pad}{p},\n" for p in parts) + " " * indent + ")"


def _encode(node: WorkflowNode, graph: _Graph, input_id: str) -> _Step:
    cfg = node_config(node)
    t = node.type
    label = {"label": node.label} if node.label else {}
    if t == "input":
        cfg_inputs = graph.config.inputs
        static: dict[str, Any] = {"fields": {i.name: i.type for i in cfg_inputs}}
        required = [i.name for i in cfg_inputs if i.required]
        if required:
            static["required"] = required
        return _Step("start", node.id, static={**static, **label})
    if t == "agent":
        return _Step("agent", node.id, static={"member": cfg.agent, **label}, inputs={"prompt": cfg.prompt})
    if t == "llm":
        static = {"model": resolve_model(cfg.model or cfg.model_tier or "standard")}
        if cfg.system:
            static["system"] = cfg.system
        if cfg.json_output:
            static["json_output"] = True
        static["max_tokens"] = int(cfg.max_tokens)
        if cfg.temperature is not None:
            static["temperature"] = float(cfg.temperature)
        return _Step("llm", node.id, static={**static, **label}, inputs={"prompt": cfg.prompt})
    if t == "tool":
        static = {"key": cfg.tool, "fields": list(TOOL_PARAMS.get(cfg.tool, []))}
        if cfg.options:
            static["options"] = cfg.options
        if cfg.requires_approval:
            static["requires_approval"] = True
        static["approver_role"] = cfg.approver_role
        return _Step("tool", node.id, static={**static, **label}, inputs=dict(cfg.args))
    if t in ("connector_action", "sub_workflow", "custom", "approval"):
        container = cfg.payload if t == "approval" else cfg.args
        fields, aliases = _fields_for(list(container))
        inputs = {f: container[aliases.get(f, f)] for f in fields}
        args: list[str] = []
        if t == "connector_action":
            static = {"connection_id": cfg.connection_id, "action": cfg.action}
        elif t == "sub_workflow":
            static = {"workflow": cfg.workflow}
        elif t == "custom":
            static = {}
            args = [f"nodes.{cfg.function}"]
        else:
            static = {"prompt": cfg.prompt}
            if cfg.description:
                static["description"] = cfg.description
        static["fields"] = fields
        if aliases:
            static["aliases"] = aliases
        if t in ("connector_action", "custom") and cfg.requires_approval:
            static["requires_approval"] = True
        if t in ("connector_action", "custom", "approval"):
            static["approver_role"] = cfg.approver_role
        if t == "approval":
            static["input_node"] = input_id
        return _Step(t, node.id, args=args, static={**static, **label}, inputs=inputs)
    if t == "knowledge_search":
        static = {"kb_ids": list(cfg.kb_ids), "k": int(cfg.k), "mode": cfg.mode}
        return _Step("knowledge_search", node.id, static={**static, **label}, inputs={"query": cfg.query})
    if t == "sql_query":
        return _Step(
            "sql_query",
            node.id,
            static={"kb_id": cfg.kb_id, "sql": cfg.sql, **label},
            inputs={"params": list(cfg.params)},
        )
    if t == "http_request":
        static = {"method": cfg.method}
        if cfg.headers:
            static["headers"] = dict(cfg.headers)
        if cfg.allowed_hosts:
            static["allowed_hosts"] = list(cfg.allowed_hosts)
        if cfg.method != "GET":
            static["approver_role"] = cfg.approver_role
        inputs: dict[str, Any] = {"url": cfg.url}
        if cfg.body is not None and cfg.body != "":
            inputs["body"] = cfg.body
        if cfg.query:
            inputs["query"] = dict(cfg.query)
        return _Step("http_request", node.id, static={**static, **label}, inputs=inputs)
    if t == "condition":
        return _Step(
            "condition", node.id, static=label, inputs={"expression": cfg.expression}, binders={"expression": "bind"}
        )
    if t == "loop":
        body_node = graph.by_id[cfg.body]
        body = _encode(body_node, graph, input_id)
        static = {"mode": cfg.mode}
        if cfg.mode == "count":
            static["count"] = int(cfg.count)
        static["max_items"] = int(cfg.max_items)
        inputs = {"items": cfg.items} if cfg.mode == "foreach" else {}
        return _Step(
            "loop", node.id, static={**static, **label}, inputs=inputs, body=body, body_inputs=dict(body.inputs)
        )
    if t == "transform":
        return _Step("transform", node.id, static=label, inputs={"value": cfg.value})
    if t == "wait":
        return _Step("wait", node.id, static={"seconds": int(cfg.seconds), **label})
    if t == "output":
        return _Step("output", node.id, static=label, inputs={"value": cfg.value})
    raise ValueError(f"unknown node type {t}")


def _span(node_id: str) -> str:
    return f"get_run_context().step_span({_py(node_id)}, None)"


def _scopes(template: Any, input_id: str, skip_root: str | None = None) -> list[tuple[str, str]]:
    roots: list[str] = []
    for path in placeholders(template):
        root = path.split(".", 1)[0]
        root = "input" if root == "event" else root
        if root != skip_root and root not in roots:
            roots.append(root)
    return [(r, input_id if r == "input" else r) for r in roots]


def _bound(fn: str, template: Any, input_id: str, indent: int) -> str:
    """``lambda: wf.render(<template>, node=get_run_context().step_span("node", None), …)``."""
    scopes = _scopes(template, input_id)
    literal = _py(template, indent + 4)
    if not scopes:
        flat = f"lambda: wf.{fn}({literal})"
        if len(flat) + indent <= 110 or "\n" in literal:
            return flat
        pad = " " * (indent + 4)
        return f"lambda: wf.{fn}(\n{pad}{literal},\n{' ' * indent})"
    pad = " " * (indent + 4)
    lines = [f"lambda: wf.{fn}(", f"{pad}{literal},"]
    lines += [f"{pad}{name}={_span(target)}," for name, target in scopes]
    lines.append(f"{' ' * indent})")
    return "\n".join(lines)


def _skippable(graph: _Graph) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for n in graph.order():
        incoming = graph.incoming[n.id]
        result[n.id] = any(e.condition is not None or result.get(e.source, False) for e in incoming)
    return result


def _when(node: WorkflowNode, graph: _Graph, skippable: dict[str, bool], indent: int) -> str | None:
    incoming = graph.incoming[node.id]
    if not skippable.get(node.id):
        return None
    pad = " " * (indent + 4)
    terms = []
    for e in incoming:
        branch = "" if e.condition is None else (", True" if e.condition == "true" else ", False")
        terms.append(f"wf.active({_span(e.source)}{branch})")
    if len(terms) == 1:
        return f"lambda: {terms[0]}"
    body = f"\n{pad}or ".join(terms)
    return f"lambda: (\n{pad}{body}\n{' ' * indent})"


def _step_code(
    node: WorkflowNode, graph: _Graph, order: list[WorkflowNode], skippable: dict[str, bool], input_id: str
) -> str:
    step = _encode(node, graph, input_id)
    indent = 8
    lines = [f"    .step(\n        {step.call(indent)},"]
    if node.type == "loop":
        if step.inputs.get("items") is not None:
            lines.append(f"        items={_bound('render', step.inputs['items'], input_id, indent)},")
        body_paths = [p for p in placeholders(step.body_inputs or {}) if p.split(".", 1)[0] != node.id]
        if body_paths:
            lines.append(
                f"        context={_bound('collect', ['{{' + p + '}}' for p in body_paths], input_id, indent)},"
            )
    else:
        for field, template in step.inputs.items():
            fn = step.binders.get(field, "render")
            lines.append(f"        {field}={_bound(fn, template, input_id, indent)},")
    deps = [e.source for e in graph.incoming[node.id]]
    if node.type == "output":
        position = {n.id: i for i, n in enumerate(order)}
        before = [n.id for n in order if position[n.id] < position[node.id]]
        deps = before
    deps = [d for d in dict.fromkeys(deps)]
    if deps:
        lines.append(f"        depends_on={_py(deps, indent)},")
    when = _when(node, graph, skippable, indent)
    if when:
        lines.append(f"        when={when},")
    lines.append("    )")
    return "\n".join(lines)


def _studio_meta(config: WorkflowConfig) -> dict[str, Any]:
    return {
        "inputs": [i.model_dump(mode="json") for i in config.inputs],
        "nodes": [
            {"id": n.id, "type": n.type, "label": n.label, "config": node_config(n).model_dump(mode="json")}
            for n in config.nodes
        ],
        "edges": [e.model_dump(mode="json", exclude_none=True) for e in config.edges],
        "custom_nodes": list(config.custom_nodes),
    }


def normalized(config: WorkflowConfig) -> WorkflowConfig:
    """Configs with every default filled in (what is stored and generated)."""
    return config.model_copy(
        update={
            "nodes": [n.model_copy(update={"config": node_config(n).model_dump(mode="json")}) for n in config.nodes]
        }
    )


def render_workflow_code(config: WorkflowConfig, **validation: Any) -> str:
    """``workflow.py`` for a valid graph. Raises :class:`WorkflowValidationError`."""
    issues = validate_workflow(config, **validation)
    if issues:
        raise WorkflowValidationError(issues)
    config = normalized(config)
    graph = _Graph(config)
    order = graph.order()
    input_id = next(n.id for n in config.nodes if n.type == "input")
    skippable = _skippable(graph)
    steps = [_step_code(n, graph, order, skippable, input_id) for n in order]
    body = "\n".join(steps)
    uses_custom = any(n.type == "custom" for n in config.nodes)
    imports = ["from messer import Workflow"]
    if "get_run_context()" in body:
        imports.append("from messer.state import get_run_context")
    local = ["try:  # inside the Messer runtime the member folder is a package"]
    if uses_custom:
        local.append("    from . import nodes")
    local.append("    from . import workflow_runtime as wf")
    local.append("except ImportError:  # loaded as a plain file (messer start, flow introspection)")
    local.append("    import workflow_runtime as wf")
    if uses_custom:
        local.append("")
        local.append('    nodes = wf.sibling(__file__, "nodes")')
    workflow_kwargs = [f"name={_py(config.name)}"]
    if config.description:
        workflow_kwargs.append(f"description={_py(config.description)}")
    summary = config.description.strip().replace('"""', "'''")
    doc = (
        f'"""{config.name} — workflow generated by Messer Studio.\n\n'
        + (f"{summary}\n\n" if summary else "")
        + "Edit freely: while the code keeps the structure below the Studio keeps the canvas in sync; anything else\n"
        "switches the Studio to code mode and this file becomes the source of truth. Node helpers live in\n"
        f"{RUNTIME_FILE} (rewritten by the Studio); custom nodes are the functions of {CUSTOM_NODES_FILE}.\n"
        '"""\n'
    )
    return (
        doc
        + "\n"
        + "\n".join(imports)
        + "\n\n"
        + "\n".join(local)
        + "\n\n"
        + f"workflow = (\n    Workflow({', '.join(workflow_kwargs)})\n{body}\n)\n\n"
        + "# Canvas metadata: graph, labels and node settings (positions live in layout.json).\n"
        + f"STUDIO = {_py(_studio_meta(config))}\n"
    )


# ----------------------------------------------------------------------------------------------- layout


def layout_json(positions: dict[str, Position], viewport: dict[str, Any] | None = None) -> str:
    view = viewport or {"x": 0, "y": 0, "zoom": 1}
    data = {
        "version": 1,
        "viewport": {k: float(view.get(k, 1 if k == "zoom" else 0)) for k in ("x", "y", "zoom")},
        "nodes": {k: {"x": round(p.x, 1), "y": round(p.y, 1)} for k, p in positions.items()},
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_layout(config: WorkflowConfig, viewport: dict[str, Any] | None = None) -> str:
    return layout_json({n.id: n.position for n in config.nodes if n.position}, viewport)


def parse_layout(text: str | None) -> tuple[dict[str, Position], dict[str, float]]:
    try:
        data = json.loads(text or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    positions: dict[str, Position] = {}
    for node_id, pos in (data.get("nodes") or {}).items():
        if isinstance(pos, dict):
            try:
                positions[str(node_id)] = Position(x=float(pos.get("x", 0)), y=float(pos.get("y", 0)))
            except (TypeError, ValueError):
                continue
    raw = data.get("viewport") if isinstance(data.get("viewport"), dict) else {}
    viewport = {"x": 0.0, "y": 0.0, "zoom": 1.0}
    for key in viewport:
        try:
            viewport[key] = float(raw.get(key, viewport[key]))  # type: ignore[union-attr]
        except (TypeError, ValueError):
            continue
    return positions, viewport


def with_positions(config: WorkflowConfig, positions: dict[str, Position]) -> WorkflowConfig:
    return config.model_copy(
        update={"nodes": [n.model_copy(update={"position": positions.get(n.id, n.position)}) for n in config.nodes]}
    )


def auto_layout(config: WorkflowConfig) -> dict[str, Position]:
    """Left-to-right layered layout for graphs without positions (parsed code, templates)."""
    graph = _Graph(config)
    depth: dict[str, int] = {}
    for n in graph.order():
        depth[n.id] = max((depth.get(e.source, 0) + 1 for e in graph.incoming[n.id]), default=0)
    rows: dict[int, int] = {}
    positions: dict[str, Position] = {}
    for n in config.nodes:
        if n.id in graph.body_of:
            continue
        d = depth.get(n.id, 0)
        row = rows.get(d, 0)
        rows[d] = row + 1
        positions[n.id] = Position(x=80 + d * 280, y=80 + row * 140)
    for body_id, loop_id in graph.body_of.items():
        anchor = positions.get(loop_id, Position())
        positions[body_id] = Position(x=anchor.x + 40, y=anchor.y + 160)
    return positions


# ------------------------------------------------------------------------------------------------ parse


class _Unparseable(Exception):
    pass


def _literal(node: ast.AST | None) -> Any:
    if node is None:
        raise _Unparseable("missing")
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError) as exc:
        raise _Unparseable(ast.dump(node)[:80]) from exc


def _factory_call(node: ast.AST) -> tuple[str, str, list[ast.expr], dict[str, ast.expr]]:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "wf"
        and node.args
    ):
        raise _Unparseable("step must be wf.<node>(...)")
    node_id = _literal(node.args[0])
    if not isinstance(node_id, str):
        raise _Unparseable("node id")
    kwargs = {k.arg: k.value for k in node.keywords if k.arg}
    if len(kwargs) != len(node.keywords):
        raise _Unparseable("**kwargs in factory")
    return node.func.attr, node_id, list(node.args[1:]), kwargs


def _template_of(value: ast.expr) -> Any:
    """``lambda: wf.render(<literal>, …)`` → the literal."""
    if not (isinstance(value, ast.Lambda) and isinstance(value.body, ast.Call) and value.body.args):
        raise _Unparseable("bound field must be lambda: wf.render(...)")
    return _literal(value.body.args[0])


_FACTORY_TYPE = {
    "start": "input",
    "agent": "agent",
    "llm": "llm",
    "tool": "tool",
    "connector_action": "connector_action",
    "knowledge_search": "knowledge_search",
    "sql_query": "sql_query",
    "http_request": "http_request",
    "condition": "condition",
    "loop": "loop",
    "transform": "transform",
    "approval": "approval",
    "wait": "wait",
    "sub_workflow": "sub_workflow",
    "output": "output",
    "custom": "custom",
}


def _decode(
    node: WorkflowNode,
    factory: str,
    args: list[ast.expr],
    static_nodes: dict[str, ast.expr],
    inputs: dict[str, Any],
    studio_inputs: list[WorkflowInput],
) -> tuple[WorkflowNode, list[WorkflowInput] | None]:
    if _FACTORY_TYPE.get(factory) != node.type:
        raise _Unparseable("factory does not match the node type")
    static = {k: _literal(v) for k, v in static_nodes.items() if k not in ("body", "body_inputs")}
    cfg = dict(node_config(node).model_dump(mode="json"))
    label = str(static.get("label", ""))
    t = node.type
    new_inputs: list[WorkflowInput] | None = None
    aliases: dict[str, str] = dict(static.get("aliases") or {})
    if t == "input":
        fields = dict(static.get("fields") or {})
        required = set(static.get("required") or [])
        known = {i.name: i for i in studio_inputs}
        new_inputs = [
            WorkflowInput(
                name=str(name),
                type=kind,
                description=known[name].description if name in known else "",
                required=name in required,
            )
            for name, kind in fields.items()
        ]
    elif t == "agent":
        cfg.update(agent=static.get("member", ""), prompt=inputs.get("prompt", ""))
    elif t == "llm":
        model = str(static.get("model") or "")
        tier = cfg.get("model_tier")
        if tier in TIERS and model == resolve_model(tier):
            cfg["model"] = None
        else:
            cfg["model"] = model or None
            cfg["model_tier"] = None if model else tier
        cfg.update(
            system=static.get("system", ""),
            json_output=bool(static.get("json_output", False)),
            max_tokens=static.get("max_tokens", 1024),
            temperature=static.get("temperature"),
            prompt=inputs.get("prompt", ""),
        )
    elif t == "tool":
        cfg.update(
            tool=static.get("key", ""),
            options=static.get("options", {}),
            requires_approval=bool(static.get("requires_approval", False)),
            approver_role=static.get("approver_role", "admin"),
            args={aliases.get(k, k): v for k, v in inputs.items()},
        )
    elif t in ("connector_action", "sub_workflow", "custom", "approval"):
        container = {aliases.get(k, k): v for k, v in inputs.items()}
        if t == "approval":
            cfg.update(
                prompt=static.get("prompt", ""),
                description=static.get("description", ""),
                approver_role=static.get("approver_role", "admin"),
                payload=container,
            )
        else:
            cfg["args"] = container
        if t == "connector_action":
            cfg.update(connection_id=static.get("connection_id", ""), action=static.get("action", ""))
        if t == "sub_workflow":
            cfg["workflow"] = static.get("workflow", "")
        if t == "custom":
            if len(args) != 1 or not (
                isinstance(args[0], ast.Attribute)
                and isinstance(args[0].value, ast.Name)
                and args[0].value.id == "nodes"
            ):
                raise _Unparseable("custom node function")
            cfg["function"] = args[0].attr
        if t in ("connector_action", "custom"):
            cfg.update(
                requires_approval=bool(static.get("requires_approval", False)),
                approver_role=static.get("approver_role", "admin"),
            )
    elif t == "knowledge_search":
        cfg.update(
            kb_ids=static.get("kb_ids", []),
            k=static.get("k", 5),
            mode=static.get("mode", "hybrid"),
            query=inputs.get("query", ""),
        )
    elif t == "sql_query":
        cfg.update(kb_id=static.get("kb_id", ""), sql=static.get("sql", ""), params=inputs.get("params", []))
    elif t == "http_request":
        cfg.update(
            method=static.get("method", "GET"),
            headers=static.get("headers", {}),
            allowed_hosts=static.get("allowed_hosts", []),
            approver_role=static.get("approver_role", cfg.get("approver_role", "admin")),
            url=inputs.get("url", ""),
            body=inputs.get("body"),
            query=inputs.get("query", {}),
        )
    elif t == "condition":
        cfg["expression"] = inputs.get("expression", "")
    elif t == "loop":
        cfg.update(
            mode=static.get("mode", "foreach"),
            count=static.get("count", cfg.get("count", 1)),
            max_items=static.get("max_items", 100),
            items=inputs.get("items", ""),
        )
    elif t in ("transform", "output"):
        cfg["value"] = inputs.get("value", "")
    elif t == "wait":
        cfg["seconds"] = static.get("seconds", 5)
    if args and t != "custom":
        raise _Unparseable("unexpected positional arguments")
    return node.model_copy(update={"label": label, "config": cfg}), new_inputs


def _chain(value: ast.AST) -> tuple[ast.Call, list[ast.Call]]:
    steps: list[ast.Call] = []
    current = value
    while isinstance(current, ast.Call) and isinstance(current.func, ast.Attribute) and current.func.attr == "step":
        steps.append(current)
        current = current.func.value
    if not (isinstance(current, ast.Call) and isinstance(current.func, ast.Name) and current.func.id == "Workflow"):
        raise _Unparseable("workflow must be Workflow(...).step(...)")
    return current, list(reversed(steps))


def _comparable(tree: ast.Module) -> list[str]:
    out: list[str] = []
    for i, stmt in enumerate(tree.body):
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "STUDIO":
            continue
        out.append(ast.dump(stmt, include_attributes=False))
    return out


def parse_workflow_code(code: str) -> WorkflowConfig | None:
    """Map a ``workflow.py`` back to its graph without executing it. ``None`` = code mode."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    assigns: dict[str, ast.expr] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            assigns[stmt.targets[0].id] = stmt.value
        elif isinstance(stmt, ast.Import | ast.ImportFrom | ast.Try) or (
            isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        ):
            continue  # imports are checked against the regenerated module below
        else:
            return None
    if "STUDIO" not in assigns or "workflow" not in assigns:
        return None
    try:
        studio = _literal(assigns["STUDIO"])
        base, steps = _chain(assigns["workflow"])
        base_kwargs = {k.arg: k.value for k in base.keywords if k.arg}
        name = _literal(base_kwargs.get("name"))
        description = _literal(base_kwargs["description"]) if "description" in base_kwargs else ""
        current = WorkflowConfig.model_validate(
            {
                "name": name,
                "description": description,
                "inputs": studio.get("inputs", []),
                "nodes": studio.get("nodes", []),
                "edges": studio.get("edges", []),
                "custom_nodes": studio.get("custom_nodes", []),
            }
        )
        by_id = {n.id: n for n in current.nodes}
        updated: dict[str, WorkflowNode] = {}
        inputs = current.inputs
        for step in steps:
            if not step.args:
                raise _Unparseable("empty step")
            factory, node_id, args, static = _factory_call(step.args[0])
            node = by_id.get(node_id)
            if node is None or node_id in updated:
                raise _Unparseable("unknown node")
            bound: dict[str, Any] = {}
            for kw in step.keywords:
                if kw.arg is None:
                    raise _Unparseable("**kwargs")
                if kw.arg in ("depends_on", "when", "context"):
                    continue
                bound[kw.arg] = _template_of(kw.value)
            decoded, new_inputs = _decode(node, factory, args, static, bound, current.inputs)
            updated[node_id] = decoded
            if new_inputs is not None:
                inputs = new_inputs
            if factory == "loop":
                body_call = static.get("body")
                if body_call is None:
                    raise _Unparseable("loop without body")
                body_factory, body_id, body_args, body_static = _factory_call(body_call)
                body_node = by_id.get(body_id)
                if body_node is None or body_id in updated:
                    raise _Unparseable("unknown loop body")
                body_inputs = _literal(static.get("body_inputs"))
                if not isinstance(body_inputs, dict):
                    raise _Unparseable("body_inputs")
                updated[body_id], _ = _decode(
                    body_node, body_factory, body_args, body_static, body_inputs, current.inputs
                )
        if set(updated) != set(by_id):
            raise _Unparseable("steps do not match the canvas")
        config = current.model_copy(update={"inputs": inputs, "nodes": [updated[n.id] for n in current.nodes]})
        config = WorkflowConfig.model_validate(config.model_dump())
        regenerated = render_workflow_code(config)
    except (_Unparseable, KeyError, ValueError, TypeError, AttributeError, ValidationError):
        return None
    if _comparable(ast.parse(regenerated)) != _comparable(tree):
        return None
    return config


# ------------------------------------------------------------------------------------------ custom nodes


class CustomFunction(BaseModel):
    name: str
    description: str = ""
    params: list[dict[str, Any]] = Field(default_factory=list)
    is_async: bool = False
    line: int = 0


def custom_nodes_template(workflow_name: str) -> str:
    return (
        f'"""Custom nodes of the {workflow_name} workflow.\n\n'
        "Every public function of this file appears in the canvas palette as a custom node. It receives the\n"
        "arguments configured on the node (they can use bindings such as {{node.output.field}}) and returns a\n"
        'JSON-friendly value the following nodes can use. Functions may be sync or async.\n"""\n\n'
        "from typing import Any\n\n\n"
        'def normalizar_texto(texto: str = "") -> dict[str, Any]:\n'
        '    """Limpia los espacios de un texto y devuelve el texto y su longitud."""\n'
        '    limpio = " ".join(str(texto).split())\n'
        '    return {"texto": limpio, "longitud": len(limpio)}\n'
    )


def custom_function_stub(name: str, description: str = "") -> str:
    doc = (description or "Describe qué hace este nodo.").replace('"""', "'")
    return f'\n\ndef {name}(valor: Any = None) -> dict[str, Any]:\n    """{doc}"""\n    return {{"valor": valor}}\n'


def parse_custom_nodes(code: str) -> list[CustomFunction]:
    """Public top-level functions of ``nodes.py``. Raises ``SyntaxError``."""
    tree = ast.parse(code or "")
    out: list[CustomFunction] = []
    for stmt in tree.body:
        if not isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) or stmt.name.startswith("_"):
            continue
        params: list[dict[str, Any]] = []
        positional = [*stmt.args.posonlyargs, *stmt.args.args]
        defaults = [None] * (len(positional) - len(stmt.args.defaults)) + list(stmt.args.defaults)
        for arg, default in zip(positional, defaults, strict=True):
            params.append(
                {
                    "name": arg.arg,
                    "required": default is None,
                    "annotation": ast.unparse(arg.annotation) if arg.annotation is not None else None,
                }
            )
        for arg, kw_default in zip(stmt.args.kwonlyargs, stmt.args.kw_defaults, strict=True):
            params.append(
                {
                    "name": arg.arg,
                    "required": kw_default is None,
                    "annotation": ast.unparse(arg.annotation) if arg.annotation is not None else None,
                }
            )
        out.append(
            CustomFunction(
                name=stmt.name,
                description=(ast.get_docstring(stmt) or "").strip().split("\n\n")[0],
                params=params,
                is_async=isinstance(stmt, ast.AsyncFunctionDef),
                line=stmt.lineno,
            )
        )
    return out


def remove_custom_function(code: str, name: str) -> str:
    """``nodes.py`` without the top-level function ``name`` (decorators included). Raises ``KeyError``."""
    tree = ast.parse(code)
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef) and stmt.name == name:
            start = min([stmt.lineno, *[d.lineno for d in stmt.decorator_list]]) - 1
            end = stmt.end_lineno or stmt.lineno
            lines = code.splitlines(keepends=True)
            rest = lines[:start] + lines[end:]
            return re.sub(r"\n{3,}", "\n\n\n", "".join(rest)).rstrip() + "\n"
    raise KeyError(name)


# ----------------------------------------------------------------------------------------- member files


def runtime_source() -> str:
    return (Path(__file__).with_name(RUNTIME_FILE)).read_text(encoding="utf-8")


def approval_routes(config: WorkflowConfig) -> list[dict[str, Any]]:
    """Approver role per gated node, in the shape the runtime reads from ``workforce.config_json["tools"]``."""
    routes: list[dict[str, Any]] = []
    for n in config.nodes:
        if n.type not in ("approval", "tool", "connector_action", "custom", "http_request"):
            continue
        try:
            cfg = node_config(n)
        except ValidationError:
            continue
        routes.append({"name": n.id, "key": n.id, "approver_role": cfg.approver_role})
    return routes


def stored_config(config: WorkflowConfig) -> dict[str, Any]:
    """``workforce.config_json`` of a workflow: the graph without positions, plus approval routing."""
    clean = normalized(config)
    data = clean.model_dump(mode="json")
    for n in data["nodes"]:
        n.pop("position", None)
    data["tools"] = approval_routes(clean)
    return data


def load_stored_config(data: dict[str, Any] | None) -> WorkflowConfig | None:
    if not data or not data.get("nodes"):
        return None
    try:
        return WorkflowConfig.model_validate({k: v for k, v in data.items() if k != "tools"})
    except ValidationError:
        return None


# --------------------------------------------------------------------------------------------- starters

STARTERS = ("blank", "approval", "classify")


def starter_config(template: str, name: str, description: str = "") -> WorkflowConfig:
    """A small graph to start from: ``blank`` (input → output), ``approval`` (input → transform → human
    approval → output) or ``classify`` (input → LLM → condition → two outputs)."""
    if template == "approval":
        return WorkflowConfig(
            name=name,
            description=description,
            inputs=[
                WorkflowInput(name="importe", type="number", description="Importe a aprobar"),
                WorkflowInput(name="concepto", type="string", description="Concepto"),
            ],
            nodes=[
                WorkflowNode(id="entrada", type="input", label="Entrada"),
                WorkflowNode(
                    id="preparar",
                    type="transform",
                    label="Preparar solicitud",
                    config={
                        "value": {
                            "importe": "{{input.importe}}",
                            "concepto": "{{input.concepto}}",
                            "origen": "{{event.type}}",
                        }
                    },
                ),
                WorkflowNode(
                    id="aprobar",
                    type="approval",
                    label="Aprobación",
                    config={
                        "prompt": "¿Aprobar {{preparar.output.concepto}} por {{preparar.output.importe}} €?",
                        "payload": {
                            "importe": "{{preparar.output.importe}}",
                            "concepto": "{{preparar.output.concepto}}",
                        },
                        "approver_role": "admin",
                    },
                ),
                WorkflowNode(
                    id="resultado",
                    type="output",
                    label="Resultado",
                    config={
                        "value": {
                            "aprobado": True,
                            "importe": "{{aprobar.output.importe}}",
                            "concepto": "{{aprobar.output.concepto}}",
                        }
                    },
                ),
            ],
            edges=[
                WorkflowEdge(source="entrada", target="preparar"),
                WorkflowEdge(source="preparar", target="aprobar"),
                WorkflowEdge(source="aprobar", target="resultado"),
            ],
        )
    if template == "classify":
        return WorkflowConfig(
            name=name,
            description=description,
            inputs=[WorkflowInput(name="texto", type="string", description="Mensaje a clasificar", required=True)],
            nodes=[
                WorkflowNode(id="entrada", type="input", label="Entrada"),
                WorkflowNode(
                    id="clasificar",
                    type="llm",
                    label="Clasificar",
                    config={
                        "model_tier": "fast",
                        "system": "Clasificas mensajes de clientes.",
                        "prompt": 'Devuelve {"urgente": true|false, "motivo": "..."} para este mensaje:\n'
                        "{{input.texto}}",
                        "json_output": True,
                    },
                ),
                WorkflowNode(
                    id="es_urgente",
                    type="condition",
                    label="¿Urgente?",
                    config={"expression": "{{clasificar.output.urgente}} == true"},
                ),
                WorkflowNode(
                    id="urgente",
                    type="output",
                    label="Urgente",
                    config={"value": {"prioridad": "alta", "motivo": "{{clasificar.output.motivo}}"}},
                ),
                WorkflowNode(
                    id="normal",
                    type="output",
                    label="Normal",
                    config={"value": {"prioridad": "normal", "motivo": "{{clasificar.output.motivo}}"}},
                ),
            ],
            edges=[
                WorkflowEdge(source="entrada", target="clasificar"),
                WorkflowEdge(source="clasificar", target="es_urgente"),
                WorkflowEdge(source="es_urgente", target="urgente", condition="true"),
                WorkflowEdge(source="es_urgente", target="normal", condition="false"),
            ],
        )
    return WorkflowConfig(
        name=name,
        description=description,
        inputs=[WorkflowInput(name="mensaje", type="string", description="Dato de entrada")],
        nodes=[
            WorkflowNode(id="entrada", type="input", label="Entrada"),
            WorkflowNode(
                id="resultado",
                type="output",
                label="Resultado",
                config={"value": {"mensaje": "{{input.mensaje}}", "evento": "{{event}}"}},
            ),
        ],
        edges=[WorkflowEdge(source="entrada", target="resultado")],
    )


# -------------------------------------------------------------------------------------------- palette


def palette_node_types() -> list[dict[str, Any]]:
    """Node types with their config JSON schema and defaults (labels are localized by the web app)."""
    out: list[dict[str, Any]] = []
    for t in NODE_TYPES:
        model = NODE_CONFIG_MODELS[t]
        out.append(
            {
                "type": t,
                "category": NODE_CATEGORIES[t],
                "config_schema": model.model_json_schema(),
                "defaults": model().model_dump(mode="json"),
                "loop_body": t in LOOP_BODY_TYPES,
            }
        )
    return out


def palette_tools() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "label": BUILTIN_TOOLS[key]["label"],
            "side_effect": BUILTIN_TOOLS[key]["side_effect"],
            "params": params,
        }
        for key, params in TOOL_PARAMS.items()
    ]


def workflow_member_files(
    *,
    member_id: str,
    config: WorkflowConfig,
    viewport: dict[str, Any] | None = None,
    nodes_code: str | None = None,
    source_mode: str = "config",
) -> dict[str, str]:
    """Every file of a Studio workflow member (``nodes.py`` only when given)."""
    from .project_files import member_manifest

    base = f"workforce/{config.name}"
    files = {
        f"{base}/__init__.py": "",
        f"{base}/workflow.py": render_workflow_code(config),
        f"{base}/{RUNTIME_FILE}": runtime_source(),
        f"{base}/{LAYOUT_FILE}": render_layout(config, viewport),
        f"{base}/messer.yaml": member_manifest(
            member_id=member_id, kind="workflow", source_mode=source_mode, config=stored_config(config)
        ),
    }
    if nodes_code is not None:
        files[f"{base}/{CUSTOM_NODES_FILE}"] = nodes_code
    return files
