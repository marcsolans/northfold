from __future__ import annotations

import base64
from pathlib import Path

import pytest

from messer_connector_agent.config import AgentState, ConfigError, load_state, parse_config, save_state
from messer_connector_agent.handlers import AgentError, dispatch


def test_config_parsing_and_env_dsn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ERP_DSN", "postgresql://reader:x@10.0.0.5/erp")
    config = parse_config(
        {"sources": {"erp": {"type": "postgresql", "dsn_env": "ERP_DSN"}}, "paths": [str(tmp_path)], "max_file_mb": 5}
    )
    assert config.sources["erp"].dsn.endswith("/erp")
    assert config.describe() == {"sources": [{"name": "erp", "type": "postgresql"}], "paths": [str(tmp_path.resolve())]}
    assert "reader:x" not in repr(config.sources["erp"])  # the DSN is never printed
    with pytest.raises(ConfigError):
        parse_config({"sources": {"x": {"type": "oracle", "dsn": "y"}}})
    with pytest.raises(ConfigError):
        parse_config({"sources": {"x": {"type": "mysql", "dsn_env": "MISSING_VAR_FOR_TEST"}}})


def test_state_is_private_and_ws_url(tmp_path: Path) -> None:
    path = save_state(
        AgentState(api="https://app.messer.example", agent_id="a1", agent_secret="s3"), tmp_path / "c.json"
    )
    assert path.stat().st_mode & 0o777 == 0o600
    state = load_state(path)
    assert state is not None and state.ws_url == "wss://app.messer.example/api/v1/connector-agents/connect"
    assert AgentState(api="http://localhost:8000/", agent_id="a", agent_secret="s").ws_url == (
        "ws://localhost:8000/api/v1/connector-agents/connect"
    )


async def test_file_access_is_confined_to_configured_paths(tmp_path: Path) -> None:
    allowed = tmp_path / "docs"
    allowed.mkdir()
    (allowed / "a.txt").write_text("hola", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("no", encoding="utf-8")
    (allowed / "link.txt").symlink_to(tmp_path / "outside.txt")
    config = parse_config({"paths": [str(allowed)], "max_file_mb": 1})

    listing = await dispatch(config, "files.list", {"path": str(allowed), "recursive": True})
    assert [e["name"] for e in listing["entries"]] == ["a.txt"]  # the symlink escaping the root is skipped
    read = await dispatch(config, "files.read", {"path": str(allowed / "a.txt")})
    assert base64.b64decode(read["data_b64"]) == b"hola" and read["mime"] == "text/plain"
    for target in (tmp_path / "outside.txt", allowed / "link.txt", allowed / ".." / "outside.txt"):
        with pytest.raises(AgentError) as exc:
            await dispatch(config, "files.read", {"path": str(target)})
        assert exc.value.code == "path_not_allowed"
    with pytest.raises(AgentError):
        await dispatch(config, "sql.query", {"source": "missing", "sql": "select 1"})
    with pytest.raises(AgentError):
        await dispatch(config, "shell.exec", {})
