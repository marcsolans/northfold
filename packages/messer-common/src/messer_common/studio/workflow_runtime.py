"""Messer Studio workflow nodes — copied next to every Studio workflow as ``workflow_runtime.py``.

The Studio rewrites this file whenever the canvas is saved; do not edit it by hand (put your own logic in
``nodes.py``). It only depends on the engine (``messer``), so an exported project runs anywhere.

Every node of a Studio workflow is an engine ``Tool`` named after the node id, so ``workflow.py`` stays plain
engine code::

    workflow = (
        Workflow(name="facturas")
        .step(wf.start("entrada", fields={"factura": "string"}))
        .step(
            wf.http_request("consultar", method="GET"),
            url=lambda: wf.render(
                "https://api.example.com/facturas/{{input.factura}}",
                input=get_run_context().step_span("entrada", None),
            ),
            depends_on=["entrada"],
        )
    )

Bindings — ``{{node.output.path}}``, ``{{input.field}}``, ``{{event.path}}`` and, inside a loop body,
``{{loop_id.item.path}}`` / ``{{loop_id.index}}`` — are resolved by :func:`render` from the spans that
``workflow.py`` reads with ``get_run_context().step_span(...)``, which is also how the engine infers the
dependencies between steps and runs independent nodes in parallel.

Resumed runs (after a human approval) replay every node that already succeeded in the paused run with the same
input instead of executing it again: side effects never run twice and model answers do not change between the
pause and the decision (the approval id derives from the approved input).
"""

from __future__ import annotations

import ast
import asyncio
import contextvars
import hashlib
import importlib
import importlib.util
import inspect
import json
import math
import operator
import os
import re
import sys
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import yaml

from messer import Agent
from messer.core.tool import Tool
from messer.platform import tools as platform_tools
from messer.state import get_run_context
from messer.types.events.output import OutputEvent

RUNTIME_VERSION = "1"
MAX_WAIT_SECONDS = 240
"""A wait node sleeps at most 4 minutes: a run is bounded by the runtime timeout (5 minutes by default)."""
MAX_LOOP_ITEMS = 500
MAX_SUB_WORKFLOW_DEPTH = 5
JSON_INSTRUCTION = "\n\nResponde únicamente con un objeto JSON válido, sin texto adicional ni bloques de código."

_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_\-]+)*)\s*\}\}")
_SECRET_REF = re.compile(r"\$([A-Z][A-Z0-9_]*)")
_HERE = Path(__file__).resolve().parent
_PACKAGE_ROOT = __package__.rsplit(".", 1)[0] if __package__ and "." in __package__ else None
_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar("messer_studio_workflow_depth", default=0)
_RESULTS: dict[str, Any] = {}
_PARENT_TRACES: dict[str, asyncio.Future[Any]] = {}
_MISS = object()


# ------------------------------------------------------------------------------------------------ bindings


class LoopFrame:
    """What ``{{loop_id.item}}`` and ``{{loop_id.index}}`` resolve to inside a loop body."""

    __slots__ = ("index", "item")

    def __init__(self, item: Any, index: int) -> None:
        self.item = item
        self.index = index


