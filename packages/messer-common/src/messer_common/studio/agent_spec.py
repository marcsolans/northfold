"""Agent configuration edited by the Studio, and its two-way mapping to ``agent.py``.

``render_agent_code(config)`` generates plain engine code (``from messer import Agent``) so a project is
always exportable. ``parse_agent_code(code)`` statically parses an ``agent.py`` (no execution) back into a
config when the file only uses literals and the known Messer tool factories; otherwise it returns ``None`` and
the Studio switches the member to *code mode* (code wins).
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from ..models_config import TIERS, resolve_model

BuiltinToolKey = Literal[
    "knowledge_search",
    "sql_query",
    "read_url",
    "web_search",
    "calculator",
    "current_datetime",
    "http_request",
    "send_email",
]

BUILTIN_TOOLS: dict[str, dict[str, Any]] = {
    "knowledge_search": {"label": "Búsqueda en conocimiento", "side_effect": False},
    "sql_query": {"label": "Consulta SQL (solo lectura)", "side_effect": False},
    "read_url": {"label": "Leer URL", "side_effect": False},
    "web_search": {"label": "Búsqueda web", "side_effect": False},
    "calculator": {"label": "Calculadora", "side_effect": False},
    "current_datetime": {"label": "Fecha y hora", "side_effect": False},
    "http_request": {"label": "Petición HTTP", "side_effect": True},
    "send_email": {"label": "Enviar email", "side_effect": True},
}

_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class ToolConfig(BaseModel):
    type: Literal["builtin", "connector", "custom"]
    key: str  # builtin key | connector action | custom function name in tools.py
    name: str | None = None
    connection_id: str | None = None
    description: str = ""
    input_schema: dict[str, Any] | None = None
    requires_approval: bool = False
    approver_role: Literal["owner", "admin", "builder", "viewer"] = "admin"
    config: dict[str, Any] = Field(default_factory=dict)


class GuardrailConfig(BaseModel):
    type: Literal["pii", "secrets", "injection", "topics", "judge"]
    mode: Literal["shadow", "enforce"] = "enforce"
    topics: list[str] = Field(default_factory=list)
    rubric: str = ""


class MemoryConfig(BaseModel):
    enabled: bool = True
    compaction: Literal["none", "tool_results", "last_turns", "summarize"] = "tool_results"
    keep_last_n: int = 20


class VoiceConfig(BaseModel):
    enabled: bool = False
    voice: str = ""
    language: str = "es"
    greeting: str = ""


class PromptVariable(BaseModel):
    name: str
    description: str = ""
    default: str = ""


class ContextFile(BaseModel):
    """A file stored next to the agent (``workforce/<name>/context/<name>``) whose text joins the system prompt."""

    name: str
    mime: str = "application/octet-stream"
    size: int = 0


class McpServerConfig(BaseModel):
    """Remote MCP server (streamable HTTP). Header values may reference project secrets as ``$SECRET_NAME``."""

    name: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    approval: Literal["none", "destructive", "all"] = "destructive"

    @field_validator("name")
    @classmethod
    def _valid_server_name(cls, v: str) -> str:
        if not _IDENT.match(v):
            raise ValueError("El nombre del servidor MCP debe usar minúsculas, números y guiones bajos")
        return v

    @field_validator("url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("La URL del servidor MCP debe empezar por https://")
        return v


class AgentConfig(BaseModel):
    name: str
    description: str = ""
    model_tier: Literal["fast", "standard", "powerful"] | None = "standard"
    model: str | None = None  # explicit provider/model overrides the tier
    system_prompt: str = ""
    variables: list[PromptVariable] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int = 4096
    max_iter: int = 10
    timeout: int | None = 120
    tools: list[ToolConfig] = Field(default_factory=list)
    knowledge_bases: list[str] = Field(default_factory=list)
    context_files: list[ContextFile] = Field(default_factory=list)
    mcp_servers: list[McpServerConfig] = Field(default_factory=list)
    guardrails: list[GuardrailConfig] = Field(default_factory=list)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, v: str) -> str:
        if not _IDENT.match(v):
            raise ValueError("El nombre debe usar minúsculas, números y guiones bajos, empezando por letra")
        return v

    def resolved_model(self) -> str:
        return resolve_model(self.model or self.model_tier or "standard")


def default_agent_config(name: str, description: str = "") -> AgentConfig:
    return AgentConfig(
        name=name,
        description=description,
        system_prompt="Eres un asistente útil y preciso. Responde en el idioma del usuario.",
        tools=[ToolConfig(type="builtin", key="current_datetime")],
        guardrails=[GuardrailConfig(type="injection", mode="enforce"), GuardrailConfig(type="pii", mode="shadow")],
    )


# ------------------------------------------------------------------------------------------- render


def _py(value: Any) -> str:
    """Python literal for JSON-compatible values (stable, readable)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_py(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_py(str(k))}: {_py(v)}" for k, v in value.items()) + "}"
    raise TypeError(f"unsupported literal {type(value)}")


