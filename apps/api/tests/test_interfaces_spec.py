"""Interface spec: examples validate, errors are precise and located, bindings resolve to parameters only."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from messer_common.interfaces import (
    EXAMPLES,
    InterfaceValidationError,
    build_template,
    json_schema,
    validate_interface,
)
from messer_common.interfaces.examples import PLACEHOLDER_KB, table_dashboard
from messer_common.interfaces.resolve import (
    BindingInputError,
    RequestContext,
    form_values,
    render_prompt,
    sql_params,
    workflow_input,
)
from messer_common.interfaces.spec import FormComponent, KnowledgeSqlBinding, WorkflowBinding


def _issues(data: Any) -> list[dict[str, str]]:
    with pytest.raises(InterfaceValidationError) as info:
        validate_interface(data)
    return info.value.to_list()


def _dashboard() -> dict[str, Any]:
    return copy.deepcopy(EXAMPLES["invoices_dashboard"])


def test_examples_and_templates_validate() -> None:
    for key, example in EXAMPLES.items():
        spec = validate_interface(example)
        assert spec.slug and spec.components(), key
    dashboard = validate_interface(EXAMPLES["invoices_dashboard"])
    types = {c.type for c in dashboard.components()}
    assert {"kpi", "data_table", "chart"} <= types
    assert dashboard.auth.required is True  # apps require login by default
    chat = validate_interface(EXAMPLES["public_chat"])
    assert chat.chat_agent == "soporte" and chat.auth.required is False
    blank = validate_interface(build_template("blank_app", name="Mi panel", slug="mi-panel"))
    assert blank.screens[0].components == []
    generic = validate_interface(
        table_dashboard(
            name="Clientes",
            slug="clientes",
            kb_id=PLACEHOLDER_KB,
            table="clientes",
            columns=[
                {"name": "nombre", "type": "text"},
                {"name": "saldo", "type": "numeric"},
                {"name": "_row_id", "type": "integer"},
            ],
        )
    )
    assert [c.type for c in generic.components()] == ["kpi", "kpi", "data_table", "chart"]
    with pytest.raises(ValueError, match="agente"):
        build_template("public_chat", name="Chat", slug="chat")


def test_round_trip_is_stable_and_json_schema_is_exported() -> None:
    spec = validate_interface(json.dumps(EXAMPLES["invoices_dashboard"]))
    again = validate_interface(spec.to_json())
    assert again.to_json() == spec.to_json()
    schema = json_schema()
    assert schema["title"] == "Messer interface"
    text = json.dumps(schema)
    for name in ("knowledge_sql", "knowledge_search", "approvals_inbox", "file_upload", "action_button"):
        assert name in text


def test_structural_errors_are_located() -> None:
    data = _dashboard()
    comps = data["screens"][0]["components"]
    comps[1]["grid"]["x"] = 10  # 10 + 4 > 12
    comps[2]["type"] = "kpis"
    comps[3]["binding"]["kind"] = "agent"  # tables cannot bind to agents
    comps[4]["props"]["colour"] = "red"
    del comps[0]["binding"]["kb_id"]
    issues = {i["path"]: i for i in _issues(data)}
    assert issues["screens[0].components[1].grid"]["code"] == "grid_overflow"
    assert "kpis" in issues["screens[0].components[2]"]["message"]
    assert "knowledge_sql" in issues["screens[0].components[3].binding"]["message"]
    assert issues["screens[0].components[4].props.colour"]["code"] == "extra_forbidden"
    assert issues["screens[0].components[0].binding.kb_id"]["message"] == "Falta el campo obligatorio «kb_id»"


def test_semantic_errors_sql_layout_and_references() -> None:
    data = _dashboard()
    comps = data["screens"][0]["components"]
    comps[0]["binding"]["params"] = []  # uses $1
    comps[4]["binding"]["sql"] = "DELETE FROM facturas"
    comps[1]["grid"] = {"x": 2, "y": 1, "w": 4, "h": 3}  # overlaps kpi_pendientes
    comps[2]["id"] = "kpi_pendientes"
    comps[3]["binding"]["params"] = [{"input": "cliente"}]  # no filter called "cliente" and no default
    issues = {i["path"]: i for i in _issues(data)}
    assert "$1" in issues["screens[0].components[0].binding.params"]["message"]
    assert issues["screens[0].components[4].binding.sql"]["code"] == "sql_not_read_only"
    assert issues["screens[0].components[1].grid"]["code"] == "grid_overlap"
    assert issues["screens[0].components[2].id"]["code"] == "duplicate_component"
    assert issues["screens[0].components[3].binding.params[0]"]["code"] == "unknown_input"


def test_value_and_shape_rules() -> None:
    chat = copy.deepcopy(EXAMPLES["public_chat"])
    chat["screens"][0]["components"].append(copy.deepcopy(chat["screens"][0]["components"][0]) | {"id": "otro"})
    assert any(i["code"] == "chat_shape" for i in _issues(chat))
    data = _dashboard()
    data["auth"] = {"required": False, "roles": ["admin"]}
    assert any(i["code"] == "auth_roles" for i in _issues(data))
    data = _dashboard()
    data["screens"][0]["components"][0]["binding"]["params"] = [{"context": "yesterday"}]
    assert any("yesterday" in i["message"] for i in _issues(data))
    form = copy.deepcopy(EXAMPLES["request_form"])
    form["screens"][0]["components"][0]["binding"]["input_mapping"]["factura"] = "$form"
    assert any(i["code"] == "mapping_reference" for i in _issues(form))
    form = copy.deepcopy(EXAMPLES["request_form"])
    form["screens"][0]["components"][0]["binding"]["input_mapping"]["solicitante"] = "$user.phone"
    assert any("$user.email" in i["message"] for i in _issues(form))
    assert _issues("{not json")[0]["code"] == "invalid_json"
    assert _issues([1, 2])[0]["code"] == "invalid_type"
    data = _dashboard()
    data["theme"] = {"accent": "red", "logo_url": "http://insecure.example/logo.png"}
    paths = {i["path"] for i in _issues(data)}
    assert {"theme.accent", "theme.logo_url"} <= paths


def test_bindings_resolve_to_parameters_and_inputs() -> None:
    spec = validate_interface(EXAMPLES["invoices_dashboard"])
    table = spec.component("tabla_pendientes")
    vencidas = spec.component("kpi_vencidas")
    assert table is not None and vencidas is not None
    assert isinstance(table.binding, KnowledgeSqlBinding) and isinstance(vencidas.binding, KnowledgeSqlBinding)
    ctx = RequestContext(inputs={"estado": "pagada' OR 1=1 --"}, now=datetime(2026, 10, 21, 12, tzinfo=UTC))
    # The value travels as $1; the SQL text never changes.
    assert sql_params(table.binding, ctx) == ["pagada' OR 1=1 --"]
    assert "OR 1=1" not in table.binding.sql
    assert sql_params(table.binding, RequestContext()) == ["pendiente"]
    assert sql_params(vencidas.binding, ctx) == ["pendiente", "2026-10-21"]
    with pytest.raises(BindingInputError):
        sql_params(table.binding, RequestContext(inputs={"estado": "x" * 5000}))

    form_spec = validate_interface(EXAMPLES["request_form"])
    form = form_spec.component("formulario")
    assert isinstance(form, FormComponent) and isinstance(form.binding, WorkflowBinding)
    values = form_values(form, {"factura": " F-9 ", "importe": "650,5", "motivo": "", "extra": "ignored"})
    assert values == {"factura": "F-9", "importe": 650.5, "motivo": None}
    with pytest.raises(BindingInputError, match="obligatorio"):
        form_values(form, {"importe": 3})
    with pytest.raises(BindingInputError, match="≥"):
        form_values(form, {"factura": "F", "importe": -1})
    params = workflow_input(form.binding, RequestContext(form=values, user_email="ana@acme.example"))
    assert params == {"factura": "F-9", "importe": 650.5, "motivo": None, "solicitante": "ana@acme.example"}
    literal = WorkflowBinding(kind="workflow", workforce="x", input_mapping={"nota": "$$5 de descuento"})
    assert workflow_input(literal, RequestContext()) == {"nota": "$5 de descuento"}
    assert (
        render_prompt(
            "Factura {{row.numero}} de {{user.email}}", RequestContext(row={"numero": "F-1"}, user_email="a@b.es")
        )
        == "Factura F-1 de a@b.es"
    )
