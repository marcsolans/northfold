"""Run the MCP server: ``python -m messer_mcp`` (streamable HTTP on ``MESSER_MCP_HOST:MESSER_MCP_PORT``, /mcp)."""

from __future__ import annotations

import argparse
import os

from messer_common.logging import configure_logging

from .config import McpConfig


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Messer MCP server (streamable HTTP).")
    parser.add_argument("--host", default=None, help="Bind address (default MESSER_MCP_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default MESSER_MCP_PORT or 8400)")
    args = parser.parse_args(argv)
    configure_logging("mcp")
    config = McpConfig.from_env()
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    import uvicorn

    from .server import create_app

    uvicorn.run(
        create_app(config),
        host=config.host,
        port=config.port,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    main()
