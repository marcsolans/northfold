"""Temporary spike: agent with a workflow tool that pauses for approval; evals on paused runs."""

from __future__ import annotations

import json
from typing import Any

import httpx

from messer_common.projects_repo import ProjectRepo
from messer_runtime.testing import Harness


async def _sse(client: httpx.AsyncClient, url: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    async with client.stream("POST", url, json=body) as res:
        assert res.status_code == 200, (await res.aread()).decode()
        async for line in res.aiter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


WF = {
    "name": "nota_credito",
    "description": "Emite una nota de crédito (abono) para una factura; pide aprobación por encima de 500 €",
    "inputs": [
        {"name": "factura", "type": "string", "description": "Número de factura", "required": True},
        {"name": "importe", "type": "number", "description": "Importe del abono en euros", "required": True},
        {"name": "motivo", "type": "string", "description": "Motivo"},
    ],
    "nodes": [
        {"id": "entrada", "type": "input"},
        {"id": "supera_umbral", "type": "condition", "config": {"expression": "{{input.importe}} > 500"}},
        {
            "id": "aprobacion",
            "type": "approval",
            "config": {
                "prompt": "¿Aprobar el abono de {{input.importe}} € para {{input.factura}}?",
                "payload": {"factura": "{{input.factura}}", "importe": "{{input.importe}}"},
                "approver_role": "admin",
            },
        },
        {
            "id": "emitida_aprobada",
            "type": "output",
            "config": {"value": {"estado": "emitida", "factura": "{{input.factura}}", "aprobada": True}},
        },
        {
            "id": "emitida",
            "type": "output",
            "config": {"value": {"estado": "emitida", "factura": "{{input.factura}}", "aprobada": False}},
        },
    ],
    "edges": [
        {"source": "entrada", "target": "supera_umbral"},
        {"source": "supera_umbral", "target": "aprobacion", "condition": "true"},
        {"source": "supera_umbral", "target": "emitida", "condition": "false"},
        {"source": "aprobacion", "target": "emitida_aprobada"},
    ],
}


async def test_spike(client: httpx.AsyncClient, runtime: Harness) -> None:
    res = await client.post("/api/v1/auth/signup", json={"email": "spike@acme.example", "password": "Contrasena123"})
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Spike"})).json()["id"]
    r = await client.post(f"/api/v1/projects/{pid}/workflows", json={"name": "nota_credito", "config": WF})
    print("WF", r.status_code, r.text[:400])
    created = await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})
    cfg = created.json()["config"]
    cfg["tools"] = [
        {"type": "builtin", "key": "current_datetime"},
        {"type": "custom", "key": "nota_credito", "description": "Emite una nota de crédito"},
    ]
    repo = ProjectRepo.for_project(pid)
    await repo.write(
        {
            "workforce/soporte/tools.py": (
                '"""Herramientas propias."""\n\nfrom ..nota_credito.workflow import workflow as nota_credito\n\n'
                '__all__ = ["nota_credito"]\n'
            ),
            "workforce/soporte/evals/spike.yaml": (
                "- name: abono_grande\n  runnable: ../agent.py::agent\n  params:\n"
                "    prompt: Necesito una nota de crédito de 900 € para la factura F-1001\n"
                "  seq!:\n    - ...\n    - nota_credito\n    - ...\n"
                "- name: abono_pequeno\n  runnable: ../agent.py::agent\n  params:\n"
                "    prompt: Necesito una nota de crédito de 200 € para la factura F-1002\n"
                "  output:\n    contains!: emitida\n"
            ),
            "workforce/nota_credito/evals/spike.yaml": (
                "- name: wf_grande\n  runnable: ../workflow.py::workflow\n  params:\n"
                "    factura: F-1\n    importe: 900\n"
                "  output:\n    not_null!: false\n"
                "- name: wf_pequeno\n  runnable: ../workflow.py::workflow\n  params:\n"
                "    factura: F-2\n    importe: 100\n"
                "  output:\n    estado:\n      eq!: emitida\n"
            ),
        },
        message="spike",
        author="t",
        email="t@x",
    )
    saved = await client.put(f"/api/v1/projects/{pid}/workforce/soporte/config", json=cfg)
    print("CFG", saved.status_code, saved.text[:300])
    code = (await client.get(f"/api/v1/projects/{pid}/workforce/soporte")).json()["code"]
    print(code)
    events = await _sse(
        client,
        f"/api/v1/projects/{pid}/workforce/soporte/chat",
        {"message": "Necesito una nota de crédito de 900 € para la factura F-1001"},
    )
    for e in events:
        if e.get("type") in ("APPROVAL", "RUN_FINISHED", "RUN_ERROR") or e.get("type") == "OUTPUT":
            print("EV", json.dumps(e, default=str)[:600])
    for name in ("soporte", "nota_credito"):
        ev = await client.post(f"/api/v1/projects/{pid}/workforce/{name}/evals", json={})
        print("EVALS", name, ev.status_code, json.dumps(ev.json(), default=str)[:3000])
