"""Governance API: custom metrics over traces (CRUD, validation, parameterized SQL, values series), alarms
(CRUD, roles, catalog, dry-run test, history) and the organization model policy (validation against known
models, preview, audit, gateway semantics and cache invalidation)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest
from analytics_support import NOW, add_run, make_project
from billing_support import api_client, login
from sqlalchemy import func, select, text

from messer_api.services.analytics import evaluate_alarm
from messer_common import runtime_client
from messer_common.db import system_session
from messer_common.db.models import Alarm, AuditLog, ModelPolicy, Run

SONNET = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"


def _window() -> dict[str, str]:
    return {"since": (NOW - timedelta(hours=3)).isoformat(), "until": (NOW + timedelta(minutes=1)).isoformat()}


async def _org_with_traces(make_user, make_org):  # type: ignore[no-untyped-def]
    owner = await make_user()
    viewer = await make_user()
    org, _ = await make_org(owner=owner, members={str(viewer.id): "viewer"})
    project = await make_project(org.id, "Soporte")
    tool = {"kind": "tool", "duration_ms": 40}
    await add_run(
        org.id,
        project,
        cost="0.30",
        models=[SONNET],
        started_at=NOW - timedelta(hours=1),
        spans=[
            {
                "kind": "llm",
                "model": SONNET,
                "input_tokens": 100,
                "output_tokens": 50,
                "duration_ms": 800,
                "cost": "0.2",
            },
            {**tool, "name": "buscar_factura", "output": {"total": "100%"}},
            {**tool, "name": "buscar_cliente", "output": {"total": "1000"}},
        ],
    )
    await add_run(
        org.id,
        project,
        agent="cobros",
        status="error",
        cost="0.10",
        models=[HAIKU],
        started_at=NOW - timedelta(minutes=30),
        spans=[
            {"kind": "llm", "model": HAIKU, "input_tokens": 10, "output_tokens": 5, "duration_ms": 200, "cost": "0.01"},
            {**tool, "name": "buscar_factura", "status": "error", "error": {"type": "timeout"}},
            {**tool, "name": "enviar_email", "error": None},
        ],
    )
    return org, owner, viewer, project


async def _create_metric(client: httpx.AsyncClient, name: str, definition: dict) -> httpx.Response:  # type: ignore[type-arg]
    return await client.post("/api/v1/metrics", json={"name": name, "definition": definition})


async def test_custom_metric_crud_validation_and_roles(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, viewer, _ = await _org_with_traces(make_user, make_org)
    await login(client, owner.email, org.id)
    created = await _create_metric(
        client, "Búsquedas", {"source": "spans", "filter": {"kind": "tool", "name": "buscar_*"}}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["definition"]["aggregate"] == "count" and body["unit"] == "count" and body["valid"] is True
    # The model comment's legacy key "aggregation" is accepted too.
    legacy = await _create_metric(
        client, "Coste LLM", {"aggregation": "sum", "field": "cost_usd", "filter": {"kind": "llm"}}
    )
    assert legacy.status_code == 201 and legacy.json()["definition"]["aggregate"] == "sum"
    assert legacy.json()["unit"] == "usd"

    dup = await _create_metric(client, "búsquedas", {"source": "spans"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "metric_exists"
    for bad in (
        {"aggregate": "sum"},  # field required
        {"source": "runs", "filter": {"kind": "tool"}},
        {"source": "runs", "filter": {"path_glob": "a.*"}},
        {"source": "spans", "aggregate": "avg", "field": "credits"},
        {"source": "spans", "filter": {"sql": "1=1"}},  # unknown keys are refused
        {"source": "logs"},
        {"aggregate": "median", "field": "duration"},
    ):
        res = await _create_metric(client, f"bad-{uuid.uuid4().hex[:6]}", bad)
        assert res.status_code == 422, (bad, res.text)

    patched = await client.patch(f"/api/v1/metrics/{body['id']}", json={"description": "Herramientas de búsqueda"})
    assert patched.status_code == 200 and patched.json()["description"] == "Herramientas de búsqueda"
    renamed = await client.patch(f"/api/v1/metrics/{body['id']}", json={"name": "Coste LLM"})
    assert renamed.status_code == 409

    async with api_client() as vc:
        await login(vc, viewer.email, org.id)
        assert len((await vc.get("/api/v1/metrics")).json()) == 2
        assert (await _create_metric(vc, "x", {"source": "spans"})).status_code == 403
        assert (await vc.delete(f"/api/v1/metrics/{body['id']}")).status_code == 403
        values = await vc.get(f"/api/v1/metrics/{body['id']}/values", params=_window())
        assert values.status_code == 200 and values.json()["total"] == 3.0

    alarm = await client.post(
        "/api/v1/alarms", json={"name": "Muchas búsquedas", "metric": f"custom:{body['id']}", "threshold": 10}
    )
    assert alarm.status_code == 201, alarm.text
    in_use = await client.delete(f"/api/v1/metrics/{body['id']}")
    assert in_use.status_code == 409 and in_use.json()["error"]["details"]["alarms"][0]["name"] == "Muchas búsquedas"
    listed = {m["name"]: m for m in (await client.get("/api/v1/metrics")).json()}
    assert listed["Búsquedas"]["alarm_count"] == 1
    assert (await client.delete(f"/api/v1/alarms/{alarm.json()['id']}")).status_code == 204
    assert (await client.delete(f"/api/v1/metrics/{body['id']}")).status_code == 204
    assert (await client.get(f"/api/v1/metrics/{body['id']}")).status_code == 404
    async with system_session() as s:
        actions = set((await s.execute(select(AuditLog.action).where(AuditLog.org_id == org.id))).scalars())
    assert {
        "custom_metric.created",
        "custom_metric.updated",
        "custom_metric.deleted",
        "alarm.created",
        "alarm.deleted",
    } <= actions


async def test_custom_metric_values_filters_are_parameterized(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, _, project = await _org_with_traces(make_user, make_org)
    await login(client, owner.email, org.id)

    async def preview(definition: dict, **params: str) -> dict:  # type: ignore[type-arg]
        res = await client.post(
            "/api/v1/metrics/preview", params={**_window(), **params}, json={"definition": definition}
        )
        assert res.status_code == 200, res.text
        return res.json()

    assert (await preview({"filter": {"kind": "tool", "name": "buscar_*"}}))["total"] == 3
    assert (await preview({"filter": {"kind": "tool", "name": "buscar_?actura"}}))["total"] == 2
    assert (await preview({"filter": {"kind": "tool", "error": True}}))["total"] == 1
    assert (await preview({"filter": {"kind": "tool", "error": False}}))["total"] == 3  # JSON null is "no error"
    assert (await preview({"filter": {"status": "error"}}))["total"] == 1
    assert (await preview({"filter": {"path_glob": "cobros.*"}}))["total"] == 3
    # LIKE wildcards in user input are literal: "100%" does not match "1000".
    assert (await preview({"filter": {"output_contains": "100%"}}))["total"] == 1
    assert (await preview({"filter": {"output_contains": "1_00"}}))["total"] == 0
    injection = "'; DROP TABLE runs; --"
    assert (await preview({"filter": {"output_contains": injection, "name": injection}}))["total"] == 0
    async with system_session() as s:
        assert (await s.execute(select(func.count()).select_from(Run).where(Run.org_id == org.id))).scalar_one() == 2

    p95 = await preview(
        {"filter": {"kind": "llm", "model": "anthropic/claude-*"}, "aggregate": "p95", "field": "duration"}
    )
    assert p95["unit"] == "ms" and abs(p95["total"] - (200 + (800 - 200) * 0.95)) < 1e-6
    tokens = await preview({"filter": {"kind": "llm"}, "aggregate": "sum", "field": "tokens"})
    assert tokens["total"] == 165 and tokens["unit"] == "tokens"
    cost = await preview({"source": "runs", "filter": {"model": "*haiku*"}, "aggregate": "sum", "field": "cost_usd"})
    assert abs(cost["total"] - 0.10) < 1e-9
    run_tokens = await preview({"source": "runs", "filter": {"name": "soporte"}, "aggregate": "sum", "field": "tokens"})
    assert run_tokens["total"] == 150
    failed_runs = await preview({"source": "runs", "filter": {"error": True}})
    assert failed_runs["total"] == 1
    empty_avg = await preview({"filter": {"kind": "guard"}, "aggregate": "avg", "field": "duration"})
    assert empty_avg["total"] is None and all(p["value"] is None for p in empty_avg["points"])

    series = await preview({"filter": {"kind": "tool"}}, bucket="hour", tz="Europe/Madrid")
    assert sum(p["value"] for p in series["points"]) == 4 and series["bucket"] == "hour"
    scoped = await preview({"filter": {"kind": "tool"}}, project_id=str(uuid.uuid4()))
    assert scoped["total"] == 0
    by_agent = await preview({"filter": {"kind": "tool"}}, workforce="cobros")
    assert by_agent["total"] == 2
    async with system_session() as s:
        assert (await s.execute(text("select count(*) from spans where org_id = :o"), {"o": org.id})).scalar_one() == 6
    assert (await preview({"filter": {"kind": "tool"}}, project_id=str(project)))["total"] == 4


async def test_alarm_crud_catalog_test_and_history(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, viewer, project = await _org_with_traces(make_user, make_org)
    await login(client, owner.email, org.id)
    catalog = (await client.get("/api/v1/alarms/metrics")).json()
    assert {"error_rate", "latency_p95_ms", "cost_usd", "runs"} <= {m["key"] for m in catalog["builtin"]}
    assert catalog["custom"] == [] and catalog["slack_connected"] is False

    body = {
        "name": "Errores en soporte",
        "project_id": str(project),
        "metric": "error_rate",
        "comparator": ">",
        "threshold": 20,
        "window_minutes": 240,
        "channels": ["email", "email"],
        "environment": "production",
    }
    created = await client.post("/api/v1/alarms", json=body)
    assert created.status_code == 201, created.text
    alarm = created.json()
    assert alarm["channels"] == ["email"] and alarm["state"] == "ok" and alarm["unit"] == "percent"
    assert alarm["project_name"] == "Soporte" and alarm["environment"] == "production"

    for bad, code in (
        ({**body, "metric": "planets"}, 422),
        ({**body, "metric": f"custom:{uuid.uuid4()}"}, 422),
        ({**body, "channels": ["slack"]}, 422),  # Slack needs a target channel
        ({**body, "comparator": "~"}, 422),
        ({**body, "window_minutes": 0}, 422),
        ({**body, "project_id": str(uuid.uuid4())}, 404),
    ):
        res = await client.post("/api/v1/alarms", json=bad)
        assert res.status_code == code, (bad, res.text)

    test = await client.post(f"/api/v1/alarms/{alarm['id']}/test")
    assert test.status_code == 200
    assert test.json()["breached"] is True and abs(test.json()["value"] - 50.0) < 1e-6
    assert (await client.get(f"/api/v1/alarms/{alarm['id']}")).json()["state"] == "ok"  # the dry run changes nothing

    outcome = await evaluate_alarm(uuid.UUID(alarm["id"]))
    assert outcome is not None and outcome.transitioned and outcome.state == "firing"
    history = (await client.get(f"/api/v1/alarms/{alarm['id']}/history")).json()
    assert len(history) == 1 and history[0]["from_state"] == "ok" and history[0]["to_state"] == "firing"
    assert history[0]["delivery"]["email"] == 1 and history[0]["value"] == 50.0
    assert (await client.get("/api/v1/alarms")).json()[0]["state"] == "firing"

    patched = await client.patch(
        f"/api/v1/alarms/{alarm['id']}",
        json={"threshold": 60, "channels": ["email", "slack"], "slack_channel": "#alertas"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["slack_channel"] == "#alertas" and patched.json()["threshold"] == 60
    no_target = await client.patch(f"/api/v1/alarms/{alarm['id']}", json={"slack_channel": None})
    assert no_target.status_code == 422
    paused = await client.patch(f"/api/v1/alarms/{alarm['id']}", json={"enabled": False})
    assert paused.json()["enabled"] is False and paused.json()["state"] == "ok"
    assert await evaluate_alarm(uuid.UUID(alarm["id"]), force=True) is None  # disabled alarms are not evaluated

    async with api_client() as vc:
        await login(vc, viewer.email, org.id)
        assert len((await vc.get("/api/v1/alarms")).json()) == 1
        assert (await vc.get(f"/api/v1/alarms/{alarm['id']}/history")).status_code == 200
        assert (await vc.post("/api/v1/alarms", json=body)).status_code == 403
        assert (await vc.patch(f"/api/v1/alarms/{alarm['id']}", json={"enabled": True})).status_code == 403

    other_owner = await make_user()
    other, _ = await make_org(owner=other_owner, name="Other")
    async with api_client() as oc:
        await login(oc, other_owner.email, other.id)
        assert (await oc.get(f"/api/v1/alarms/{alarm['id']}")).status_code == 404
        assert (await oc.get(f"/api/v1/alarms/{alarm['id']}/history")).status_code == 404
        assert (await oc.get("/api/v1/alarms")).json() == []

    assert (await client.delete(f"/api/v1/alarms/{alarm['id']}")).status_code == 204
    async with system_session() as s:
        assert (
            await s.execute(select(func.count()).select_from(Alarm).where(Alarm.org_id == org.id))
        ).scalar_one() == 0


@pytest.fixture
def runtime_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(runtime_client, "transport", httpx.MockTransport(handler))
    return calls


async def test_model_policy_validation_preview_and_audit(
    client: httpx.AsyncClient, make_user, make_org, runtime_calls: list[str]
) -> None:  # type: ignore[no-untyped-def]
    from messer_runtime.gateway import _policy_allows

    viewer = await make_user()
    owner = await make_user()
    org, _ = await make_org(owner=owner, members={str(viewer.id): "viewer"})
    await login(client, owner.email, org.id)
    default = (await client.get("/api/v1/model-policy")).json()
    assert default["rules"] == {"allow": [], "deny": []} and default["updated_at"] is None
    assert default["allowed_count"] == default["total"] >= 3
    tiers = {t: m["model"] for m in default["models"] for t in m["tiers"]}
    assert tiers == {"fast": HAIKU, "standard": SONNET, "powerful": "anthropic/claude-opus-5-5"}
    assert all(m["model"] != "messer/demo" for m in default["models"])

    saved = await client.put(
        "/api/v1/model-policy", json={"deny": ["anthropic/claude-opus-*", " anthropic/claude-opus-* "]}
    )
    assert saved.status_code == 200, saved.text
    out = saved.json()
    assert out["rules"] == {"allow": [], "deny": ["anthropic/claude-opus-*"]}
    opus = next(m for m in out["models"] if m["model"] == "anthropic/claude-opus-5-5")
    assert opus["allowed"] is False and opus["reason"] == "denied" and opus["pattern"] == "anthropic/claude-opus-*"
    assert {"code": "tier_blocked", "tier": "powerful"} in [
        {"code": w["code"], "tier": w["tier"]} for w in out["warnings"]
    ]
    assert runtime_calls == ["/internal/v1/caches/invalidate"]

    allow = await client.put("/api/v1/model-policy", json={"allow": ["anthropic/claude-haiku-*"], "deny": []})
    rules = allow.json()["rules"]
    decisions = {m["model"]: m["allowed"] for m in allow.json()["models"]}
    assert decisions[HAIKU] is True and decisions[SONNET] is False
    # Exactly the gateway's semantics.
    assert all(_policy_allows(rules, model) == ok for model, ok in decisions.items())
    async with system_session() as s:
        policies = (await s.execute(select(ModelPolicy).where(ModelPolicy.org_id == org.id))).scalars().all()
        assert len(policies) == 1 and policies[0].rules["allow"] == ["anthropic/claude-haiku-*"]
        audits = (
            (
                await s.execute(
                    select(AuditLog.diff).where(AuditLog.org_id == org.id, AuditLog.action == "model_policy.updated")
                )
            )
            .scalars()
            .all()
        )
    assert len(audits) == 2 and any(a["before"]["deny"] == ["anthropic/claude-opus-*"] for a in audits)

    for bad, code in (
        ({"allow": ["claude"]}, "invalid_glob"),
        ({"allow": ["openai/gpt-*"]}, "matches_nothing"),
        ({"deny": ["*"]}, "blocks_everything"),
        ({"allow": ["anthropic/claude-haiku-*"], "deny": ["anthropic/*"]}, "blocks_everything"),
        ({"deny": ["anthropic/claude-opus-5-5; DROP"]}, "invalid_glob"),
    ):
        res = await client.put("/api/v1/model-policy", json=bad)
        assert res.status_code == 422, (bad, res.text)
        assert res.json()["error"]["details"]["errors"][0]["code"] == code
    preview = (await client.post("/api/v1/model-policy/preview", json={"allow": ["openai/*"]})).json()
    assert preview["errors"][0]["code"] == "matches_nothing"
    preview_ok = (await client.post("/api/v1/model-policy/preview", json={"deny": [HAIKU]})).json()
    assert preview_ok["errors"] == [] and preview_ok["allowed_count"] == preview_ok["total"] - 1
    assert (await client.get("/api/v1/model-policy")).json()["rules"]["allow"] == ["anthropic/claude-haiku-*"]

    async with api_client() as vc:
        await login(vc, viewer.email, org.id)
        assert (await vc.get("/api/v1/model-policy")).json()["rules"]["allow"] == ["anthropic/claude-haiku-*"]
        assert (await vc.put("/api/v1/model-policy", json={"deny": []})).status_code == 403
    other_owner = await make_user()
    other, _ = await make_org(owner=other_owner, name="Other")
    async with api_client() as oc:
        await login(oc, other_owner.email, other.id)
        assert (await oc.get("/api/v1/model-policy")).json()["rules"] == {"allow": [], "deny": []}
