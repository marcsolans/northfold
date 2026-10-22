"""Command line: ``messer-connector-agent enroll|run|enroll-and-run|check|status``."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .client import AgentClient
from .config import AgentState, ConfigError, load_config, load_state, save_state, state_path
from .handlers import AgentError, files_list, sql_ping


def say(text: str, *, err: bool = False) -> None:
    stream = sys.stderr if err else sys.stdout
    stream.write(text + "\n")
    stream.flush()


def enroll(api: str, token: str, *, state_file: Path | None = None) -> AgentState:
    """Exchange the enrollment token for the agent id and secret, stored locally (mode 0600)."""
    api = api.rstrip("/")
    if not api.startswith(("https://", "http://")):
        raise SystemExit("--api debe empezar por https://")
    body = json.dumps({"token": token, "hostname": socket.gethostname(), "version": __version__}).encode()
    request = urllib.request.Request(  # noqa: S310 - scheme validated above
        f"{api}/api/v1/connector-agents/enroll",
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("error", {}).get("message")
        except ValueError:
            detail = None
        raise SystemExit(f"El alta ha fallado (HTTP {exc.code}): {detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"No se puede contactar con {api}: {exc.reason}") from exc
    state = AgentState(
        api=api,
        agent_id=str(data["agent_id"]),
        agent_secret=str(data["agent_secret"]),
        org_id=str(data.get("org_id") or ""),
        connect_path=str(data.get("connect_path") or "/api/v1/connector-agents/connect"),
    )
    path = save_state(state, state_file)
    say(f"Agente dado de alta: {state.agent_id}. Credenciales guardadas en {path}")
    return state


async def _run(state: AgentState, config_path: str | None) -> None:
    config = load_config(config_path)
    client = AgentClient(state, config)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    await client.run_forever(stop)


async def _check(config_path: str | None) -> int:
    config = load_config(config_path)
    failures = 0
    say(f"Configuración: {config.path or '(ninguna)'}")
    for name in config.sources:
        try:
            info = await sql_ping(config, {"source": name})
            say(f"  ✔ origen {name}: {info.get('version', '')}")
        except AgentError as exc:
            failures += 1
            say(f"  ✘ origen {name}: {exc.message}")
    for path in config.paths:
        try:
            listing = await files_list(config, {"path": str(path)})
            say(f"  ✔ ruta {path}: {len(listing['entries'])} elementos")
        except AgentError as exc:
            failures += 1
            say(f"  ✘ ruta {path}: {exc.message}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="messer-connector-agent", description="Agente de conectores on-premise de Messer"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)
    p_enroll = sub.add_parser("enroll", help="Da de alta el agente con un token de Messer")
    p_enroll.add_argument("--api", required=True, help="URL de Messer (p. ej. https://app.messer.eu)")
    p_enroll.add_argument("--token", required=True)
    p_enroll.add_argument(
        "--state", type=Path, default=None, help=f"Archivo de credenciales (por defecto {state_path()})"
    )
    p_run = sub.add_parser("run", help="Mantiene la conexión saliente con Messer")
    p_run.add_argument("--config", default=None)
    p_run.add_argument("--state", type=Path, default=None)
    p_both = sub.add_parser("enroll-and-run", help="Da de alta (si hace falta) y se queda en marcha")
    p_both.add_argument("--api", required=True)
    p_both.add_argument("--token", required=True)
    p_both.add_argument("--config", default=None)
    p_both.add_argument("--state", type=Path, default=None)
    p_check = sub.add_parser("check", help="Comprueba los orígenes y rutas configurados")
    p_check.add_argument("--config", default=None)
    p_status = sub.add_parser("status", help="Muestra el alta guardada")
    p_status.add_argument("--state", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        if args.command == "enroll":
            enroll(args.api, args.token, state_file=args.state)
            return 0
        if args.command == "status":
            state = load_state(args.state)
            if state is None:
                say("El agente no está dado de alta.")
                return 1
            say(json.dumps({"api": state.api, "agent_id": state.agent_id, "org_id": state.org_id}, indent=2))
            return 0
        if args.command == "check":
            return asyncio.run(_check(args.config))
        if args.command in ("run", "enroll-and-run"):
            state = load_state(args.state)
            if state is None and args.command == "enroll-and-run":
                state = enroll(args.api, args.token, state_file=args.state)
            if state is None:
                say("El agente no está dado de alta: ejecuta «messer-connector-agent enroll» primero.", err=True)
                return 1
            asyncio.run(_run(state, args.config))
            return 0
    except ConfigError as exc:
        say(f"Error de configuración: {exc}", err=True)
        return 2
    return 1