def _plain(value: Any) -> Any:
    """JSON-friendly view of a node output (messages become their text, models their fields)."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    collect_text = getattr(value, "collect_text", None)
    if callable(collect_text):
        return collect_text()
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _output_of(scope: Any) -> Any:
    if scope is None:
        return None
    if isinstance(scope, dict) and "output" not in scope:
        return scope
    return _plain(getattr(scope, "output", None) if not isinstance(scope, dict) else scope.get("output"))


def _dig(value: Any, parts: list[str]) -> Any:
    current = _plain(value)
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        current = _plain(current)
    return current


def _resolve(path: str, scopes: dict[str, Any], values: dict[str, Any] | None) -> Any:
    if values is not None and path in values:
        return values[path]
    root, *rest = path.split(".")
    if root in ("input", "event"):
        base = _output_of(scopes.get("input"))
        if root == "event":
            base = base.get("event") if isinstance(base, dict) else None
        return _dig(base, rest)
    scope = scopes.get(root)
    if isinstance(scope, LoopFrame):
        if rest and rest[0] == "item":
            return _dig(scope.item, rest[1:])
        if rest and rest[0] == "index":
            return scope.index
        return None
    if scope is None or not rest or rest[0] != "output":
        return None
    return _dig(_output_of(scope), rest[1:])


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)


def _render(template: Any, scopes: dict[str, Any], values: dict[str, Any] | None) -> Any:
    if isinstance(template, str):
        single = _PLACEHOLDER.fullmatch(template.strip())
        if single is not None:
            return _resolve(single.group(1), scopes, values)
        return _PLACEHOLDER.sub(lambda m: _to_text(_resolve(m.group(1), scopes, values)), template)
    if isinstance(template, dict):
        return {k: _render(v, scopes, values) for k, v in template.items()}
    if isinstance(template, list):
        return [_render(v, scopes, values) for v in template]
    return template


def render(template: Any, /, **scopes: Any) -> Any:
    """Resolve the bindings of a template.

    A string that is exactly one ``{{...}}`` returns the bound value unchanged (lists, objects, numbers); text
    with bindings is interpolated; objects and lists are rendered recursively. Missing values are ``None``.
    ``scopes`` maps binding roots to spans: node ids, plus ``input`` (the input node, also used by ``event``).
    """
    values = scopes.pop("_values", None)
    return _render(template, scopes, values)


def placeholders(template: Any) -> list[str]:
    """Binding paths used by a template, in order of appearance (without duplicates)."""
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


def collect(template: Any, /, **scopes: Any) -> dict[str, Any]:
    """Values of every binding of ``template`` (a loop body's context, resolved before iterating)."""
    return {path: _resolve(path, scopes, None) for path in placeholders(template)}


def bind(expression: str, /, **scopes: Any) -> dict[str, Any]:
    """A condition expression with the values of its bindings (evaluated by the condition node)."""
    return {"expression": expression, "values": collect(expression, **scopes)}


def active(span: Any, branch: bool | None = None) -> bool:
    """Whether an upstream step ran successfully (and, for a condition, took ``branch``)."""
    if span is None:
        return False
    status = getattr(span, "status", None)
    code = status.get("code") if isinstance(status, dict) else getattr(status, "code", None)
    if code != "success":
        return False
    if branch is None:
        return True
    return bool(_plain(getattr(span, "output", None))) is branch


# ------------------------------------------------------------------------------------- safe expressions

_COMPARE: dict[type, Callable[[Any, Any], Any]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b if b is not None else False,
    ast.NotIn: lambda a, b: a not in b if b is not None else True,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_ARITH: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


_FUNCS: dict[str, Callable[..., Any]] = {
    "len": lambda v: len(v) if v is not None else 0,
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "int": int,
    "float": float,
    "str": _to_text,
    "bool": bool,
    "lower": lambda v: _to_text(v).lower(),
    "upper": lambda v: _to_text(v).upper(),
    "empty": _empty,
}
_NAMES: dict[str, Any] = {"true": True, "false": False, "null": None, "none": None}


class ExpressionError(ValueError):
    pass


def compile_expression(expression: str) -> tuple[ast.Expression, dict[str, str]]:
    """Parse a condition (bindings become variables ``v0``, ``v1``…) and check it only uses safe syntax."""
    names: dict[str, str] = {}

    def substitute(match: re.Match[str]) -> str:
        path = match.group(1)
        names.setdefault(path, f"__v{len(names)}")
        return names[path]

    source = _PLACEHOLDER.sub(substitute, expression or "").strip()
    if not source:
        raise ExpressionError("La condición está vacía")
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"La condición no es válida: {exc.msg}") from exc
    variables = set(names.values())
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if node.id not in variables and node.id.lower() not in _NAMES and node.id not in _FUNCS:
                raise ExpressionError(f"Nombre desconocido en la condición: {node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
                raise ExpressionError("Solo se permiten las funciones " + ", ".join(sorted(_FUNCS)))
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _ARITH:
                raise ExpressionError("Operador no permitido en la condición")
        elif isinstance(node, ast.Compare):
            if any(type(op) not in _COMPARE for op in node.ops):
                raise ExpressionError("Comparación no permitida en la condición")
        elif not isinstance(
            node,
            ast.Expression
            | ast.BoolOp
            | ast.And
            | ast.Or
            | ast.UnaryOp
            | ast.Not
            | ast.USub
            | ast.UAdd
            | ast.Constant
            | ast.List
            | ast.Tuple
            | ast.Load
            | ast.cmpop
            | ast.operator,
        ):
            raise ExpressionError(f"Sintaxis no permitida en la condición: {type(node).__name__}")
    return tree, {v: k for k, v in names.items()}


def evaluate(expression: str, values: dict[str, Any]) -> bool:
    """Evaluate a condition over bound values without executing code (comparisons, and/or/not, membership)."""
    tree, variables = compile_expression(expression)
    env = {name: values.get(path) for name, path in variables.items()}

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            return _NAMES[node.id.lower()]
        if isinstance(node, ast.List | ast.Tuple):
            return [ev(e) for e in node.elts]
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return all(bool(ev(v)) for v in node.values)
            return any(bool(ev(v)) for v in node.values)
        if isinstance(node, ast.UnaryOp):
            operand = ev(node.operand)
            if isinstance(node.op, ast.Not):
                return not operand
            if isinstance(node.op, ast.USub):
                return -operand
            return +operand
        if isinstance(node, ast.BinOp):
            try:
                return _ARITH[type(node.op)](ev(node.left), ev(node.right))
            except (TypeError, ZeroDivisionError):
                return None
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comparator in zip(node.ops, node.comparators, strict=True):
                right = ev(comparator)
                try:
                    ok = _COMPARE[type(op)](left, right)
                except TypeError:
                    ok = False
                if not ok:
                    return False
                left = right
            return True
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            try:
                return _FUNCS[node.func.id](*[ev(a) for a in node.args])
            except (TypeError, ValueError):
                return None
        raise ExpressionError(f"Sintaxis no permitida: {type(node).__name__}")

    result = ev(tree)
    if isinstance(result, float) and math.isnan(result):
        return False
    return bool(result)


# ----------------------------------------------------------------------------------------- node plumbing


def _none() -> None:
    return None


def _constant(value: Any) -> Callable[[], Any]:
    def constant() -> Any:
        return value

    return constant


def _unalias(kwargs: dict[str, Any], aliases: dict[str, str] | None) -> dict[str, Any]:
    if not aliases:
        return dict(kwargs)
    return {aliases.get(k, k): v for k, v in kwargs.items()}


async def _call(fn: Callable[..., Any], **kwargs: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return await fn(**kwargs)
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        return await result
    return result


def _canonical(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, default=str, ensure_ascii=False)


async def _parent_trace(ctx: Any) -> Any:
    future = _PARENT_TRACES.get(ctx.id)
    if future is None:
        if len(_PARENT_TRACES) > 64:
            _PARENT_TRACES.pop(next(iter(_PARENT_TRACES)))
        loader = getattr(ctx, "_get_parent_trace", None)
        if loader is None:
            return None
        future = asyncio.ensure_future(loader())
        _PARENT_TRACES[ctx.id] = future
    try:
        return await asyncio.shield(future)
    except Exception:
        return None


async def _replayed(kwargs: dict[str, Any]) -> Any:
    """Output of this node in the paused run being resumed, when it succeeded there with the same input."""
    ctx = get_run_context()
    if ctx is None or not ctx.parent_id:
        return _MISS
    trace = await _parent_trace(ctx)
    data = getattr(trace, "data", None)
    if not isinstance(data, dict):
        return _MISS
    span = ctx.current_span()
    wanted = _canonical(kwargs)
    for previous in data.values():
        if getattr(previous, "path", None) != span.path:
            continue
        status = getattr(previous, "status", None)
        code = status.get("code") if isinstance(status, dict) else getattr(status, "code", None)
        if code != "success":
            continue
        previous_input = getattr(previous, "input", None)
        if not isinstance(previous_input, dict):
            continue
        if _canonical({k: previous_input.get(k) for k in kwargs}) == wanted:
            span.metadata["studio_replay"] = {"from_run": str(ctx.parent_id)}
            return _plain(getattr(previous, "output", None))
    return _MISS


def _finisher(transform: Callable[[Any], Any] | None) -> Callable[[], None]:
    def finish() -> None:
        ctx = get_run_context()
        if ctx is None:
            return
        span = ctx.current_span()
        if span.call_id in _RESULTS:
            span.output = _RESULTS.pop(span.call_id)
            return
        status = span.status
        if status is None or status.code != "success":
            return
        output = _plain(span.output)
        span.output = transform(output) if transform is not None else output

    return finish


def _signature_handler(fields: list[str], body: Callable[..., Any], *, stream: bool) -> Callable[..., Any]:
    """A handler whose declared parameters are exactly ``fields`` (so other workflow inputs never leak in)."""
    if stream:

        async def stream_handler(**kwargs: Any) -> AsyncIterator[Any]:
            cached = await _replayed(kwargs)
            if cached is not _MISS:
                _RESULTS[get_run_context().current_span().call_id] = cached  # type: ignore[union-attr]
                return
            async for event in body(**kwargs):
                yield event

        handler: Callable[..., Any] = stream_handler
    else:

        async def call_handler(**kwargs: Any) -> Any:
            cached = await _replayed(kwargs)
            if cached is not _MISS:
                _RESULTS[get_run_context().current_span().call_id] = cached  # type: ignore[union-attr]
                return None
            return await body(**kwargs)

        handler = call_handler
    handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
        [inspect.Parameter(f, inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=Any) for f in fields]
    )
    handler.__annotations__ = dict.fromkeys(fields, Any)
    return handler


def _node(
    node_id: str,
    kind: str,
    fields: list[str],
    body: Callable[..., Any],
    *,
    stream: bool = False,
    label: str = "",
    defaults: dict[str, Any] | None = None,
    transform: Callable[[Any], Any] | None = None,
    **tool_kwargs: Any,
) -> Tool:
    """An engine Tool named after the node. Every field gets a runtime default, so a node never consumes the
    workflow's own inputs; ``workflow.py`` binds the fields with ``step(..., field=lambda: render(...))``."""
    static = defaults or {}
    return Tool(
        name=node_id,
        description=label or None,
        handler=_signature_handler(fields, body, stream=stream),
        default_params={f: (_constant(static[f]) if f in static else _none) for f in fields},
        post_hook=_finisher(transform),
        metadata={"messer_node": kind, "label": label},
        **tool_kwargs,
    )


def _approval_policy(base: Any, *, role: str, node_id: str, force: bool) -> Callable[..., Any]:
    async def policy(**kwargs: Any) -> dict[str, Any]:
        required = True if force else base
        if callable(base) and not force:
            required = base(**kwargs)
            if inspect.isawaitable(required):
                required = await required
        if isinstance(required, dict):
            required = bool(required.get("required"))
        return {
            "required": bool(required),
            "kind": "workflow_step",
            "metadata": {"approver_role": role, "node": node_id},
        }

    return policy


def _env(value: str) -> str:
    """``"Bearer $TOKEN"`` → the project secret ``TOKEN`` (secrets live in the sandbox environment)."""
    return _SECRET_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _member(name: str, kind: str) -> Any:
    """Another member of this project (agent or workflow), loaded like the runtime loads it."""
    manifest = _HERE.parent / name / "messer.yaml"
    if not manifest.is_file():
        raise LookupError(f"«{name}» no existe en este proyecto")
    data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    if data.get("_type", "agent") != kind:
        raise LookupError(f"«{name}» no es un {'agente' if kind == 'agent' else 'flujo'}")
    file_part, _, attr = str(data.get("fqn") or f"{kind}.py::{kind}").partition("::")
    if _PACKAGE_ROOT:
        module_name = f"{_PACKAGE_ROOT}.{name}.{Path(file_part).stem}"
    else:  # plain-file mode: every member folder is a package under workforce/
        if str(_HERE.parent) not in sys.path:
            sys.path.insert(0, str(_HERE.parent))
        module_name = f"{name}.{Path(file_part).stem}"
    return getattr(importlib.import_module(module_name), attr or kind)


def sibling(module_file: str, name: str) -> Any:
    """Import ``<name>.py`` next to ``module_file`` when the workflow is loaded as a plain file."""
    path = Path(module_file).resolve().parent / f"{name}.py"
    module_name = f"_messer_{name}_{hashlib.sha256(str(path).encode()).hexdigest()[:12]}"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _make_agent(**kwargs: Any) -> Agent:
    """The model behind an LLM node (tests replace it to use an offline model)."""
    return Agent(**kwargs)


def _json(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw)
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if starts:
        try:
            value, _ = json.JSONDecoder().raw_decode(raw[min(starts) :])
            return value
        except json.JSONDecodeError:
            pass
    raise ValueError("La respuesta del modelo no es JSON válido")


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    if isinstance(value, dict):
        return [{"key": k, "value": v} for k, v in value.items()]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [line for line in value.splitlines() if line.strip()]
        return _as_list(parsed) if isinstance(parsed, list | dict) else [parsed]
    return [value]


# ------------------------------------------------------------------------------------------------- nodes

_INPUT_TYPES: dict[str, Any] = {"string": str, "number": float, "boolean": bool, "object": dict[str, Any] | list[Any]}


def start(
    node_id: str, *, fields: dict[str, str] | None = None, required: list[str] | None = None, label: str = ""
) -> Tool:
    """Input node: the workflow's inputs (plus ``event``, the payload of the trigger that started the run)."""
    declared = dict(fields or {})
    mandatory = [f for f in declared if f in set(required or [])]
    params = [
        inspect.Parameter(f, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=_INPUT_TYPES.get(declared[f], Any))
        for f in mandatory
    ]
    params.append(
        inspect.Parameter("event", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=None, annotation=dict | None)
    )
    params += [
        inspect.Parameter(
            f,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=None,
            annotation=_INPUT_TYPES.get(declared[f], Any) | None,
        )
        for f in declared
        if f not in mandatory
    ]

    async def entry(**kwargs: Any) -> dict[str, Any]:
        return {**{f: kwargs.get(f) for f in declared}, "event": kwargs.get("event") or {}}

    entry.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    entry.__annotations__ = {p.name: p.annotation for p in params}
    return Tool(
        name=node_id, description=label or None, handler=entry, metadata={"messer_node": "input", "label": label}
    )


def agent(node_id: str, *, member: str, label: str = "") -> Tool:
    """Agent node: another agent of the project, called with a prompt (its tools and approvals included)."""

    async def run(prompt: Any = None) -> AsyncIterator[Any]:
        target = _member(member, "agent")
        async for event in target(prompt=_to_text(prompt)):
            yield event

    return _node(node_id, "agent", ["prompt"], run, stream=True, label=label)


def llm(
    node_id: str,
    *,
    model: str,
    system: str = "",
    json_output: bool = False,
    max_tokens: int = 1024,
    temperature: float | None = None,
    label: str = "",
) -> Tool:
    """LLM node: one model call with a prompt template; optionally parses the answer as JSON."""
    options: dict[str, Any] = {"temperature": temperature} if temperature is not None else {}
    model_agent = _make_agent(
        name=f"{node_id}_llm",
        model=model,
        system_prompt=(system or "Eres un asistente preciso.") + (JSON_INSTRUCTION if json_output else ""),
        max_tokens=max_tokens,
        max_iter=1,
        tools=[],
        **options,
    )

    async def run(prompt: Any = None) -> AsyncIterator[Any]:
        model_agent.nest(get_run_context().current_span().path)  # type: ignore[union-attr]
        async for event in model_agent(prompt=_to_text(prompt)):
            yield event

    return _node(node_id, "llm", ["prompt"], run, stream=True, label=label, transform=_json if json_output else None)


def _builtin(key: str, options: dict[str, Any]) -> Tool:
    if key == "knowledge_search":
        return platform_tools.knowledge_search(list(options.get("kb_ids") or []))
    if key == "sql_query":
        return platform_tools.sql_query(str(options.get("kb_id") or ""))
    if key == "send_email":
        return platform_tools.send_email()
    if key == "read_url":
        return platform_tools.read_url(allowed_hosts=options.get("allowed_hosts") or None)
    if key == "http_request":
        return platform_tools.http_request(allowed_hosts=options.get("allowed_hosts") or None)
    if key == "calculator":
        return platform_tools.calculator()
    if key == "current_datetime":
        return platform_tools.current_datetime(timezone=str(options.get("timezone") or "Europe/Madrid"))
    raise ValueError(f"Herramienta no disponible en flujos: {key}")


def tool(
    node_id: str,
    *,
    key: str,
    fields: list[str],
    options: dict[str, Any] | None = None,
    requires_approval: bool = False,
    approver_role: str = "admin",
    label: str = "",
) -> Tool:
    """Tool node: a built-in Messer tool (send email, read URL, calculator…) with its own approval rules."""
    base = _builtin(key, options or {})

    async def run(**kwargs: Any) -> Any:
        return await _call(base.handler, **{k: v for k, v in kwargs.items() if v is not None})

    return _node(
        node_id,
        "tool",
        fields,
        run,
        label=label,
        requires_approval=_approval_policy(
            base.requires_approval, role=approver_role, node_id=node_id, force=requires_approval
        ),
        approval_prompt=base.approval_prompt or f"¿Ejecutar «{label or node_id}»?",
    )


def connector_action(
    node_id: str,
    *,
    connection_id: str,
    action: str,
    fields: list[str],
    aliases: dict[str, str] | None = None,
    requires_approval: bool = False,
    approver_role: str = "admin",
    label: str = "",
) -> Tool:
    """Connector action node: an action of a connected app (send a Gmail message, create a CRM record…)."""
    base = platform_tools.connector_action(connection_id, action, name=node_id)

    async def run(**kwargs: Any) -> Any:
        args = {k: v for k, v in _unalias(kwargs, aliases).items() if v is not None}
        return await base.handler(**args)

    return _node(
        node_id,
        "connector_action",
        fields,
        run,
        label=label,
        requires_approval=_approval_policy(False, role=approver_role, node_id=node_id, force=requires_approval),
        approval_prompt=f"¿Ejecutar la acción {action} ({label or node_id})?",
    )


def knowledge_search(node_id: str, *, kb_ids: list[str], k: int = 5, mode: str = "hybrid", label: str = "") -> Tool:
    """Knowledge search node: hybrid/vector/keyword search over knowledge bases, with sources."""
    base = platform_tools.knowledge_search(list(kb_ids), name=node_id, k=k, mode=mode)  # type: ignore[arg-type]

    async def run(query: Any = None) -> Any:
        return await base.handler(query=_to_text(query), top_k=k)

    return _node(node_id, "knowledge_search", ["query"], run, label=label)


def sql_query(node_id: str, *, kb_id: str, sql: str, label: str = "") -> Tool:
    """SQL node: one read-only SELECT over a knowledge base's tables; bindings go in ``$1, $2…`` parameters."""
    base = platform_tools.sql_query(kb_id, name=node_id)

    async def run(sql: Any = None, params: Any = None) -> Any:
        return await base.handler(sql=str(sql or ""), params=_as_list(params))

    return _node(node_id, "sql_query", ["sql", "params"], run, label=label, defaults={"sql": sql})


def http_request(
    node_id: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    allowed_hosts: list[str] | None = None,
    approver_role: str = "admin",
    label: str = "",
) -> Tool:
    """HTTP node: a request to an external API. Any method other than GET waits for a human approval."""
    base = platform_tools.http_request(
        allowed_hosts=allowed_hosts or None, headers={k: _env(v) for k, v in (headers or {}).items()}
    )

    async def run(method: Any = None, url: Any = None, body: Any = None, query: Any = None) -> Any:
        return await base.handler(
            method=str(method or "GET").upper(), url=_to_text(url), body=body, query=query or None
        )

    return _node(
        node_id,
        "http_request",
        ["method", "url", "body", "query"],
        run,
        label=label,
        defaults={"method": method.upper()},
        requires_approval=_approval_policy(base.requires_approval, role=approver_role, node_id=node_id, force=False),
        approval_prompt=base.approval_prompt,
    )


def condition(node_id: str, *, label: str = "") -> Tool:
    """Condition node: evaluates a safe expression over bound values; outgoing edges are true/false branches."""

    async def run(expression: Any = None) -> bool:
        bound = expression if isinstance(expression, dict) else {"expression": str(expression or ""), "values": {}}
        return evaluate(str(bound.get("expression") or ""), dict(bound.get("values") or {}))

    return _node(node_id, "condition", ["expression"], run, label=label)


def loop(
    node_id: str,
    *,
    body: Tool,
    body_inputs: dict[str, Any],
    mode: str = "foreach",
    count: int = 1,
    max_items: int = 100,
    label: str = "",
) -> Tool:
    """Loop node: runs its body node once per item of a list (or ``count`` times) and returns every result."""
    limit = max(1, min(int(max_items), MAX_LOOP_ITEMS))

    async def run(items: Any = None, context: Any = None) -> AsyncIterator[Any]:
        ctx = get_run_context()
        assert ctx is not None
        span = ctx.current_span()
        body.nest(span.path)
        sequence = list(range(max(1, int(count)))) if mode == "count" else _as_list(items)
        if len(sequence) > limit:
            raise ValueError(f"La lista tiene {len(sequence)} elementos y el máximo del bucle es {limit}")
        values = dict(context or {})
        results: list[Any] = []
        for index, item in enumerate(sequence):
            frame = LoopFrame(item=item, index=index)
            args = {f: _render(t, {node_id: frame}, values) for f, t in body_inputs.items()}
            final: OutputEvent | None = None
            async for event in body(**args):
                yield event
                if isinstance(event, OutputEvent) and event.path == body._path:
                    final = event
            if final is None or final.status.code != "success":
                return  # paused for an approval or failed: the body's final event decides this node's status
            results.append(_plain(final.output))
        _RESULTS[span.call_id] = results

    return _node(node_id, "loop", ["items", "context"], run, stream=True, label=label)


def transform(node_id: str, *, label: str = "") -> Tool:
    """Transform node: builds a value (text or JSON) from bindings, without running code."""

    async def run(value: Any = None) -> Any:
        return value

    return _node(node_id, "transform", ["value"], run, label=label)


def approval(
    node_id: str,
    *,
    fields: list[str],
    aliases: dict[str, str] | None = None,
    prompt: str = "",
    description: str = "",
    approver_role: str = "admin",
    input_node: str | None = None,
    label: str = "",
) -> Tool:
    """Human approval node: the run pauses until someone with ``approver_role`` approves the payload (they may
    correct its values). A denial ends the run."""

    def gate_prompt(**_: Any) -> str:
        ctx = get_run_context()
        scopes: dict[str, Any] = {}
        if ctx is not None:
            for path in placeholders(prompt):
                root = path.split(".", 1)[0]
                if root in ("input", "event"):
                    scopes["input"] = ctx.step_span(input_node, None) if input_node else None
                elif root not in scopes:
                    scopes[root] = ctx.step_span(root, None)
        text = _to_text(_render(prompt, scopes, None)).strip()
        return text or f"¿Aprobar «{label or node_id}»?"

    async def policy(**_: Any) -> dict[str, Any]:
        return {
            "required": True,
            "kind": "workflow_approval",
            "grantable": False,
            "metadata": {"approver_role": approver_role, "node": node_id},
        }

    async def run(**kwargs: Any) -> dict[str, Any]:
        return _unalias(kwargs, aliases)

    return _node(
        node_id,
        "approval",
        fields,
        run,
        label=label,
        requires_approval=policy,
        approval_prompt=gate_prompt,
        approval_description=description or None,
    )


def wait(node_id: str, *, seconds: float, label: str = "") -> Tool:
    """Wait node: pauses the run for some seconds (at most ``MAX_WAIT_SECONDS``)."""

    async def run(seconds: Any = None) -> dict[str, Any]:
        delay = max(0.0, min(float(seconds or 0), float(MAX_WAIT_SECONDS)))
        await asyncio.sleep(delay)
        return {"waited_s": delay}

    return _node(node_id, "wait", ["seconds"], run, label=label, defaults={"seconds": seconds})


def sub_workflow(
    node_id: str, *, workflow: str, fields: list[str], aliases: dict[str, str] | None = None, label: str = ""
) -> Tool:
    """Sub-workflow node: runs another workflow of the project with the given inputs."""

    async def run(**kwargs: Any) -> AsyncIterator[Any]:
        depth = _DEPTH.get()
        if depth >= MAX_SUB_WORKFLOW_DEPTH:
            raise RecursionError(f"Demasiados subflujos anidados (máximo {MAX_SUB_WORKFLOW_DEPTH})")
        target = _member(workflow, "workflow")
        token = _DEPTH.set(depth + 1)
        try:
            async for event in target(**_unalias(kwargs, aliases)):
                yield event
        finally:
            _DEPTH.reset(token)

    return _node(node_id, "sub_workflow", fields, run, stream=True, label=label)


def custom(
    node_id: str,
    function: Callable[..., Any],
    *,
    fields: list[str],
    aliases: dict[str, str] | None = None,
    requires_approval: bool = False,
    approver_role: str = "admin",
    label: str = "",
) -> Tool:
    """Custom node: a function of ``nodes.py`` (sync functions run in a worker thread)."""

    async def run(**kwargs: Any) -> Any:
        args = _unalias(kwargs, aliases)
        if inspect.iscoroutinefunction(function):
            return await function(**args)
        return await asyncio.to_thread(function, **args)

    return _node(
        node_id,
        "custom",
        fields,
        run,
        label=label,
        requires_approval=_approval_policy(False, role=approver_role, node_id=node_id, force=requires_approval),
        approval_prompt=f"¿Ejecutar «{label or node_id}»?",
    )


def output(node_id: str, *, label: str = "") -> Tool:
    """Output node: what the workflow returns."""

    async def run(value: Any = None) -> Any:
        return value

    return _node(node_id, "output", ["value"], run, label=label)