_SELF_GATED = {"send_email", "http_request"}  # factories that already gate side effects


def _render_tool(tool: ToolConfig, config: AgentConfig) -> str:
    expr = _render_tool_expr(tool, config)
    if tool.requires_approval and tool.type != "connector" and tool.key not in _SELF_GATED:
        return f"require_approval({expr})"
    return expr


_SECRET_REF = re.compile(r"\$([A-Z][A-Z0-9_]*)")


def _render_header_value(value: str) -> str:
    """``"Bearer $TOKEN"`` → ``"Bearer " + os.environ.get("TOKEN", "")`` (secrets live in the sandbox env)."""
    parts: list[str] = []
    pos = 0
    for m in _SECRET_REF.finditer(value):
        if m.start() > pos:
            parts.append(_py(value[pos : m.start()]))
        parts.append(f'os.environ.get({_py(m.group(1))}, "")')
        pos = m.end()
    if pos < len(value):
        parts.append(_py(value[pos:]))
    return " + ".join(parts) if parts else '""'


def _render_mcp(server: McpServerConfig) -> str:
    headers = "{" + ", ".join(f"{_py(k)}: {_render_header_value(v)}" for k, v in server.headers.items()) + "}"
    args = [f"name={_py(server.name)}", 'transport="http"', f"url={_py(server.url)}"]
    if server.headers:
        args.append(f"headers={headers}")
    if server.approval != "none":
        args.append(f"approval={_py(server.approval)}")
    return f"MCPServer({', '.join(args)})"


def _render_tool_expr(tool: ToolConfig, config: AgentConfig) -> str:
    if tool.type == "builtin":
        if tool.key == "knowledge_search":
            return f"knowledge_search(kb_ids={_py(config.knowledge_bases)})"
        if tool.key == "sql_query":
            kb = tool.config.get("kb_id") or (config.knowledge_bases[0] if config.knowledge_bases else "")
            return f"sql_query(kb_id={_py(kb)})"
        if tool.key == "send_email":
            return f"send_email(requires_approval={_py(tool.requires_approval or True)})"
        if tool.key in ("read_url", "http_request"):
            hosts = tool.config.get("allowed_hosts")
            return f"{tool.key}(allowed_hosts={_py(hosts)})" if hosts else f"{tool.key}()"
        if tool.key == "current_datetime":
            tz = tool.config.get("timezone")
            return f"current_datetime(timezone={_py(tz)})" if tz else "current_datetime()"
        return f"{tool.key}()"
    if tool.type == "connector":
        args = [
            _py(tool.connection_id or ""),
            _py(tool.key),
            f"name={_py(tool.name or re.sub(r'[^a-zA-Z0-9_]', '_', tool.key))}",
            f"description={_py(tool.description)}",
            f"input_schema={_py(tool.input_schema or {'type': 'object', 'properties': {}})}",
            f"requires_approval={_py(tool.requires_approval)}",
        ]
        return f"connector_action({', '.join(args)})"
    # custom: a function defined in tools.py next to agent.py
    return f"custom_tools.{tool.key}"


