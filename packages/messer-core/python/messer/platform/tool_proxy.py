"""Platform tool proxy — remote tool execution without exporting credentials."""

import os
from typing import Any

import structlog

from .. import __version__
from ..errors import ToolProxyUnavailable
from ..state import get_call_id, get_or_create_run_context
from .utils import _request

logger = structlog.get_logger("messer.platform.tool_proxy")

_PROXY_PREFIX = "/proxies/v1/tools"


def _subject_header_env_map() -> dict[str, str]:
    """Map x-messer-* header names to MESSER_* env vars (fallback when subject fields are unset)."""
    return {
        "x-messer-app-id": "MESSER_APP_ID",
        "x-messer-project-id": "MESSER_PROJECT_ID",
        "x-messer-rev": "MESSER_REV",
    }


def build_tool_proxy_headers() -> dict[str, str]:
    """Build per-request headers for tool proxy calls (run context + subject + version)."""
    run_context = get_or_create_run_context()
    headers: dict[str, str] = {
        "x-messer-run-id": run_context.id,
        "x-messer-version": __version__,
    }

    # Match the llm router: always attach call_id when the context var is set (tool runs always set it).
    call_id = get_call_id()
    if call_id is not None:
        headers["x-messer-call-id"] = call_id

    platform_config = run_context.platform_config
    if platform_config and platform_config.subject:
        subject = platform_config.subject
        if subject.app_id:
            headers["x-messer-app-id"] = subject.app_id
        if subject.project_id:
            headers["x-messer-project-id"] = subject.project_id
        if subject.rev:
            headers["x-messer-rev"] = subject.rev

    for header_name, env_var in _subject_header_env_map().items():
        if header_name not in headers:
            value = os.getenv(env_var)
            if value:
                headers[header_name] = value

    return headers


def _tool_proxy_path(org_id: str, tool_name: str) -> str:
    return f"orgs/{org_id}{_PROXY_PREFIX}/{tool_name}"


async def execute_tool_proxy(tool_name: str, params: dict[str, Any]) -> Any:
    """Execute a tool via the platform proxy (no credentials in the client runtime).

    POST ``/orgs/{org_id}/proxies/v1/tools/{tool_name}`` with handler params as JSON body.
    Returns the platform's response JSON unchanged: the handler's result sits under
    ``output``, next to ``tool``, ``provider`` and ``version``.
    """
    run_context = get_or_create_run_context()
    platform_config = run_context.platform_config
    if platform_config is None or platform_config.subject is None:
        # The run context may have skipped platform_config resolution (e.g. tracing was
        # explicitly disabled). Resolve it on demand — the proxy needs the org subject.
        # force_refresh bypasses a stale cached default (a default call could have cached
        # None before MESSER_API_KEY / MESSER_ORG_ID were set in this process).
        from ..state.config_loader import resolve_platform_config

        platform_config = resolve_platform_config(platform_config, force_refresh=True)
        run_context.platform_config = platform_config

    if platform_config is None or platform_config.subject is None:
        raise ToolProxyUnavailable(
            "Tool proxy requires platform_config with org subject. Set MESSER_API_KEY and MESSER_ORG_ID."
        )

    org_id = platform_config.subject.org_id
    path = _tool_proxy_path(org_id, tool_name)
    headers = build_tool_proxy_headers()

    logger.debug("tool_proxy_execute", tool=tool_name, path=path)

    response = await _request(
        "POST",
        path,
        headers=headers,
        json=params,
    )
    return response.json()
