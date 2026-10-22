"""AI analytics API: KPIs (cost, runs, users, p50/p95, success rate), previous period, time series by local
hour/day, breakdowns (org, project, agent, channel, environment, user, model), feedback, filters, CSV export
(with formula-injection protection), RLS isolation between organizations, and eval comparison across versions."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from analytics_support import NOW, add_feedback, add_run, make_project, percentile
from billing_support import api_client, login

from messer_common.db import system_session
from messer_common.db.models import EvalRun, Membership, Version, Workforce

SONNET = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"


def _window(hours: int = 6) -> dict[str, str]:
    return {"since": (NOW - timedelta(hours=hours)).isoformat(), "until": (NOW + timedelta(minutes=1)).isoformat()}


async def _seed(make_user, make_org):  # type: ignore[no-untyped-def]
    owner = await make_user(name="Ana Owner")
    org, _ = await make_org(owner=owner, name="Analytics Co")
    p1 = await make_project(org.id, "Soporte", agents=("soporte",))
    p2 = await make_project(org.id, "Ventas", agents=("ventas",))
    llm = {"kind": "llm", "model": SONNET, "input_tokens": 1000, "output_tokens": 200, "cost": "0.004"}
    runs = [
        await add_run(
            org.id,
            p1,
            cost="0.10",
            credits="1",
            duration_ms=100,
            user_id=owner.id,
            models=[SONNET],
            spans=[llm, {"kind": "tool", "name": "buscar_factura", "duration_ms": 30}],
            started_at=NOW - timedelta(hours=2),
        ),
        await add_run(
            org.id,
            p1,
            cost="0.10",
            credits="1",
            duration_ms=200,
            external_user_id="+34600111222",
            channel="whatsapp",
            models=[SONNET],
            spans=[llm],
            started_at=NOW - timedelta(hours=2, minutes=5),
        ),
        await add_run(
            org.id,
            p1,
            cost="0.10",
            credits="1",
            duration_ms=300,
            external_user_id="+34600111222",
            channel="whatsapp",
            environment="development",
            models=[HAIKU],
            spans=[{**llm, "model": HAIKU, "cost": "0.001"}],
            started_at=NOW - timedelta(hours=1),
        ),
        await add_run(
            org.id,
            p1,
            status="error",
            cost="0.05",
            credits="0.5",
            duration_ms=1000,
            user_id=owner.id,
            started_at=NOW - timedelta(minutes=30),
        ),
        await add_run(
            org.id,
            p2,
            agent="ventas",
            cost="0.20",
            credits="2",
            duration_ms=400,
            channel="api",
            models=[SONNET],
            spans=[llm],
            started_at=NOW - timedelta(minutes=20),
        ),
        await add_run(
            org.id,
            p2,
            agent="ventas",
            cost="0.20",
            credits="2",
            duration_ms=500,
            channel="api",
            models=[SONNET],
            spans=[llm],
            started_at=NOW - timedelta(minutes=10),
        ),
    ]
    # Previous period (6 h earlier) and a run that is still running (no duration).
    await add_run(org.id, p1, cost="1.00", duration_ms=50, started_at=NOW - timedelta(hours=9))
    await add_feedback(org.id, runs[0], "up", at=NOW - timedelta(minutes=50))
    await add_feedback(org.id, runs[1], "up", "Muy útil", at=NOW - timedelta(minutes=40))
    await add_feedback(org.id, runs[3], "down", "Respuesta incorrecta", at=NOW - timedelta(minutes=20))
    return org, owner, p1, p2, runs


async def test_overview_kpis_previous_period_and_feedback(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, p1, _, _ = await _seed(make_user, make_org)
    await login(client, owner.email, org.id)
    res = await client.get("/api/v1/analytics/overview", params=_window())
    assert res.status_code == 200, res.text
    body = res.json()
    k = body["kpis"]
    assert (k["runs"], k["success"], k["errors"], k["terminal"]) == (6, 5, 1, 6)
    assert Decimal(k["cost_usd"]) == Decimal("0.75") and Decimal(k["credits"]) == Decimal("7.5")
    assert k["users"] == 2  # one platform user + one WhatsApp user (runs without identity are not users)
    durations = [100, 200, 300, 1000, 400, 500]
    assert abs(k["p50_ms"] - percentile(durations, 0.5)) < 1e-6
    assert abs(k["p95_ms"] - percentile(durations, 0.95)) < 1e-6
    assert abs(k["success_rate"] - 5 / 6) < 1e-9 and abs(k["error_rate"] - 1 / 6) < 1e-9
    assert body["previous"]["runs"] == 1 and Decimal(body["previous"]["cost_usd"]) == Decimal("1.00")
    assert body["feedback"] == {"up": 2, "down": 1, "total": 3, "up_ratio": 2 / 3}
    top = body["top_models"][0]
    assert top["model"] == SONNET and top["label"] == "Claude Sonnet 5.5" and top["runs"] == 4 and top["calls"] == 4

    scoped = (await client.get("/api/v1/analytics/overview", params={**_window(), "project_id": str(p1)})).json()
    assert scoped["kpis"]["runs"] == 4 and scoped["feedback"]["total"] == 3
    prod = (await client.get("/api/v1/analytics/overview", params={**_window(), "environment": "production"})).json()
    assert prod["kpis"]["runs"] == 5
    wa = (await client.get("/api/v1/analytics/overview", params={**_window(), "channel": "whatsapp"})).json()
    assert (
        wa["kpis"]["runs"] == 2
        and wa["kpis"]["users"] == 1
        and wa["feedback"] == {"up": 1, "down": 0, "total": 1, "up_ratio": 1.0}
    )
    agent = (await client.get("/api/v1/analytics/overview", params={**_window(), "workforce": "ventas"})).json()
    assert agent["kpis"]["runs"] == 2


async def test_timeseries_local_buckets(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, *_ = await _seed(make_user, make_org)
    await login(client, owner.email, org.id)
    tz = "America/New_York"
    res = await client.get("/api/v1/analytics/timeseries", params={**_window(), "bucket": "hour", "tz": tz})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["bucket"] == "hour" and body["tz"] == tz
    points = body["points"]
    assert sum(p["runs"] for p in points) == 6
    assert len(points) in (7, 8)
    # The error run lands in the local hour that contains its start time.
    err_local = (NOW - timedelta(minutes=30)).astimezone(ZoneInfo(tz)).replace(minute=0, second=0, microsecond=0)
    bucket = next(p for p in points if datetime.fromisoformat(p["t"]) == err_local)
    assert bucket["errors"] >= 1
    first = datetime.fromisoformat(points[0]["t"])
    assert first.utcoffset() == ZoneInfo(tz).utcoffset(first.replace(tzinfo=None))

    daily = (await client.get("/api/v1/analytics/timeseries", params={**_window(48), "bucket": "day"})).json()
    assert sum(p["runs"] for p in daily["points"]) == 7
    assert sum(Decimal(p["cost_usd"]) for p in daily["points"]) == Decimal("1.75")
    auto = (await client.get("/api/v1/analytics/timeseries", params=_window())).json()
    assert auto["bucket"] == "hour"

    bad_tz = await client.get("/api/v1/analytics/timeseries", params={**_window(), "tz": "Mars/Olympus"})
    assert bad_tz.status_code == 422 and bad_tz.json()["error"]["code"] == "invalid_timezone"
    too_many = await client.get(
        "/api/v1/analytics/timeseries",
        params={"since": (NOW - timedelta(days=200)).isoformat(), "until": NOW.isoformat(), "bucket": "hour"},
    )
    assert too_many.status_code == 422 and too_many.json()["error"]["code"] == "too_many_points"
    inverted = await client.get(
        "/api/v1/analytics/overview", params={"since": NOW.isoformat(), "until": (NOW - timedelta(hours=1)).isoformat()}
    )
    assert inverted.status_code == 422 and inverted.json()["error"]["code"] == "invalid_range"
    too_long = await client.get("/api/v1/analytics/overview", params={"since": (NOW - timedelta(days=500)).isoformat()})
    assert too_long.status_code == 422 and too_long.json()["error"]["code"] == "range_too_long"


async def test_breakdowns_by_every_dimension(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, p1, p2, _ = await _seed(make_user, make_org)
    await login(client, owner.email, org.id)

    async def rows(group_by: str, **params: str) -> list[dict]:  # type: ignore[type-arg]
        res = await client.get("/api/v1/analytics/breakdown", params={**_window(), "group_by": group_by, **params})
        assert res.status_code == 200, res.text
        return res.json()["rows"]

    projects = await rows("project")
    assert [(r["label"], r["runs"]) for r in projects] == [("Soporte", 4), ("Ventas", 2)]
    assert projects[0]["project_id"] == str(p1) and projects[0]["errors"] == 1
    by_cost = await rows("project", sort="cost_usd")
    assert [r["label"] for r in by_cost] == ["Ventas", "Soporte"] and Decimal(by_cost[0]["cost_usd"]) == Decimal("0.40")
    by_error_rate = await rows("project", sort="error_rate")
    assert by_error_rate[0]["label"] == "Soporte"
    agents = await rows("agent")
    assert {(r["label"], r["project_name"]) for r in agents} == {("soporte", "Soporte"), ("ventas", "Ventas")}
    assert next(r for r in agents if r["label"] == "ventas")["key"] == f"{p2}:ventas"
    channels = {r["key"]: r["runs"] for r in await rows("channel")}
    assert channels == {"studio": 2, "whatsapp": 2, "api": 2}
    envs = {r["key"]: r["runs"] for r in await rows("environment")}
    assert envs == {"production": 5, "development": 1}
    users = {r["key"]: r for r in await rows("user")}
    assert users[f"u:{owner.id}"]["label"] == "Ana Owner" and users[f"u:{owner.id}"]["runs"] == 2
    assert users["x:+34600111222"]["runs"] == 2 and users["anonymous"]["runs"] == 2
    org_row = await rows("org")
    assert len(org_row) == 1 and org_row[0]["label"] == "Analytics Co" and org_row[0]["runs"] == 6
    models = {r["key"]: r for r in await rows("model")}
    assert models[SONNET]["calls"] == 4
    assert models[SONNET]["runs"] == 4 and models[SONNET]["input_tokens"] == 4000
    assert models[HAIKU]["runs"] == 1 and Decimal(models[HAIKU]["cost_usd"]) == Decimal("0.001")
    limited = await rows("channel", limit="1")
    assert len(limited) == 1

    invalid = await client.get("/api/v1/analytics/breakdown", params={"group_by": "planet"})
    assert invalid.status_code == 422


async def test_feedback_filters_and_csv_exports(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org, owner, p1, _, runs = await _seed(make_user, make_org)
    evil = await make_project(org.id, '=HYPERLINK("http://x")')
    await add_run(org.id, evil, agent="x", started_at=NOW - timedelta(minutes=1))
    await login(client, owner.email, org.id)

    fb = (await client.get("/api/v1/analytics/feedback", params=_window())).json()
    assert fb["total"] == 3 and [c["comment"] for c in fb["comments"]] == ["Respuesta incorrecta", "Muy útil"]
    assert fb["comments"][0]["project_name"] == "Soporte" and fb["comments"][0]["user"] is None
    assert fb["comments"][0]["run_id"] == str(runs[3])

    opts = (await client.get("/api/v1/analytics/filters", params=_window())).json()
    assert {p["label"] for p in opts["projects"]} >= {"Soporte", "Ventas"}
    assert opts["environments"] == ["development", "production"]
    assert opts["channels"] == ["api", "studio", "whatsapp"]
    assert {a["value"] for a in opts["agents"]} == {"soporte", "ventas", "x"}

    res = await client.get(
        "/api/v1/analytics/export.csv", params={**_window(), "view": "breakdown", "group_by": "project"}
    )
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    table = list(csv.reader(io.StringIO(res.text)))
    assert table[0][:3] == ["name", "project", "runs"]
    labels = [r[0] for r in table[1:]]
    assert "Soporte" in labels and '\'=HYPERLINK("http://x")' in labels

    for view, extra in (
        ("timeseries", {"bucket": "hour"}),
        ("feedback", {}),
        ("overview", {}),
        ("breakdown", {"group_by": "model"}),
        ("breakdown", {"group_by": "user"}),
    ):
        out = await client.get("/api/v1/analytics/export.csv", params={**_window(), "view": view, **extra})
        assert out.status_code == 200, (view, out.text)
        assert len(list(csv.reader(io.StringIO(out.text)))) >= 2
    feedback_csv = (await client.get("/api/v1/analytics/export.csv", params={**_window(), "view": "feedback"})).text
    assert "Respuesta incorrecta" in feedback_csv
    scoped = (
        await client.get(
            "/api/v1/analytics/export.csv", params={**_window(), "view": "overview", "project_id": str(p1)}
        )
    ).text
    assert "runs,4," in scoped


async def test_rls_isolation_and_roles(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    org_a, _owner_a, *_ = await _seed(make_user, make_org)
    owner_b = await make_user()
    org_b, _ = await make_org(owner=owner_b, name="Other Co")
    pb = await make_project(org_b.id, "Secreto")
    await add_run(org_b.id, pb, cost="9.00", started_at=NOW - timedelta(minutes=3))

    viewer = await make_user()
    async with system_session() as s:
        s.add(Membership(org_id=org_a.id, user_id=viewer.id, role="viewer"))
    async with api_client() as vc:
        await login(vc, viewer.email, org_a.id)
        k = (await vc.get("/api/v1/analytics/overview", params=_window())).json()["kpis"]
        assert k["runs"] == 6 and Decimal(k["cost_usd"]) == Decimal("0.75")
        # Asking for another organization's project returns nothing (RLS + org filter).
        other = (await vc.get("/api/v1/analytics/overview", params={**_window(), "project_id": str(pb)})).json()
        assert other["kpis"]["runs"] == 0
        labels = [r["label"] for r in (await vc.get("/api/v1/analytics/breakdown", params=_window())).json()["rows"]]
        assert "Secreto" not in labels
    async with api_client() as bc:
        await login(bc, owner_b.email, org_b.id)
        k = (await bc.get("/api/v1/analytics/overview", params=_window())).json()["kpis"]
        assert k["runs"] == 1 and Decimal(k["cost_usd"]) == Decimal("9.00")
    async with api_client() as anon:
        assert (await anon.get("/api/v1/analytics/overview")).status_code == 401


async def test_eval_comparison_across_versions(client: httpx.AsyncClient, make_user, make_org) -> None:  # type: ignore[no-untyped-def]
    owner = await make_user()
    org, _ = await make_org(owner=owner)
    project_id = await make_project(org.id, "Facturas", agents=("facturas",))
    async with system_session() as s:
        from sqlalchemy import select

        member = (
            await s.execute(select(Workforce).where(Workforce.project_id == project_id, Workforce.name == "facturas"))
        ).scalar_one()
        t = datetime.now(UTC) - timedelta(days=3)
        v1 = Version(
            org_id=org.id,
            project_id=project_id,
            entity_type="workforce",
            entity_id=member.id,
            version=1,
            git_commit="a" * 40,
            message="Primera",
            created_at=t,
        )
        v2 = Version(
            org_id=org.id,
            project_id=project_id,
            entity_type="workforce",
            entity_id=member.id,
            version=2,
            git_commit="b" * 40,
            message="Corrige facturas",
            created_at=t + timedelta(days=1),
        )
        s.add_all([v1, v2])
        await s.flush()

        def ev(version_id: uuid.UUID | None, at: datetime, results: list[dict], status: str = "failed") -> EvalRun:  # type: ignore[type-arg]
            passed = sum(1 for r in results if r.get("passed"))
            return EvalRun(
                org_id=org.id,
                project_id=project_id,
                workforce_id=member.id,
                version_id=version_id,
                trigger="deploy" if version_id else "manual",
                status=status,
                results=results,
                passed=passed,
                failed=len(results) - passed,
                created_at=at,
            )

        s.add_all(
            [
                ev(
                    v1.id,
                    t + timedelta(hours=1),
                    [{"name": "saludo", "passed": True}, {"name": "factura", "passed": False}],
                ),
                ev(
                    v1.id,
                    t + timedelta(hours=2),
                    [{"name": "saludo", "passed": True}, {"name": "factura", "passed": True}],
                ),
                # Manual run after v2 was saved, without a version: attributed to v2.
                ev(
                    None,
                    t + timedelta(days=1, hours=1),
                    [{"name": "saludo", "passed": True}, {"name": "factura", "passed": True}],
                    status="passed",
                ),
                # Manual run before any version existed.
                ev(None, t - timedelta(days=1), [{"name": "saludo", "passed": False}]),
                ev(v2.id, t + timedelta(days=1, hours=2), [{"error": {"type": "runtime_unavailable"}}], status="error"),
            ]
        )
        v1_id, v2_id = v1.id, v2.id
    await login(client, owner.email, org.id)
    res = await client.get(f"/api/v1/projects/{project_id}/workforce/facturas/evals/compare")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["workforce"] == "facturas" and body["kind"] == "agent"
    keys = [v["key"] for v in body["versions"]]
    assert keys == ["head", str(v1_id), str(v2_id)]
    v1o, v2o = body["versions"][1], body["versions"][2]
    assert (v1o["number"], v1o["eval_runs"], v1o["passed"], v1o["failed"]) == (1, 2, 3, 1)
    assert v1o["pass_rate"] == 0.75 and v1o["inferred"] is False
    assert (v2o["number"], v2o["eval_runs"], v2o["errored_runs"], v2o["pass_rate"]) == (2, 2, 1, 1.0)
    cases = {c["name"]: c["results"] for c in body["cases"]}
    assert cases["factura"][str(v1_id)] == {"passed": 1, "total": 2, "rate": 0.5}
    assert cases["factura"][str(v2_id)]["rate"] == 1.0
    assert cases["saludo"]["head"] == {"passed": 0, "total": 1, "rate": 0.0}

    latest = (
        await client.get(f"/api/v1/projects/{project_id}/workforce/facturas/evals/compare", params={"versions": 1})
    ).json()
    assert [v["key"] for v in latest["versions"]] == [str(v2_id)]
    missing = await client.get(f"/api/v1/projects/{project_id}/workforce/nadie/evals/compare")
    assert missing.status_code == 404
