"""The Messer MCP server: tools and resources over the platform API (streamable HTTP at ``/mcp``).

Authentication: ``Authorization: Bearer msr_…`` (an organization API key) or an OAuth 2.1 access token issued by
the platform API (authorization code + PKCE with dynamic client registration). Unauthenticated requests get a
401 whose ``WWW-Authenticate`` header points to the protected resource metadata
(``/.well-known/oauth-protected-resource/mcp``), which names the API as authorization server.

Every tool call is an API request made with the caller's token, so roles, scopes, project-scoped keys, plan limits
and audit apply unchanged.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Literal
from urllib.parse import quote, unquote

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Resource, ToolAnnotations
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from messer_common.logging import get_logger

from .api import ApiClient, MesserApiError
from .auth import ALL_SCOPES, MesserTokenVerifier
from .config import McpConfig

log = get_logger("messer.mcp")

INSTRUCTIONS = """Messer builds, runs and governs AI agents and workflows. Everything is code in one git repository
per project (workforce/<name>/agent.py | workflow.py). Typical flow: list_projects (or create_project) →
create_agent / update_agent → run_evals → deploy (evals gate production) → run_agent (production) →
list_runs / get_run (traces with cost). Agent configuration fields: system_prompt, model_tier (fast | standard |
powerful) or model ("provider/model"), tools (built-in keys such as knowledge_search, sql_query, read_url,
web_search, calculator, current_datetime, http_request, send_email), knowledge_bases, guardrails, memory.
Answers and errors from the platform are in Spanish."""

TERMINAL = ("live", "failed", "rolled_back", "superseded", "cancelled")
MAX_LISTED_RESOURCES = 300
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
CREATE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
UPDATE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False)
RUN = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
DEPLOY = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def _request_token(ctx: Context | None) -> str:  # type: ignore[type-arg]
    """The bearer of the HTTP request carrying this MCP message (verified by the auth middleware)."""
    if ctx is not None:
        try:
            request = ctx.request_context.request
        except ValueError:
            request = None
        if request is not None:
            user = request.scope.get("user")
            if isinstance(user, AuthenticatedUser):
                return user.access_token.token
    token = get_access_token()
    if token is not None:
        return token.token
    raise ToolError("Sin credenciales: conecta el servidor MCP con una API key o OAuth")


def _deep_merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def file_uri(project_id: str, path: str) -> str:
    return f"messer://projects/{project_id}/files/{quote(path, safe='')}"


class MesserMCP(FastMCP):  # type: ignore[type-arg]
    """FastMCP with resources listed dynamically: the files of every project the caller can see."""

    config: McpConfig

    def api(self, ctx: Context | None = None) -> ApiClient:  # type: ignore[type-arg]
        request_id = uuid.uuid4().hex
        return ApiClient(self.config.api_url, _request_token(ctx), request_id=request_id)

    async def list_resources(self) -> list[Resource]:  # type: ignore[override]
        static = await super().list_resources()
        try:
            ctx = self.get_context()
            async with self.api(ctx) as api:
                projects = await api.get("/projects")
                listed: list[Resource] = []
                for project in projects or []:
                    if len(listed) >= MAX_LISTED_RESOURCES:
                        break
                    files = await api.get(f"/projects/{project['id']}/files")
                    for path in (files or {}).get("files", []):
                        if len(listed) >= MAX_LISTED_RESOURCES:
                            break
                        listed.append(
                            Resource(
                                uri=file_uri(project["id"], path),  # type: ignore[arg-type]
                                name=f"{project['name']}/{path}",
                                description=f"Archivo {path} del proyecto «{project['name']}»",
                                mimeType="text/plain",
                            )
                        )
        except (ToolError, MesserApiError) as exc:
            log.info("mcp.list_resources_failed", error=str(exc))
            return static
        return [*static, *listed]


def build_server(config: McpConfig | None = None) -> tuple[MesserMCP, MesserTokenVerifier]:
    cfg = config or McpConfig.from_env()
    verifier = MesserTokenVerifier(cfg.api_url)
    mcp = MesserMCP(
        name="messer",
        instructions=INSTRUCTIONS,
        website_url=f"{cfg.web_url}/docs/mcp",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(cfg.issuer_url),
            resource_server_url=AnyHttpUrl(cfg.resource_url),
            required_scopes=None,
        ),
        host=cfg.host,
        port=cfg.port,
        stateless_http=cfg.stateless,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=cfg.allowed_hosts(),
            allowed_origins=cfg.allowed_origins(),
        ),
    )
    mcp.config = cfg
    _register_tools(mcp)
    _register_resources(mcp)
    return mcp, verifier


# ---------------------------------------------------------------------------------------------- tools


def _register_tools(mcp: MesserMCP) -> None:  # noqa: C901 - one registration block per tool
    @mcp.tool(annotations=READ)
    async def whoami(ctx: Context) -> dict[str, Any]:  # type: ignore[type-arg]
        """Who this connection acts as: organization, role, credential (API key or OAuth app) and scopes."""
        async with mcp.api(ctx) as api:
            return await api.get("/cli/whoami")  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_projects(ctx: Context) -> list[dict[str, Any]]:  # type: ignore[type-arg]
        """List the organization's projects (id, name, number of agents and workflows, runs in 30 days)."""
        async with mcp.api(ctx) as api:
            return await api.get("/projects")  # type: ignore[no-any-return]

    @mcp.tool(annotations=CREATE)
    async def create_project(
        ctx: Context,  # type: ignore[type-arg]
        name: str,
        description: str = "",
        default_model_tier: Literal["fast", "standard", "powerful"] = "standard",
    ) -> dict[str, Any]:
        """Create a project (its own git repository with development and production environments)."""
        async with mcp.api(ctx) as api:
            return await api.post(  # type: ignore[no-any-return]
                "/projects", {"name": name, "description": description, "default_model_tier": default_model_tier}
            )

    @mcp.tool(annotations=READ)
    async def get_project(ctx: Context, project_id: str) -> dict[str, Any]:  # type: ignore[type-arg]
        """A project with its agents and workflows and its environments (deployed version, URL)."""
        async with mcp.api(ctx) as api:
            project = await api.get(f"/projects/{project_id}")
            project["workforce"] = await api.get(f"/projects/{project_id}/workforce")
            project["environments"] = await api.get(f"/projects/{project_id}/environments")
            return project  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_workforce(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        kind: Literal["agent", "workflow"] | None = None,
    ) -> list[dict[str, Any]]:
        """List the agents and workflows of a project."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/workforce", kind=kind)  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def get_agent(ctx: Context, project_id: str, name: str) -> dict[str, Any]:  # type: ignore[type-arg]
        """An agent's Studio configuration, its generated agent.py code, source mode and current version."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/workforce/{name}")  # type: ignore[no-any-return]

    @mcp.tool(annotations=CREATE)
    async def create_agent(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        description: str = "",
        system_prompt: str | None = None,
        model_tier: Literal["fast", "standard", "powerful"] | None = None,
        model: str | None = None,
        tools: list[str] | None = None,
        knowledge_bases: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an agent. ``name``: lowercase letters, digits and _. Optional ``system_prompt``, ``model_tier`` or
        explicit ``model``, built-in ``tools`` keys and ``knowledge_bases`` ids; ``config`` sets any other field of
        the Studio configuration (merged over the defaults)."""
        async with mcp.api(ctx) as api:
            created = await api.post(
                f"/projects/{project_id}/workforce", {"name": name, "description": description}
            )
            changes: dict[str, Any] = dict(config or {})
            if system_prompt is not None:
                changes["system_prompt"] = system_prompt
            if model_tier is not None:
                changes["model_tier"] = model_tier
            if model is not None:
                changes["model"] = model
            if tools is not None:
                changes["tools"] = [{"type": "builtin", "key": key} for key in tools]
            if knowledge_bases is not None:
                changes["knowledge_bases"] = knowledge_bases
            if not changes:
                return created  # type: ignore[no-any-return]
            merged = _deep_merge(created["config"], changes)
            merged["name"] = name
            return await api.put(f"/projects/{project_id}/workforce/{name}/config", merged)  # type: ignore[no-any-return]

    @mcp.tool(annotations=UPDATE)
    async def update_agent(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        changes: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> dict[str, Any]:
        """Update an agent: ``changes`` is merged into its Studio configuration (e.g. {"system_prompt": "…"}), or
        ``code`` replaces agent.py (the configuration follows the code when it can be parsed; otherwise the agent
        switches to code mode). Each change is a commit."""
        if (changes is None) == (code is None):
            raise ToolError("Indica exactamente uno de: changes, code")
        async with mcp.api(ctx) as api:
            if code is not None:
                return await api.put(f"/projects/{project_id}/workforce/{name}/code", {"code": code})  # type: ignore[no-any-return]
            current = await api.get(f"/projects/{project_id}/workforce/{name}")
            merged = _deep_merge(current["config"], changes or {})
            merged["name"] = name
            return await api.put(f"/projects/{project_id}/workforce/{name}/config", merged)  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def get_workflow(ctx: Context, project_id: str, name: str) -> dict[str, Any]:  # type: ignore[type-arg]
        """A workflow's graph (nodes, edges, inputs), its workflow.py code and custom nodes."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/workflows/{name}")  # type: ignore[no-any-return]

    @mcp.tool(annotations=CREATE)
    async def create_workflow(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        description: str = "",
        template: Literal["blank", "approval", "classify"] = "blank",
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a workflow from a template, or from a full graph ``config`` (same shape as get_workflow's)."""
        body: dict[str, Any] = {"name": name, "description": description, "template": template}
        if config is not None:
            body["config"] = config
        async with mcp.api(ctx) as api:
            return await api.post(f"/projects/{project_id}/workflows", body)  # type: ignore[no-any-return]

    @mcp.tool(annotations=UPDATE)
    async def update_workflow(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        config: dict[str, Any] | None = None,
        code: str | None = None,
        message: str | None = None,
    ) -> dict[str, Any]:
        """Replace a workflow's graph ``config`` (validated, regenerates workflow.py) or its ``code``."""
        if (config is None) == (code is None):
            raise ToolError("Indica exactamente uno de: config, code")
        async with mcp.api(ctx) as api:
            if code is not None:
                return await api.put(f"/projects/{project_id}/workflows/{name}/code", {"code": code})  # type: ignore[no-any-return]
            body: dict[str, Any] = {"config": config}
            if message:
                body["message"] = message
            return await api.put(f"/projects/{project_id}/workflows/{name}/graph", body)  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_evals(ctx: Context, project_id: str, name: str, limit: int = 10) -> list[dict[str, Any]]:  # type: ignore[type-arg]
        """Recent eval runs of an agent or workflow (passed, failed, per-case results)."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/workforce/{name}/evals", limit=limit)  # type: ignore[no-any-return]

    @mcp.tool(annotations=RUN)
    async def run_evals(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run the YAML evals (workforce/<name>/evals/*.yaml) of an agent or workflow against its latest code."""
        async with mcp.api(ctx) as api:
            return await api.post(f"/projects/{project_id}/workforce/{name}/evals", {"tags": tags})  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_knowledge_bases(ctx: Context) -> list[dict[str, Any]]:  # type: ignore[type-arg]
        """List the organization's knowledge bases (documents and tables)."""
        async with mcp.api(ctx) as api:
            return await api.get("/knowledge-bases")  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def search_knowledge(
        ctx: Context,  # type: ignore[type-arg]
        kb_id: str,
        query: str,
        mode: Literal["hybrid", "vector", "keyword"] = "hybrid",
        k: int = 8,
    ) -> dict[str, Any]:
        """Search a knowledge base's documents (hybrid = vector + keyword). Hits carry file, page and content."""
        async with mcp.api(ctx) as api:
            return await api.post(f"/knowledge-bases/{kb_id}/search", {"query": query, "mode": mode, "k": k})  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def query_knowledge(
        ctx: Context,  # type: ignore[type-arg]
        kb_id: str,
        sql: str,
        params: list[Any] | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Run a read-only SQL query over a knowledge base's tables (policies and masking apply)."""
        async with mcp.api(ctx) as api:
            return await api.post(  # type: ignore[no-any-return]
                f"/knowledge-bases/{kb_id}/query", {"sql": sql, "params": params or [], "limit": limit}
            )

    @mcp.tool(annotations=RUN)
    async def run_agent(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        name: str,
        prompt: str | None = None,
        input: dict[str, Any] | None = None,
        environment: Literal["production", "development"] = "production",
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Run an agent (``prompt``) or workflow (``input``) through the public run API. ``production`` runs the
        deployed version (deploy first); ``development`` runs the latest code. ``session_id`` keeps memory."""
        body_input = dict(input or {})
        if prompt is not None:
            body_input["prompt"] = prompt
        body: dict[str, Any] = {"input": body_input, "environment": environment}
        if session_id:
            body["session_id"] = session_id
        async with mcp.api(ctx) as api:
            return await api.request(  # type: ignore[no-any-return]
                "POST", f"/v1/projects/{project_id}/workforce/{name}/run", json=body
            )

    @mcp.tool(annotations=DEPLOY)
    async def deploy(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        environment: Literal["production", "development"] = "production",
        message: str = "",
        wait_seconds: int = 120,
    ) -> dict[str, Any]:
        """Deploy the project's latest code. Evals run as a gate; the deployment goes live only if they pass.
        Waits up to ``wait_seconds`` (0 = return at once) and returns the deployment with its logs."""
        async with mcp.api(ctx) as api:
            dep = await api.post(
                f"/projects/{project_id}/deployments", {"environment": environment, "message": message}
            )
            deadline = time.monotonic() + max(0, min(int(wait_seconds), 900))
            seen = 0
            while dep["status"] not in TERMINAL and time.monotonic() < deadline:
                await asyncio.sleep(1.0)
                dep = await api.get(f"/deployments/{dep['id']}")
                logs = dep.get("logs") or []
                for entry in logs[seen:]:
                    await ctx.info(str(entry.get("message", "")))
                seen = len(logs)
            return dep  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def get_deployment(ctx: Context, deployment_id: str) -> dict[str, Any]:  # type: ignore[type-arg]
        """A deployment's status (pending, evaluating, deploying, live, failed…) and logs."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/deployments/{deployment_id}")  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_deployments(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        environment: Literal["production", "development"] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Deployment history of a project."""
        async with mcp.api(ctx) as api:
            return await api.get(  # type: ignore[no-any-return]
                f"/projects/{project_id}/deployments", environment=environment, limit=limit
            )

    @mcp.tool(annotations=READ)
    async def list_runs(
        ctx: Context,  # type: ignore[type-arg]
        project_id: str,
        workforce: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Recent runs of a project (status, channel, environment, cost, duration)."""
        async with mcp.api(ctx) as api:
            return await api.get(  # type: ignore[no-any-return]
                f"/projects/{project_id}/runs", workforce=workforce, status=status, limit=limit
            )

    @mcp.tool(annotations=READ)
    async def get_run(ctx: Context, run_id: str) -> dict[str, Any]:  # type: ignore[type-arg]
        """A run's full trace: input, output, every span (model and tool calls with tokens, cost and latency)."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/runs/{run_id}")  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def list_files(ctx: Context, project_id: str, ref: str = "HEAD") -> dict[str, Any]:  # type: ignore[type-arg]
        """Files of a project's repository at a git ref (also exposed as resources)."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/files", ref=ref)  # type: ignore[no-any-return]

    @mcp.tool(annotations=READ)
    async def read_file(ctx: Context, project_id: str, path: str, ref: str = "HEAD") -> dict[str, Any]:  # type: ignore[type-arg]
        """Content of one file of a project's repository."""
        async with mcp.api(ctx) as api:
            return await api.get(f"/projects/{project_id}/files/content", path=path, ref=ref)  # type: ignore[no-any-return]


# ------------------------------------------------------------------------------------------ resources


def _register_resources(mcp: MesserMCP) -> None:
    @mcp.resource(
        "messer://projects/{project_id}/files/{path}",
        name="project-file",
        description="A file of a project's repository (path percent-encoded, e.g. workforce%2Fsoporte%2Fagent.py).",
        mime_type="text/plain",
    )
    async def project_file(project_id: str, path: str) -> str:
        async with mcp.api(mcp.get_context()) as api:
            data = await api.get(f"/projects/{project_id}/files/content", path=unquote(path))
        return str(data.get("content", ""))

    @mcp.resource(
        "messer://projects/{project_id}",
        name="project",
        description="A project summary: metadata, agents and workflows, environments and file list (JSON).",
        mime_type="application/json",
    )
    async def project_summary(project_id: str) -> str:
        async with mcp.api(mcp.get_context()) as api:
            project = await api.get(f"/projects/{project_id}")
            project["workforce"] = await api.get(f"/projects/{project_id}/workforce")
            project["environments"] = await api.get(f"/projects/{project_id}/environments")
            project["files"] = [
                {"path": p, "uri": file_uri(project_id, p)}
                for p in (await api.get(f"/projects/{project_id}/files")).get("files", [])
            ]
        return json.dumps(project, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------------------------- app


def create_app(config: McpConfig | None = None) -> Starlette:
    """The ASGI app: ``/mcp`` plus OAuth discovery documents and a health check."""
    mcp, _verifier = build_server(config)
    cfg = mcp.config
    app = mcp.streamable_http_app()

    def protected_resource(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "resource": cfg.resource_url,
                "authorization_servers": [cfg.issuer_url],
                "scopes_supported": ALL_SCOPES,
                "bearer_methods_supported": ["header"],
                "resource_name": "Messer",
                "resource_documentation": f"{cfg.web_url}/docs/mcp",
            },
            headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"},
        )

    def authorization_server(_: Request) -> JSONResponse:
        """Mirror of the API's RFC 8414 document for clients that look for it on the MCP server's origin."""
        base = cfg.issuer_url
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/oauth/authorize",
                "token_endpoint": f"{base}/oauth/token",
                "registration_endpoint": f"{base}/oauth/register",
                "revocation_endpoint": f"{base}/oauth/revoke",
                "scopes_supported": ALL_SCOPES,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
                "code_challenge_methods_supported": ["S256"],
            },
            headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"},
        )

    def health(_: Request) -> JSONResponse:
        return JSONResponse({"ok": True, "service": "mcp", "endpoint": cfg.resource_url})

    routes = [
        Route("/.well-known/oauth-protected-resource/mcp", protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource, methods=["GET"]),
        Route("/.well-known/oauth-authorization-server", authorization_server, methods=["GET"]),
        Route("/healthcheck", health, methods=["GET"]),
        Route("/health", health, methods=["GET"]),
    ]
    for route in reversed(routes):
        app.router.routes.insert(0, route)
    app.state.mcp = mcp
    return app
