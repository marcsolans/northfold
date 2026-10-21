"""Sandbox process: serves one project checkout (one commit) over a Unix socket.

Runs in a child process with a scrubbed environment and resource limits. It imports only the engine
(``messer``) and the web stack — never the platform kernel — so no database or provider credentials are
reachable from project code. Platform access goes through ``MESSER_API_HOST`` (the runtime's internal API)
with a sandbox token scoped to this organization, project and commit.

    python -m messer_runtime.sandbox.server --project-dir /cache/<project>/<commit> --socket /tmp/sbx.sock
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import traceback
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

PROJECT_DIR = Path.cwd()
_runnables: dict[str, Any] = {}
_load_lock = asyncio.Lock()


def _members() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    base = PROJECT_DIR / "workforce"
    if not base.is_dir():
        return found
    for manifest in sorted(base.glob("*/messer.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        found[manifest.parent.name] = {
            "name": manifest.parent.name,
            "type": data.get("_type", "agent"),
            "fqn": data.get("fqn", "agent.py::agent"),
        }
    return found


async def load_runnable(name: str) -> Any:
    if name in _runnables:
        return _runnables[name]
    async with _load_lock:
        if name in _runnables:
            return _runnables[name]
        member = _members().get(name)
        if member is None:
            raise HTTPException(status_code=404, detail=f"workforce member {name!r} not found")
        file_part, _, attr = str(member["fqn"]).partition("::")
        module_name = f"workforce.{name}.{Path(file_part).stem}"
        module = importlib.import_module(module_name)
        runnable = getattr(module, attr or "agent")
        _runnables[name] = runnable
        return runnable


def _event_json(event: Any) -> str:
    if hasattr(event, "model_dump"):
        return json.dumps(event.model_dump(mode="json"), default=str)
    return json.dumps(event, default=str)


app = FastAPI()


@app.get("/healthcheck")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"ok": True, "members": list(_members())})


@app.get("/members")
async def members() -> JSONResponse:
    return JSONResponse(list(_members().values()))


@app.get("/members/{name}/schema")
async def member_schema(name: str) -> JSONResponse:
    runnable = await load_runnable(name)
    return JSONResponse({"params": runnable.params_model_schema, "returns": runnable.return_model_schema})


@app.post("/members/{name}/stream")
async def stream(name: str, request: Request) -> StreamingResponse:
    from messer.state import RunContext, set_run_context

    body = await request.json()
    try:
        runnable = await load_runnable(name)
    except HTTPException:
        raise
    except Exception as exc:
        detail = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(limit=8)}
        return StreamingResponse(_error_stream(detail), media_type="text/event-stream")

    run_context = RunContext(id=body["run_id"], parent_id=body.get("parent_id"))
    kwargs: dict[str, Any] = dict(body.get("input") or {})
    if body.get("resume"):
        kwargs["resume"] = body["resume"]

    async def events() -> AsyncIterator[str]:
        set_run_context(run_context)
        try:
            async for event in runnable(**kwargs):
                yield f"data: {_event_json(event)}\n\n"
        except Exception as exc:
            detail = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(limit=8)}
            yield f"event: sandbox_error\ndata: {json.dumps(detail)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


async def _error_stream(detail: dict[str, Any]) -> AsyncIterator[str]:
    yield f"event: sandbox_error\ndata: {json.dumps(detail)}\n\n"


@app.post("/members/{name}/flow")
async def flow(name: str) -> JSONResponse:
    """Static graph of a workflow (nodes, edges, params) via the engine codegen introspection."""
    from messer.codegen.flow import get_flow

    await load_runnable(name)
    return JSONResponse(get_flow(PROJECT_DIR / "workforce" / name))


@app.post("/members/{name}/evals")
async def evals(name: str, request: Request) -> JSONResponse:
    """Run the member's YAML evals with the engine eval runner and return per-case results."""
    from .evals_runner import run_member_evals

    body = await request.json() if await request.body() else {}
    return JSONResponse(await run_member_evals(PROJECT_DIR / "workforce" / name, tags=body.get("tags")))


def main() -> None:
    global PROJECT_DIR
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--socket", required=True)
    args = parser.parse_args()
    PROJECT_DIR = Path(args.project_dir).resolve()
    sys.path.insert(0, str(PROJECT_DIR))
    uvicorn.run(app, uds=args.socket, log_level="warning", lifespan="off")


if __name__ == "__main__":
    main()
