"""Load test for the hot paths: authenticated API reads, agent runs through the public API, and the streaming chat.

    python tests/load/loadtest.py --api http://localhost:8000 --users 20 --duration 60

Creates its own organization, project and agent (and an API key) on the target, then runs N concurrent virtual users
for the given duration. Each user loops over a weighted mix of requests and records latency per scenario. Prints a
table with p50/p95/p99, throughput and error rate (and writes JSON with ``--json``). Agents answer with whatever
model the target has: the deterministic demo model without provider keys, so model latency is excluded and the
numbers measure the platform itself (API, runtime, sandboxes, database, Redis).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Stats:
    latencies: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    errors: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, name: str, seconds: float, ok: bool) -> None:
        self.latencies[name].append(seconds * 1000)
        if not ok:
            self.errors[name] += 1


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1))))
    return ordered[k]


async def _setup(api: str) -> dict[str, str]:
    email = f"load-{uuid.uuid4().hex[:8]}@example.com"
    async with httpx.AsyncClient(base_url=api, timeout=60) as c:
        r = await c.post(
            "/api/v1/auth/signup", json={"email": email, "password": "Contrasena-Carga-123", "name": "Carga"}
        )
        r.raise_for_status()
        project = (await c.post("/api/v1/projects", json={"name": f"Carga {email[5:13]}"})).json()
        pid = project["id"]
        (await c.post(f"/api/v1/projects/{pid}/workforce", json={"name": "asistente"})).raise_for_status()
        key = (await c.post("/api/v1/api-keys", json={"name": "carga", "project_id": pid, "scopes": []})).json()["key"]
        cookies = dict(c.cookies)
    return {"pid": pid, "key": key, **{f"cookie:{k}": v for k, v in cookies.items()}}


async def _user(api: str, ctx: dict[str, str], stats: Stats, deadline: float, prompts: list[str]) -> None:
    cookies = {k.split(":", 1)[1]: v for k, v in ctx.items() if k.startswith("cookie:")}
    headers = {"Authorization": f"Bearer {ctx['key']}"}
    pid = ctx["pid"]
    async with httpx.AsyncClient(base_url=api, timeout=120, cookies=cookies) as c:
        conversation: str | None = None
        while time.monotonic() < deadline:
            roll = random.random()
            t0 = time.perf_counter()
            try:
                if roll < 0.45:
                    res = await c.get("/api/v1/projects")
                    stats.record("GET /projects", time.perf_counter() - t0, res.status_code == 200)
                elif roll < 0.65:
                    res = await c.get("/api/v1/runs", params={"project_id": pid, "limit": 20})
                    stats.record("GET /runs", time.perf_counter() - t0, res.status_code == 200)
                elif roll < 0.85:
                    res = await c.post(
                        f"/v1/projects/{pid}/workforce/asistente/run",
                        headers=headers,
                        json={"input": {"prompt": random.choice(prompts)}, "environment": "development"},
                    )
                    stats.record(
                        "POST /v1/…/run (agent)",
                        time.perf_counter() - t0,
                        res.status_code == 200 and res.json().get("status") == "success",
                    )
                else:
                    body: dict[str, Any] = {"message": random.choice(prompts)}
                    if conversation:
                        body["conversation_id"] = conversation
                    first: float | None = None
                    ok = False
                    async with c.stream("POST", f"/api/v1/projects/{pid}/workforce/asistente/chat", json=body) as res:
                        async for line in res.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            event = json.loads(line[6:])
                            if first is None and event.get("type") == "DELTA":
                                first = time.perf_counter() - t0
                            if event.get("type") == "CONVERSATION":
                                conversation = event["conversation_id"]
                            if event.get("type") == "RUN_FINISHED":
                                ok = event.get("status") == "success"
                    stats.record("chat stream (total)", time.perf_counter() - t0, ok)
                    if first is not None:
                        stats.record("chat stream (first token)", first, True)
            except httpx.HTTPError:
                stats.record("transport errors", time.perf_counter() - t0, False)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--json", dest="json_out")
    args = parser.parse_args()
    ctx = await _setup(args.api)
    prompts = ["Hola, ¿qué tal?", "¿Qué día es hoy?", "Calcula 128 * 37", "Resume en una frase qué haces"]
    stats = Stats()
    started = time.monotonic()
    deadline = started + args.duration
    await asyncio.gather(*(_user(args.api, ctx, stats, deadline, prompts) for _ in range(args.users)))
    elapsed = time.monotonic() - started
    rows = []
    for name, values in sorted(stats.latencies.items()):
        rows.append(
            {
                "scenario": name,
                "requests": len(values),
                "rps": round(len(values) / elapsed, 2),
                "p50_ms": round(_pct(values, 50)),
                "p95_ms": round(_pct(values, 95)),
                "p99_ms": round(_pct(values, 99)),
                "mean_ms": round(statistics.fmean(values)),
                "errors": stats.errors.get(name, 0),
                "error_rate": round(stats.errors.get(name, 0) / max(1, len(values)), 4),
            }
        )
    width = max(len(r["scenario"]) for r in rows) if rows else 10
    print(f"{'scenario'.ljust(width)}  reqs   rps    p50    p95    p99  errors")  # noqa: T201 - CLI report
    for r in rows:
        print(  # noqa: T201 - CLI report
            f"{r['scenario'].ljust(width)}  {r['requests']:>4}  {r['rps']:>5}  {r['p50_ms']:>5}  {r['p95_ms']:>5}  "
            f"{r['p99_ms']:>5}  {r['errors']:>6}"
        )
    if args.json_out:
        payload = json.dumps({"users": args.users, "duration_s": args.duration, "results": rows}, indent=2)
        await asyncio.to_thread(Path(args.json_out).write_text, payload, "utf-8")


if __name__ == "__main__":
    asyncio.run(main())