def _render_guardrails(config: AgentConfig) -> str:
    """Each rail is rendered as an object so shadow/enforce is per rail."""
    specs: list[str] = []
    for g in config.guardrails:
        shadow = f"shadow={_py(g.mode == 'shadow')}"
        if g.type == "pii":
            specs.append(f'DetectPII(on_input="redact", on_output="redact", {shadow})')
        elif g.type == "secrets":
            specs.append(f"RedactSecrets({shadow})")
        elif g.type == "injection":
            specs.append(f"PromptInjection({shadow})")
        elif g.type == "topics" and g.topics:
            specs.append(f"TopicGuard(deny={_py(g.topics)}, {shadow})")
        elif g.type == "judge" and g.rubric:
            specs.append(f'LLMJudge({_py(g.rubric)}, model={_py(resolve_model("fast"))}, action="retry", {shadow})')
    return "[" + ", ".join(specs) + "]"


def _render_compaction(memory: MemoryConfig) -> str | None:
    if not memory.enabled or memory.compaction == "none":
        return None
    if memory.compaction == "tool_results":
        return "compact_tool_results()"
    if memory.compaction == "last_turns":
        return f"keep_last_n_turns({int(memory.keep_last_n)})"
    return f"summarize(threshold=60000, model={_py(resolve_model('fast'))})"


def render_agent_code(config: AgentConfig, *, has_custom_tools: bool = False) -> str:
    builtin_keys = sorted({t.key for t in config.tools if t.type == "builtin"})
    factories = [k for k in builtin_keys if k in BUILTIN_TOOLS]
    if any(t.type == "connector" for t in config.tools):
        factories.append("connector_action")
    imports = ["from messer import Agent"]
    guardrails_expr = _render_guardrails(config)
    guard_imports = [
        n
        for n in ("DetectPII", "LLMJudge", "PromptInjection", "RedactSecrets", "TopicGuard")
        if f"{n}(" in guardrails_expr
    ]
    if guard_imports:
        imports.append(f"from messer.guardrails import {', '.join(guard_imports)}")
    compaction = _render_compaction(config.memory)
    if compaction:
        imports.append(f"from messer.core.memory_compaction import {compaction.split('(')[0]}")
    if any(t.requires_approval and t.type != "connector" and t.key not in _SELF_GATED for t in config.tools):
        factories.append("require_approval")
    if config.context_files:
        factories.append("context_prompt")
    if config.mcp_servers:
        imports.append("from messer.core import MCPServer")
        if any(_SECRET_REF.search(v) for srv in config.mcp_servers for v in srv.headers.values()):
            imports.insert(0, "import os\n")
    if factories:
        imports.append(f"from messer.platform.tools import {', '.join(sorted(set(factories)))}")
    if has_custom_tools or any(t.type == "custom" for t in config.tools):
        imports.append("from . import tools as custom_tools")

    tools = ",\n        ".join(
        [_render_tool(t, config) for t in config.tools] + [_render_mcp(m) for m in config.mcp_servers]
    )
    kwargs = [
        f"name={_py(config.name)}",
        f"description={_py(config.description)}",
        f"model={_py(config.resolved_model())}",
        "system_prompt=SYSTEM_PROMPT + CONTEXT" if config.context_files else "system_prompt=SYSTEM_PROMPT",
        f"max_tokens={int(config.max_tokens)}",
        f"max_iter={int(config.max_iter)}",
    ]
    if config.temperature is not None:
        kwargs.append(f"temperature={float(config.temperature)!r}")
    if config.timeout:
        kwargs.append(f"timeout={int(config.timeout)}")
    kwargs.append(f"tools=[\n        {tools},\n    ]" if tools else "tools=[]")
    if config.guardrails:
        kwargs.append(f"guardrails={guardrails_expr}")
    if compaction:
        kwargs.append(f"memory_compaction={compaction}")

    studio_meta = {
        "model_tier": config.model_tier if not config.model else None,
        "variables": [v.model_dump() for v in config.variables],
        "tools": [t.model_dump(exclude_none=True) for t in config.tools],
        "knowledge_bases": config.knowledge_bases,
        "context_files": [c.model_dump() for c in config.context_files],
        "mcp_servers": [m.model_dump() for m in config.mcp_servers],
        "guardrails": [g.model_dump() for g in config.guardrails],
        "memory": config.memory.model_dump(),
        "voice": config.voice.model_dump(),
    }
    body = ",\n    ".join(kwargs)
    return (
        f'"""{config.name} — generated by Messer Studio. Edit freely: the Studio keeps code and configuration in sync\n'
        'when the code only uses the patterns below; otherwise the code is the source of truth."""\n\n'
        + "\n".join(imports)
        + "\n\n"
        + f"SYSTEM_PROMPT = {_py(config.system_prompt)}\n\n"
        + (
            f"CONTEXT = context_prompt(__file__, {_py([c.name for c in config.context_files])})\n\n"
            if config.context_files
            else ""
        )
        + f"STUDIO = {_py(studio_meta)}\n\n"
        + f"agent = Agent(\n    {body},\n)\n"
    )


