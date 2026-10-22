"""Studio graph ↔ workflow.py: validation, generation, parse round-trip, and running generated workflows."""

from __future__ import annotations

import importlib
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from messer_common.studio.workflow_spec import (
    STARTERS,
    WorkflowConfig,
    WorkflowEdge,
    WorkflowInput,
    WorkflowNode,
    auto_layout,
    custom_function_stub,
    normalized,
    parse_custom_nodes,
    parse_layout,
    parse_workflow_code,
    remove_custom_function,
    render_layout,
    render_workflow_code,
    starter_config,
    stored_config,
    validate_workflow,
    with_positions,
    workflow_member_files,
)

# ------------------------------------------------------------------------------------------- fixtures


class Project:
    """A project checkout on disk importable as ``workforce.<name>`` (like the sandbox loads it)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "workforce").mkdir(parents=True, exist_ok=True)
        (root / "workforce" / "__init__.py").write_text("", encoding="utf-8")

    def add(self, config: WorkflowConfig, nodes_code: str | None = None) -> None:
        for rel, content in workflow_member_files(member_id="m", config=config, nodes_code=nodes_code).items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def add_file(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def runtime(self, name: str) -> Any:
        return importlib.import_module(f"workforce.{name}.workflow_runtime")

    def load(self, name: str) -> Any:
        return importlib.import_module(f"workforce.{name}.workflow").workflow


def _forget_workforce() -> None:
    for key in [k for k in sys.modules if k == "workforce" or k.startswith("workforce.")]:
        del sys.modules[key]


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Project]:
    _forget_workforce()
    sys.path.insert(0, str(tmp_path))
    try:
        yield Project(tmp_path)
    finally:
        sys.path.remove(str(tmp_path))
        _forget_workforce()


async def run(
    workflow: Any, resume: dict[str, Any] | None = None, parent: str | None = None, **inputs: Any
) -> list[Any]:
    from messer.state import RunContext, set_run_context

    set_run_context(RunContext(parent_id=parent))
    if resume is not None:
        inputs["resume"] = resume
    return [event async for event in workflow(**inputs)]


def final(events: list[Any]) -> Any:
    return next(e for e in reversed(events) if e.type == "OUTPUT" and e.parent_call_id is None)


def outputs(events: list[Any], workflow: str) -> dict[str, Any]:
    return {
        e.path.split(".", 1)[1]: e
        for e in events
        if e.type == "OUTPUT" and e.path.count(".") == 1 and e.path.startswith(f"{workflow}.")
    }


def node(node_id: str, type_: str, **config: Any) -> WorkflowNode:
    return WorkflowNode(id=node_id, type=type_, config=config)  # type: ignore[arg-type]


def edge(source: str, target: str, condition: str | None = None) -> WorkflowEdge:
    return WorkflowEdge(source=source, target=target, condition=condition)  # type: ignore[arg-type]


def codes(config: WorkflowConfig, **kwargs: Any) -> set[str]:
    return {i["code"] for i in validate_workflow(config, **kwargs)}


# ----------------------------------------------------------------------------------- generation & parse


@pytest.mark.parametrize("template", STARTERS)
def test_starters_roundtrip(template: str) -> None:
    cfg = starter_config(template, f"flujo_{template}", "Prueba")
    assert validate_workflow(cfg) == []
    code = render_workflow_code(cfg)
    assert "from messer import Workflow" in code and "STUDIO = " in code
    parsed = parse_workflow_code(code)
    assert parsed is not None
    assert normalized(parsed).model_dump() == normalized(cfg).model_dump()


def test_bindings_become_step_span_lookups_and_explicit_edges() -> None:
    code = render_workflow_code(starter_config("approval", "pagos"))
    assert 'preparar=get_run_context().step_span("preparar", None)' in code
    assert 'input=get_run_context().step_span("entrada", None)' in code
    assert 'depends_on=["preparar"]' in code
    assert "requires_approval" not in code  # the approval node factory gates itself


def test_hand_edited_literals_stay_in_sync() -> None:
    cfg = starter_config("approval", "pagos")
    code = render_workflow_code(cfg).replace(
        "¿Aprobar {{preparar.output.concepto}}", "¿Pagamos {{preparar.output.concepto}}"
    )
    code = code.replace('approver_role="admin"', 'approver_role="owner"')
    parsed = parse_workflow_code(code)
    assert parsed is not None
    approval = parsed.node("aprobar")
    assert approval is not None
    assert approval.config["prompt"].startswith("¿Pagamos") and approval.config["approver_role"] == "owner"


def test_structural_edits_switch_to_code_mode() -> None:
    code = render_workflow_code(starter_config("approval", "pagos"))
    assert parse_workflow_code(code + "\n\ndef helper():\n    return 1\n") is None
    assert parse_workflow_code(code.replace('depends_on=["preparar"]', 'depends_on=["entrada"]')) is None
    assert parse_workflow_code(code.replace('wf.render(\n            "{{preparar.output.importe}}"', "str(")) is None
    assert parse_workflow_code("this is not python(") is None


def test_layout_roundtrip_and_auto_layout() -> None:
    cfg = starter_config("classify", "clasificador")
    positions = auto_layout(cfg)
    assert set(positions) == {n.id for n in cfg.nodes}
    text = render_layout(with_positions(cfg, positions), {"x": 10, "y": -5, "zoom": 0.8})
    back, viewport = parse_layout(text)
    assert back["clasificar"].x == positions["clasificar"].x and viewport["zoom"] == 0.8
    assert parse_layout("not json") == ({}, {"x": 0.0, "y": 0.0, "zoom": 1.0})


def test_stored_config_routes_approver_roles() -> None:
    cfg = starter_config("approval", "pagos")
    stored = stored_config(cfg)
    assert {"name": "aprobar", "key": "aprobar", "approver_role": "admin"} in stored["tools"]
    assert all("position" not in n for n in stored["nodes"])


# ------------------------------------------------------------------------------------------- validation


def _base(*nodes: WorkflowNode, edges: list[WorkflowEdge] | None = None) -> WorkflowConfig:
    return WorkflowConfig(
        name="prueba",
        inputs=[WorkflowInput(name="importe", type="number")],
        nodes=[node("entrada", "input"), *nodes],
        edges=edges or [],
    )


def test_validation_rules() -> None:
    assert "input_count" in codes(WorkflowConfig(name="x", nodes=[node("salida", "output")]))
    assert "no_output" in codes(_base())
    dup = _base(node("salida", "output"), node("salida", "output"), edges=[edge("entrada", "salida")])
    assert "duplicate_id" in codes(dup)
    reserved = _base(node("input", "output"), edges=[edge("entrada", "input")])
    assert "invalid_id" in codes(reserved)
    disconnected = _base(node("salida", "output"))
    assert "disconnected" in codes(disconnected)
    cyc = _base(
        node("a", "transform", value="1"),
        node("b", "transform", value="2"),
        node("salida", "output"),
        edges=[edge("entrada", "a"), edge("a", "b"), edge("b", "a"), edge("b", "salida")],
    )
    issues = validate_workflow(cyc)
    assert {i["code"] for i in issues} == {"cycle"} and {i["node_id"] for i in issues} == {"a", "b"}
    upstream = _base(
        node("a", "transform", value="{{b.output}}"),
        node("b", "transform", value="x"),
        node("salida", "output", value="{{a.output}}"),
        edges=[edge("entrada", "a"), edge("entrada", "b"), edge("a", "salida"), edge("b", "salida")],
    )
    assert "invalid_binding" in codes(upstream)
    unknown_input = _base(node("salida", "output", value="{{input.nada}}"), edges=[edge("entrada", "salida")])
    assert "invalid_binding" in codes(unknown_input)
    branches = _base(
        node("si", "condition", expression="{{input.importe}} > 10"),
        node("salida", "output"),
        edges=[edge("entrada", "si"), edge("si", "salida")],
    )
    assert "unlabeled_branch" in codes(branches)
    unsafe = _base(
        node("si", "condition", expression="__import__('os').system('ls')"),
        node("salida", "output"),
        edges=[edge("entrada", "si"), edge("si", "salida", "true")],
    )
    assert "invalid_expression" in codes(unsafe)
    sql = _base(
        node("q", "sql_query", kb_id="kb", sql="select * from t where a = '{{input.importe}}'"),
        node("salida", "output"),
        edges=[edge("entrada", "q"), edge("q", "salida")],
    )
    assert "sql_bindings" in codes(sql)
    wait = _base(
        node("w", "wait", seconds=10_000), node("salida", "output"), edges=[edge("entrada", "w"), edge("w", "salida")]
    )
    assert "invalid_config" in codes(wait)
    agent = _base(
        node("a", "agent", agent="soporte", prompt="Hola"),
        node("salida", "output"),
        edges=[edge("entrada", "a"), edge("a", "salida")],
    )
    assert "unknown_agent" in codes(agent, members={"otro": "agent"})
    assert codes(agent, members={"soporte": "agent"}) == set()
    custom = _base(
        node("c", "custom", function="falta"),
        node("salida", "output"),
        edges=[edge("entrada", "c"), edge("c", "salida")],
    )
    assert "unknown_function" in codes(custom, custom_functions=["otra"])


def test_loop_body_rules() -> None:
    good = _base(
        node("cada", "loop", items="{{input.importe}}", body="doble"),
        node("doble", "transform", value="{{cada.item}}"),
        node("salida", "output", value="{{cada.output}}"),
        edges=[edge("entrada", "cada"), edge("cada", "doble"), edge("doble", "cada"), edge("cada", "salida")],
    )
    assert validate_workflow(good) == []
    leaking = good.model_copy(update={"nodes": [*good.nodes[:3], node("salida", "output", value="{{doble.output}}")]})
    assert "invalid_binding" in codes(leaking)
    stray = good.model_copy(update={"edges": [*good.edges, edge("doble", "salida")]})
    assert "loop_body_connections" in codes(stray)
    approval_body = good.model_copy(
        update={"nodes": [good.nodes[0], good.nodes[1], node("doble", "approval"), good.nodes[3]]}
    )
    assert "loop_body_type" in codes(approval_body)


# --------------------------------------------------------------------------------------------- running

PARALLEL_NODES = '''
import asyncio
import time
from typing import Any

CALLS: list[str] = []


async def lento(etiqueta: str = "", segundos: float = 0.3) -> dict[str, Any]:
    """Espera y devuelve cuándo empezó y terminó."""
    CALLS.append(etiqueta)
    start = time.perf_counter()
    await asyncio.sleep(segundos)
    return {"etiqueta": etiqueta, "inicio": start, "fin": time.perf_counter()}


def contar(valor: Any = None) -> dict[str, Any]:
    CALLS.append(f"contar:{valor}")
    return {"valor": valor, "llamadas": len(CALLS)}
'''


def _parallel_config() -> WorkflowConfig:
    return WorkflowConfig(
        name="paralelo",
        inputs=[WorkflowInput(name="cliente", type="string", required=True)],
        nodes=[
            node("entrada", "input"),
            node("a", "custom", function="lento", args={"etiqueta": "A-{{input.cliente}}"}),
            node("b", "custom", function="lento", args={"etiqueta": "B-{{event.body.pedido}}"}),
            node(
                "salida",
                "output",
                value={
                    "a": "{{a.output.etiqueta}}",
                    "b": "{{b.output.etiqueta}}",
                    "texto": "Cliente {{input.cliente}}",
                },
            ),
        ],
        edges=[edge("entrada", "a"), edge("entrada", "b"), edge("a", "salida"), edge("b", "salida")],
        custom_nodes=["lento", "contar"],
    )


async def test_independent_branches_run_in_parallel(project: Project) -> None:
    cfg = _parallel_config()
    project.add(cfg, nodes_code=PARALLEL_NODES)
    workflow = project.load("paralelo")
    started = time.perf_counter()
    events = await run(workflow, cliente="ACME", event={"type": "webhook", "body": {"pedido": 77}})
    elapsed = time.perf_counter() - started
    out = final(events)
    assert out.status.code == "success", out.error
    assert out.output == {"a": "A-ACME", "b": "B-77", "texto": "Cliente ACME"}
    steps = outputs(events, "paralelo")
    a, b = steps["a"].output, steps["b"].output
    assert a["inicio"] < b["fin"] and b["inicio"] < a["fin"]  # overlapping
    assert elapsed < 0.55


async def test_generated_flow_matches_engine_introspection(project: Project) -> None:
    from messer.codegen.flow import get_flow

    project.add(_parallel_config(), nodes_code=PARALLEL_NODES)
    flow = get_flow(project.root / "workforce" / "paralelo")
    ids = {n["id"] for n in flow["nodes"]}
    assert ids == {"paralelo.entrada", "paralelo.a", "paralelo.b", "paralelo.salida"}
    pairs = {(e["source"], e["target"]) for e in flow["edges"]}
    assert ("paralelo.entrada", "paralelo.a") in pairs and ("paralelo.b", "paralelo.salida") in pairs
    params = next(n for n in flow["nodes"] if n["id"] == "paralelo.entrada")["data"]["params"]
    assert set(params["properties"]) == {"cliente", "event"} and params["required"] == ["cliente"]


async def test_condition_branches_and_llm_json(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from messer import Agent
    from messer.core.test_model import TestModel

    cfg = starter_config("classify", "clasificador")
    project.add(cfg)
    runtime = project.runtime("clasificador")
    answers = iter(
        ['{"urgente": true, "motivo": "Sin servicio"}', '```json\n{"urgente": false, "motivo": "Duda"}\n```']
    )
    model = TestModel(handler=lambda _messages: next(answers))

    def offline_agent(**kwargs: Any) -> Agent:
        return Agent(**{**kwargs, "model": model})

    monkeypatch.setattr(runtime, "_make_agent", offline_agent)
    workflow = project.load("clasificador")
    first = await run(workflow, texto="No tengo línea desde ayer")
    assert final(first).output == {"prioridad": "alta", "motivo": "Sin servicio"}
    assert set(outputs(first, "clasificador")) == {"entrada", "clasificar", "es_urgente", "urgente"}
    second = await run(workflow, texto="¿Cómo cambio mi tarifa?")
    assert final(second).output == {"prioridad": "normal", "motivo": "Duda"}
    assert "urgente" not in outputs(second, "clasificador")
    missing = await run(workflow)
    assert final(missing).status.code == "error"


async def test_loop_over_items_and_count(project: Project) -> None:
    cfg = WorkflowConfig(
        name="bucles",
        inputs=[WorkflowInput(name="lineas", type="object")],
        nodes=[
            node("entrada", "input"),
            node("cada", "loop", items="{{input.lineas}}", body="formatear"),
            node(
                "formatear",
                "transform",
                value="{{cada.index}}: {{cada.item.nombre}} x{{cada.item.unidades}} ({{input.lineas.0.nombre}})",
            ),
            node("veces", "loop", mode="count", count=3, body="numero"),
            node("numero", "transform", value="{{veces.index}}"),
            node("salida", "output", value={"lineas": "{{cada.output}}", "veces": "{{veces.output}}"}),
        ],
        edges=[
            edge("entrada", "cada"),
            edge("cada", "formatear"),
            edge("cada", "salida"),
            edge("entrada", "veces"),
            edge("veces", "numero"),
            edge("numero", "veces"),
            edge("veces", "salida"),
        ],
    )
    assert validate_workflow(cfg) == []
    project.add(cfg)
    events = await run(
        project.load("bucles"), lineas=[{"nombre": "Tornillo", "unidades": 4}, {"nombre": "Tuerca", "unidades": 2}]
    )
    out = final(events)
    assert out.status.code == "success", out.error
    assert out.output == {"lineas": ["0: Tornillo x4 (Tornillo)", "1: Tuerca x2 (Tornillo)"], "veces": [0, 1, 2]}
    body_paths = {e.path for e in events if e.type == "OUTPUT" and e.path.endswith(".formatear")}
    assert body_paths == {"bucles.cada.formatear"}


def _approval_config() -> WorkflowConfig:
    return WorkflowConfig(
        name="pagos",
        inputs=[WorkflowInput(name="importe", type="number", required=True)],
        nodes=[
            node("entrada", "input"),
            node("registrar", "custom", function="contar", args={"valor": "{{input.importe}}"}),
            node(
                "aprobar",
                "approval",
                prompt="¿Pagar {{registrar.output.valor}} €?",
                payload={"importe": "{{registrar.output.valor}}", "from": "tesoreria"},
                approver_role="builder",
            ),
            node("grande", "condition", expression="{{aprobar.output.importe}} >= 1000"),
            node("revisar", "output", value={"estado": "revisión", "importe": "{{aprobar.output.importe}}"}),
            node(
                "pagar",
                "output",
                value={
                    "estado": "pagado",
                    "importe": "{{aprobar.output.importe}}",
                    "origen": "{{aprobar.output.from}}",
                },
            ),
        ],
        edges=[
            edge("entrada", "registrar"),
            edge("registrar", "aprobar"),
            edge("aprobar", "grande"),
            edge("grande", "revisar", "true"),
            edge("grande", "pagar", "false"),
        ],
        custom_nodes=["lento", "contar"],
    )


async def test_approval_pauses_and_resumes_with_corrections(project: Project) -> None:
    project.add(_approval_config(), nodes_code=PARALLEL_NODES)
    workflow = project.load("pagos")
    nodes_module = importlib.import_module("workforce.pagos.nodes")
    paused = await run(workflow, importe=1500)
    gate = next(e for e in paused if e.type == "APPROVAL")
    assert gate.prompt == "¿Pagar 1500 €?"
    assert gate.input == {"importe": 1500.0, "from_": "tesoreria"}
    assert gate.metadata == {"approver_role": "builder", "node": "aprobar"}
    assert final(paused).status.reason == "approval_required"

    resumed = await run(
        workflow,
        importe=1500,
        parent=final(paused).run_id,
        resume={gate.approval_id: {"approved": True, "override_input": {"importe": 900}}},
    )
    out = final(resumed)
    assert out.status.code == "success", out.error
    assert out.output == {"estado": "pagado", "importe": 900, "origen": "tesoreria"}
    assert nodes_module.CALLS == ["contar:1500.0"]  # replayed on resume, not executed twice
    registrar = outputs(resumed, "pagos")["registrar"]
    assert registrar.output["valor"] == 1500.0


async def test_denied_approval_ends_the_run(project: Project) -> None:
    project.add(_approval_config(), nodes_code=PARALLEL_NODES)
    workflow = project.load("pagos")
    paused = await run(workflow, importe=20)
    gate = next(e for e in paused if e.type == "APPROVAL")
    denied = await run(
        workflow,
        importe=20,
        parent=final(paused).run_id,
        resume={gate.approval_id: {"approved": False, "reason": "No procede"}},
    )
    out = final(denied)
    assert out.status.code == "cancelled" and out.status.reason == "approval_denied"
    assert not {"revisar", "pagar"} & set(outputs(denied, "pagos"))


async def test_http_post_waits_for_approval(project: Project) -> None:
    cfg = _base(
        node(
            "avisar",
            "http_request",
            method="POST",
            url="https://hooks.example.com/{{input.importe}}",
            body={"importe": "{{input.importe}}"},
            approver_role="owner",
        ),
        node("salida", "output", value="{{avisar.output.status}}"),
        edges=[edge("entrada", "avisar"), edge("avisar", "salida")],
    ).model_copy(update={"name": "avisos"})
    project.add(cfg)
    events = await run(project.load("avisos"), importe=5)
    gate = next(e for e in events if e.type == "APPROVAL")
    assert gate.prompt == "¿Permitir POST https://hooks.example.com/5?"
    assert gate.input["body"] == {"importe": 5.0} and gate.metadata["approver_role"] == "owner"


async def test_agent_and_sub_workflow_nodes(project: Project) -> None:
    project.add_file("workforce/soporte/messer.yaml", "_type: agent\nfqn: agent.py::agent\n")
    project.add_file("workforce/soporte/__init__.py", "")
    project.add_file(
        "workforce/soporte/agent.py",
        "from messer import Agent\nfrom messer.core.test_model import TestModel\n\n"
        "agent = Agent(name='soporte', model=TestModel(handler=lambda m: 'Respuesta a: ' + m[-1].collect_text()),"
        " tools=[], max_tokens=64)\n",
    )
    child = WorkflowConfig(
        name="saludo",
        inputs=[WorkflowInput(name="nombre", type="string")],
        nodes=[node("entrada", "input"), node("salida", "output", value="Hola {{input.nombre}}")],
        edges=[edge("entrada", "salida")],
    )
    parent = WorkflowConfig(
        name="principal",
        inputs=[WorkflowInput(name="nombre", type="string")],
        nodes=[
            node("entrada", "input"),
            node("preguntar", "agent", agent="soporte", prompt="¿Qué tal {{input.nombre}}?"),
            node("saludar", "sub_workflow", workflow="saludo", args={"nombre": "{{input.nombre}}"}),
            node("salida", "output", value={"agente": "{{preguntar.output}}", "saludo": "{{saludar.output}}"}),
        ],
        edges=[
            edge("entrada", "preguntar"),
            edge("entrada", "saludar"),
            edge("preguntar", "salida"),
            edge("saludar", "salida"),
        ],
    )
    assert validate_workflow(parent, members={"soporte": "agent", "saludo": "workflow"}) == []
    project.add(child)
    project.add(parent)
    out = final(await run(project.load("principal"), nombre="Ana"))
    assert out.status.code == "success", out.error
    assert out.output == {"agente": "Respuesta a: ¿Qué tal Ana?", "saludo": "Hola Ana"}


# ------------------------------------------------------------------------------------------ custom nodes


def test_custom_nodes_parse_add_and_remove() -> None:
    code = PARALLEL_NODES + custom_function_stub("nuevo", "Hace algo")
    functions = {f.name: f for f in parse_custom_nodes(code)}
    assert set(functions) == {"lento", "contar", "nuevo"}
    assert functions["lento"].is_async and functions["lento"].params[0] == {
        "name": "etiqueta",
        "required": False,
        "annotation": "str",
    }
    assert functions["nuevo"].description == "Hace algo"
    removed = remove_custom_function(code, "lento")
    assert {f.name for f in parse_custom_nodes(removed)} == {"contar", "nuevo"}
    with pytest.raises(KeyError):
        remove_custom_function(code, "nada")
    with pytest.raises(SyntaxError):
        parse_custom_nodes("def roto(:\n")
