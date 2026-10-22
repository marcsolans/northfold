from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest

from messer_connectors import http as chttp
from messer_connectors import registry
from messer_connectors.adapters.webhooks import sign, verify_request
from messer_connectors.base import ConnectionContext, ConnectorAuthError, ConnectorError


def ctx(key: str, config: dict[str, Any], credentials: dict[str, Any] | None = None) -> ConnectionContext:
    adapter = registry.get_adapter(key)
    adapter.validate_config(config, credentials or {})
    config, credentials = adapter.prepare(config, credentials or {})
    return ConnectionContext(
        connection_id=uuid.uuid4(), org_id=uuid.uuid4(), credentials=credentials, config=config, connector_key=key
    )


# ----------------------------------------------------------------------------- webhooks


def test_webhook_hmac_verification() -> None:
    secret = "s3cr3t"
    body = b'{"invoice": "F-2026-0412", "amount": 1284.6}'
    verify_request(secret=secret, mode="hmac", body=body, headers={"X-Messer-Signature": sign(secret, body)}, query={})
    # GitHub-style header and bare hex are accepted too.
    verify_request(secret=secret, mode="hmac", body=body, headers={"X-Hub-Signature-256": sign(secret, body)}, query={})
    with pytest.raises(ConnectorAuthError):
        verify_request(
            secret=secret, mode="hmac", body=body + b" ", headers={"X-Messer-Signature": sign(secret, body)}, query={}
        )
    with pytest.raises(ConnectorAuthError):
        verify_request(secret=secret, mode="hmac", body=body, headers={}, query={})
    with pytest.raises(ConnectorAuthError):
        verify_request(
            secret="other", mode="hmac", body=body, headers={"X-Messer-Signature": sign(secret, body)}, query={}
        )


def test_webhook_timestamped_signature_and_replay_window() -> None:
    secret = "s3cr3t"
    body = b"{}"
    ts = int(time.time())
    headers = {"X-Messer-Signature": sign(secret, body, ts), "X-Messer-Timestamp": str(ts)}
    verify_request(secret=secret, mode="hmac", body=body, headers=headers, query={})
    with pytest.raises(ConnectorAuthError):
        verify_request(secret=secret, mode="hmac", body=body, headers=headers, query={}, now=ts + 3600)


def test_webhook_token_mode_and_secret_generation() -> None:
    c = ctx("webhooks", {"verification": "token"})
    secret = c.credentials["secret"]
    assert len(secret) >= 32
    verify_request(secret=secret, mode="token", body=b"x", headers={"X-Messer-Token": secret}, query={})
    verify_request(secret=secret, mode="token", body=b"x", headers={}, query={"token": secret})
    with pytest.raises(ConnectorAuthError):
        verify_request(secret=secret, mode="token", body=b"x", headers={"X-Messer-Token": "nope"}, query={})


# ----------------------------------------------------------------------------- generic HTTP


async def test_http_get_needs_no_approval_but_other_methods_do() -> None:
    adapter = registry.get_adapter("http")
    assert adapter.action("get").side_effect is False
    assert adapter.action("request").side_effect is True
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"invoices": [{"id": "F-1", "total": 12.5}]})
        return httpx.Response(201, json={"created": json.loads(request.content)})

    c = ctx(
        "http",
        {
            "base_url": "https://erp.example/api/v2",
            "auth_header_name": "X-Api-Key",
            "default_headers": {"Accept-Language": "es"},
        },
        {"auth_header_value": "k-123"},
    )
    assert "auth_header_value" not in c.config
    chttp.set_transport(httpx.MockTransport(handler))
    try:
        res = await adapter.run_action(c, "get", {"path": "/invoices", "query": {"status": "pending"}})
        assert res["status"] == 200 and res["json"]["invoices"][0]["id"] == "F-1"
        assert str(seen[0].url) == "https://erp.example/api/v2/invoices?status=pending"
        assert seen[0].headers["x-api-key"] == "k-123" and seen[0].headers["accept-language"] == "es"
        res = await adapter.run_action(
            c, "request", {"method": "POST", "path": "credit-notes", "json": {"amount": 640}}
        )
        assert res["status"] == 201 and seen[1].method == "POST"
        with pytest.raises(ConnectorError):
            await adapter.run_action(c, "get", {"path": "https://evil.example/steal"})
    finally:
        chttp.set_transport(None)


@pytest.mark.parametrize(
    "host", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.10", "::1", "localhost", "100.64.0.1"]
)
def test_ssrf_guard_blocks_private_targets(host: str) -> None:
    with pytest.raises(ConnectorError):
        chttp.check_public_host(host, allow_private=False)
    chttp.check_public_host(host, allow_private=True)


def test_ssrf_guard_allows_public_addresses() -> None:
    chttp.check_public_host("8.8.8.8", allow_private=False)
    chttp.check_public_host("2001:4860:4860::8888", allow_private=False)


# ----------------------------------------------------------------------------- MCP


MCP_SERVER = '''
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("facturas")


@mcp.tool()
def pending_total(customer: str) -> str:
    """Importe pendiente de un cliente."""
    return f"{customer}: 1284.60 EUR"


@mcp.tool()
def add(a: int, b: int) -> int:
    """Suma dos números."""
    return a + b


if __name__ == "__main__":
    mcp.run()
'''


async def test_mcp_stdio_server_lists_and_calls_tools(tmp_path: Path) -> None:
    script = tmp_path / "server.py"
    script.write_text(MCP_SERVER, encoding="utf-8")
    adapter = registry.get_adapter("mcp")
    c = ctx("mcp", {"transport": "stdio", "command": sys.executable, "args": [str(script)]})
    tools = await adapter.run_action(c, "list_tools", {})
    names = {t["name"] for t in tools}
    assert names == {"pending_total", "add"}
    add = next(t for t in tools if t["name"] == "add")
    assert add["input_schema"]["properties"].keys() == {"a", "b"}
    assert adapter.action("call_tool").side_effect is True
    result = await adapter.run_action(c, "call_tool", {"tool": "pending_total", "arguments": {"customer": "Mendaro"}})
    assert result["result"] == "Mendaro: 1284.60 EUR"
    test = await adapter.test(c)
    assert test.ok and "2 herramientas" in test.message


async def test_mcp_config_validation() -> None:
    adapter = registry.get_adapter("mcp")
    with pytest.raises(ConnectorError):
        adapter.validate_config({"transport": "http", "url": "ftp://x"}, {})
    with pytest.raises(ConnectorError):
        adapter.validate_config({"transport": "stdio"}, {})
    config, creds = adapter.prepare(
        {"transport": "http", "url": "https://mcp.example/mcp", "headers": {"Authorization": "Bearer t"}}, {}
    )
    assert "headers" not in config and creds["headers"] == {"Authorization": "Bearer t"}