# ------------------------------------------------------------------------------------------- parse


class _Unparseable(Exception):
    pass


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError) as exc:
        raise _Unparseable(ast.dump(node)[:80]) from exc


def parse_agent_code(code: str) -> AgentConfig | None:
    """Map an ``agent.py`` back to a config without executing it. ``None`` = code mode."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    assigns: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            assigns[stmt.targets[0].id] = stmt.value
        elif isinstance(stmt, ast.Import | ast.ImportFrom | ast.Expr):
            continue
        else:
            return None  # functions, classes or logic in the module → code mode
    call = assigns.get("agent")
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "Agent":
        return None
    try:
        kw = {k.arg: k.value for k in call.keywords if k.arg}
        prompt_node = kw.get("system_prompt")
        if isinstance(prompt_node, ast.BinOp) and isinstance(prompt_node.op, ast.Add):
            prompt_node = prompt_node.left  # SYSTEM_PROMPT + CONTEXT
        if isinstance(prompt_node, ast.Name):
            prompt_node = assigns.get(prompt_node.id)
        system_prompt = _literal(prompt_node) if prompt_node is not None else ""
        studio = _literal(assigns["STUDIO"]) if "STUDIO" in assigns else {}
        model = _literal(kw["model"]) if "model" in kw else None
        tier = studio.get("model_tier")
        if tier in TIERS and model == resolve_model(tier):
            model = None
        # Tools must match the STUDIO metadata one-to-one (same count and factory names).
        tools_node = kw.get("tools")
        tool_calls = tools_node.elts if isinstance(tools_node, ast.List) else []
        studio_tools = [ToolConfig.model_validate(t) for t in studio.get("tools", [])]
        studio_mcp = [McpServerConfig.model_validate(m) for m in studio.get("mcp_servers", [])]
        if len(tool_calls) != len(studio_tools) + len(studio_mcp):
            return None
        for node, mcp in zip(tool_calls[len(studio_tools) :], studio_mcp, strict=True):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "MCPServer"):
                return None
            url_kw = next((k.value for k in node.keywords if k.arg == "url"), None)
            if url_kw is None or _literal(url_kw) != mcp.url:
                return None
        for node, cfg in zip(tool_calls[: len(studio_tools)], studio_tools, strict=True):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "require_approval"
                and node.args
            ):
                if not cfg.requires_approval:
                    return None
                node = node.args[0]
            if cfg.type == "custom":
                if not (isinstance(node, ast.Attribute) and node.attr == cfg.key):
                    return None
                continue
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                return None
            expected = cfg.key if cfg.type == "builtin" else "connector_action"
            if node.func.id != expected:
                return None
        config = AgentConfig(
            name=_literal(kw["name"]),
            description=_literal(kw["description"]) if "description" in kw else "",
            model_tier=tier if tier in TIERS else None,
            model=model,
            system_prompt=system_prompt,
            variables=studio.get("variables", []),
            temperature=_literal(kw["temperature"]) if "temperature" in kw else None,
            max_tokens=_literal(kw["max_tokens"]) if "max_tokens" in kw else 4096,
            max_iter=_literal(kw["max_iter"]) if "max_iter" in kw else 10,
            timeout=_literal(kw["timeout"]) if "timeout" in kw else None,
            tools=studio_tools,
            knowledge_bases=studio.get("knowledge_bases", []),
            context_files=studio.get("context_files", []),
            mcp_servers=studio_mcp,
            guardrails=studio.get("guardrails", []),
            memory=studio.get("memory", {}),
            voice=studio.get("voice", {}),
        )
    except (_Unparseable, KeyError, ValueError, TypeError):
        return None
    return config
