"""Studio config ↔ agent.py: generated code is plain engine code, parses back, and runs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from messer_common.studio.agent_spec import (
    AgentConfig,
    ContextFile,
    GuardrailConfig,
    McpServerConfig,
    ToolConfig,
    default_agent_config,
    parse_agent_code,
    render_agent_code,
)


def _full_config() -> AgentConfig:
    cfg = default_agent_config("facturas", "Atiende dudas de facturación")
    cfg.system_prompt = "Eres el asistente de {{empresa}}."
    cfg.tools = [
        ToolConfig(type="builtin", key="calculator", requires_approval=True, approver_role="builder"),
        ToolConfig(type="builtin", key="send_email", requires_approval=True),
        ToolConfig(type="builtin", key="current_datetime", config={"timezone": "Europe/Madrid"}),
    ]
    cfg.context_files = [ContextFile(name="tarifas.md", mime="text/markdown", size=40)]
    cfg.mcp_servers = [
        McpServerConfig(name="crm", url="https://mcp.example.com/mcp", headers={"Authorization": "Bearer $CRM_TOKEN"})
    ]
    cfg.guardrails = [GuardrailConfig(type="topics", topics=["política"], mode="shadow")]
    return cfg


def test_roundtrip_keeps_every_field() -> None:
    cfg = _full_config()
    code = render_agent_code(cfg)
    assert "require_approval(calculator())" in code
    assert 'os.environ.get("CRM_TOKEN", "")' in code
    assert "system_prompt=SYSTEM_PROMPT + CONTEXT" in code
    parsed = parse_agent_code(code)
    assert parsed is not None
    assert parsed.model_dump() == cfg.model_dump()


def test_hand_written_logic_switches_to_code_mode() -> None:
    code = render_agent_code(_full_config()) + "\n\nif True:\n    pass\n"
    assert parse_agent_code(code) is None


def test_generated_code_imports_and_builds_the_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _full_config()
    member = tmp_path / "facturas"
    (member / "context").mkdir(parents=True)
    (member / "context" / "tarifas.md").write_text("Tarifa plana: 49 €/mes", encoding="utf-8")
    (member / "agent.py").write_text(render_agent_code(cfg), encoding="utf-8")
    monkeypatch.setenv("CRM_TOKEN", "secret-token")
    spec = importlib.util.spec_from_file_location("facturas_agent", member / "agent.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["facturas_agent"] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop("facturas_agent", None)
    assert "Tarifa plana: 49 €/mes" in module.CONTEXT
    agent = module.agent
    assert agent.name == "facturas"
    names = [getattr(t, "name", None) for t in agent.tools]
    assert "calculator" in names and "send_email" in names
    calc = next(t for t in agent.tools if getattr(t, "name", None) == "calculator")
    assert calc.requires_approval is True


def test_custom_tools_load_as_package_and_plain_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = default_agent_config("abonos", "Emite abonos")
    cfg.tools = [ToolConfig(type="custom", key="emitir_abono", requires_approval=True)]
    code = render_agent_code(cfg, has_custom_tools=True)
    parsed = parse_agent_code(code)
    assert parsed is not None and parsed.model_dump() == cfg.model_dump()
    member = tmp_path / "workforce" / "abonos"
    member.mkdir(parents=True)
    (tmp_path / "workforce" / "__init__.py").write_text("", encoding="utf-8")
    (member / "__init__.py").write_text("", encoding="utf-8")
    (member / "agent.py").write_text(code, encoding="utf-8")
    (member / "tools.py").write_text(
        'def emitir_abono(factura: str, importe: float) -> str:\n    """Emite un abono."""\n    return factura\n',
        encoding="utf-8",
    )

    def gated(module: object) -> bool:
        tool = next(t for t in module.agent.tools if getattr(t, "name", None) == "emitir_abono")  # type: ignore[attr-defined]
        return tool.requires_approval is True

    # As a package (the runtime sandbox).
    monkeypatch.syspath_prepend(str(tmp_path))
    package = importlib.import_module("workforce.abonos.agent")
    assert gated(package)
    for name in [m for m in sys.modules if m == "workforce" or m.startswith("workforce.")]:
        sys.modules.pop(name)
    # As a plain file next to tools.py (messer start, flow introspection).
    monkeypatch.syspath_prepend(str(member))
    spec = importlib.util.spec_from_file_location("abonos_agent", member / "agent.py")
    assert spec is not None and spec.loader is not None
    plain = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(plain)
    finally:
        sys.modules.pop("tools", None)
    assert gated(plain)
