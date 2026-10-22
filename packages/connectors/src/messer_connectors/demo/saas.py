"""Fake Slack, Notion, HubSpot and Salesforce APIs backed by the JSON fixtures (demo mode)."""

from __future__ import annotations

import operator
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

import httpx

from ..base import ConnectionContext
from . import DemoClock, error_response, fixture, iso, json_response, new_id, request_json, route, words_match

# ============================================================================= Slack


def _slack_ok(data: dict[str, Any]) -> httpx.Response:
    return json_response({"ok": True, **data})


def slack_handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    data = fixture("slack")
    method = request.url.path.removeprefix("/api/")
    params = dict(request.url.params)
    if request.method == "POST":
        params.update({k: str(v) for k, v in request_json(request).items()})
    channels = {c["id"]: c for c in data["channels"]}
    messages = [{**m, "ts": f"{clock.at(m['offset_min']).timestamp():.6f}"} for m in data["messages"]]
    if method == "auth.test":
        return _slack_ok(
            {
                "url": "https://albor-demo.slack.example/",
                "team": data["team"]["name"],
                "user": data["user"]["name"],
                "team_id": data["team"]["id"],
                "user_id": data["user"]["id"],
            }
        )
    if method == "conversations.list":
        return _slack_ok(
            {
                "channels": [
                    {**c, "topic": {"value": c["topic"]}, "is_archived": False, "is_member": True}
                    for c in data["channels"]
                ],
                "response_metadata": {"next_cursor": ""},
            }
        )
    if method == "conversations.history":
        channel = params.get("channel", "")
        if channel not in channels:
            return _slack_error("channel_not_found")
        found = sorted((m for m in messages if m["channel"] == channel), key=lambda m: m["ts"], reverse=True)
        return _slack_ok(
            {
                "messages": [{"type": "message", "user": m["user"], "text": m["text"], "ts": m["ts"]} for m in found],
                "has_more": False,
            }
        )
    if method == "chat.postMessage":
        channel = params.get("channel", "")
        if channel.lstrip("#") not in {c["name"] for c in data["channels"]} and channel not in channels:
            return _slack_error("channel_not_found")
        ts = f"{datetime.now(UTC).timestamp():.6f}"
        return _slack_ok({"channel": channel, "ts": ts, "message": {"text": params.get("text", ""), "ts": ts}})
    if method == "chat.update":
        if params.get("channel") not in channels:
            return _slack_error("channel_not_found")
        return _slack_ok({"channel": params["channel"], "ts": params.get("ts"), "text": params.get("text", "")})
    if method == "search.messages":
        query = params.get("query", "")
        found = [m for m in messages if words_match(query, m["text"], m["username"])]
        return _slack_ok(
            {
                "messages": {
                    "total": len(found),
                    "matches": [
                        {
                            "channel": {"id": m["channel"], "name": channels[m["channel"]]["name"]},
                            "username": m["username"],
                            "text": m["text"],
                            "ts": m["ts"],
                            "permalink": f"https://albor-demo.slack.example/archives/{m['channel']}",
                        }
                        for m in found
                    ],
                }
            }
        )
    return _slack_error("unknown_method")


def _slack_error(code: str) -> httpx.Response:
    return json_response({"ok": False, "error": code})


# ============================================================================= Notion


def _rich(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "plain_text": text, "text": {"content": text}, "annotations": {}}]


def _notion_page(page: dict[str, Any], clock: DemoClock) -> dict[str, Any]:
    when = iso(clock.at(page["offset_min"]))
    parent = page["parent"]
    return {
        "object": "page",
        "id": page["id"],
        "created_time": when,
        "last_edited_time": when,
        "archived": False,
        "url": f"https://www.notion.so/demo-{page['id']}",
        "icon": {"type": "emoji", "emoji": page.get("icon", "📄")},
        "parent": {"type": "workspace", "workspace": True}
        if parent["type"] == "workspace"
        else {"type": "page_id", "page_id": parent["id"]},
        "properties": {"title": {"id": "title", "type": "title", "title": _rich(page["title"])}},
    }


def _notion_row(db: dict[str, Any], row: dict[str, Any], clock: DemoClock) -> dict[str, Any]:
    when = iso(clock.at(row["offset_min"]))
    return {
        "object": "page",
        "id": row["id"],
        "created_time": when,
        "last_edited_time": when,
        "archived": False,
        "url": f"https://www.notion.so/demo-{row['id']}",
        "parent": {"type": "database_id", "database_id": db["id"]},
        "properties": {
            "Nombre": {"type": "title", "title": _rich(row["title"])},
            "Estado": {"type": "select", "select": {"name": row["Estado"]}},
            "Cliente": {"type": "rich_text", "rich_text": _rich(row["Cliente"])},
            "Importe": {"type": "number", "number": row["Importe"]},
        },
    }


def _notion_db(db: dict[str, Any], clock: DemoClock) -> dict[str, Any]:
    when = iso(clock.at(db["offset_min"]))
    return {
        "object": "database",
        "id": db["id"],
        "created_time": when,
        "last_edited_time": when,
        "title": _rich(db["title"]),
        "url": f"https://www.notion.so/demo-{db['id']}",
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "Nombre": {"type": "title"},
            "Estado": {"type": "select"},
            "Cliente": {"type": "rich_text"},
            "Importe": {"type": "number"},
        },
    }


def notion_handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    data = fixture("notion")
    path = request.url.path.removeprefix("/v1")
    pages = {p["id"]: p for p in data["pages"]}
    dbs = {d["id"]: d for d in data["databases"]}
    if path == "/users/me":
        return json_response(
            {
                "object": "user",
                "id": data["bot"]["id"],
                "type": "bot",
                "name": data["bot"]["name"],
                "bot": {"workspace_name": data["bot"]["workspace_name"]},
            }
        )
    if path == "/search" and request.method == "POST":
        body = request_json(request)
        query = str(body.get("query") or "")
        kind = ((body.get("filter") or {}).get("value")) or None
        results: list[dict[str, Any]] = []
        if kind in (None, "page"):
            results += [_notion_page(p, clock) for p in data["pages"] if words_match(query, p["title"])]
        if kind in (None, "database"):
            results += [_notion_db(d, clock) for d in data["databases"] if words_match(query, d["title"])]
        results.sort(key=lambda r: r["last_edited_time"], reverse=True)
        size = int(body.get("page_size") or 100)
        start = int(body.get("start_cursor") or 0)
        chunk = results[start : start + size]
        more = start + size < len(results)
        return json_response(
            {"object": "list", "results": chunk, "has_more": more, "next_cursor": str(start + size) if more else None}
        )
    if m := route(path, r"/pages/([^/]+)"):
        pid = unquote(m.group(1))
        if pid in pages:
            return json_response(_notion_page(pages[pid], clock))
        for db in data["databases"]:
            for row in db["rows"]:
                if row["id"] == pid:
                    return json_response(_notion_row(db, row, clock))
        return error_response(404, "object_not_found")
    if m := route(path, r"/blocks/([^/]+)/children"):
        bid = unquote(m.group(1))
        page = pages.get(bid)
        blocks: list[dict[str, Any]] = []
        if page is not None:
            for i, (btype, text) in enumerate(page["blocks"]):
                payload: dict[str, Any] = {"rich_text": _rich(text)}
                if btype == "to_do":
                    payload["checked"] = False
                blocks.append(
                    {"object": "block", "id": f"{bid}-b{i}", "type": btype, "has_children": False, btype: payload}
                )
            for child in data["pages"]:
                if child["parent"].get("id") == bid:
                    blocks.append(
                        {
                            "object": "block",
                            "id": child["id"],
                            "type": "child_page",
                            "has_children": True,
                            "child_page": {"title": child["title"]},
                        }
                    )
        else:
            for db in data["databases"]:
                for row in db["rows"]:
                    if row["id"] == bid:
                        text = f"Incidencia de {row['Cliente']}: {row['title']} (estado: {row['Estado']})."
                        blocks.append(
                            {
                                "object": "block",
                                "id": f"{bid}-b0",
                                "type": "paragraph",
                                "has_children": False,
                                "paragraph": {"rich_text": _rich(text)},
                            }
                        )
        return json_response({"object": "list", "results": blocks, "has_more": False, "next_cursor": None})
    if m := route(path, r"/databases/([^/]+)/query"):
        db = dbs[unquote(m.group(1))]
        rows = [_notion_row(db, r, clock) for r in db["rows"]]
        return json_response({"object": "list", "results": rows, "has_more": False, "next_cursor": None})
    if m := route(path, r"/databases/([^/]+)"):
        return json_response(_notion_db(dbs[unquote(m.group(1))], clock))
    return error_response(404, f"Ruta de Notion no emulada: {path}")


# ============================================================================= HubSpot

HS_MODIFIED = {"contacts": "lastmodifieddate", "companies": "hs_lastmodifieddate", "deals": "hs_lastmodifieddate"}


def _hs_records(obj: str, clock: DemoClock) -> list[dict[str, Any]]:
    data = fixture("hubspot")
    if obj not in ("contacts", "companies", "deals"):
        raise KeyError(obj)
    out = []
    for rec in data[obj]:
        when = iso(clock.at(rec["offset_min"]))
        out.append(_hs_record(obj, rec["id"], rec["properties"], when))
    if obj == "contacts":
        for k, when, tpl in clock.incoming(data["incoming_contacts"]):
            out.append(_hs_record(obj, str(6000 + k), tpl["properties"], iso(when)))
    return out


def _hs_record(obj: str, rid: str, props: dict[str, Any], when: str) -> dict[str, Any]:
    properties = {**props, "createdate": when, HS_MODIFIED[obj]: when, "hs_object_id": rid}
    return {"id": rid, "properties": properties, "createdAt": when, "updatedAt": when, "archived": False}


def _hs_filter(records: list[dict[str, Any]], body: dict[str, Any]) -> list[dict[str, Any]]:
    out = records
    query = str(body.get("query") or "")
    if query:
        out = [r for r in out if words_match(query, *[str(v) for v in r["properties"].values()])]
    groups = body.get("filterGroups") or []
    if groups:

        def ok(rec: dict[str, Any]) -> bool:
            for group in groups:
                if all(_hs_cond(rec, f) for f in group.get("filters", [])):
                    return True
            return False

        out = [r for r in out if ok(r)]
    for sort in reversed(body.get("sorts") or []):
        name = sort.get("propertyName") if isinstance(sort, dict) else str(sort)
        desc = isinstance(sort, dict) and sort.get("direction") == "DESCENDING"
        out = sorted(out, key=lambda r: str(r["properties"].get(name) or ""), reverse=desc)
    return out


def _hs_cond(rec: dict[str, Any], flt: dict[str, Any]) -> bool:
    value = rec["properties"].get(flt.get("propertyName"))
    target = flt.get("value")
    op = flt.get("operator")
    if flt.get("propertyName") in ("createdate", "lastmodifieddate", "hs_lastmodifieddate") and target is not None:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000 if value else 0
        target_n = float(target)
        return {
            "GT": stamp > target_n,
            "GTE": stamp >= target_n,
            "LT": stamp < target_n,
            "LTE": stamp <= target_n,
            "EQ": stamp == target_n,
        }.get(str(op), False)
    if op == "EQ":
        return str(value).lower() == str(target).lower()
    if op == "NEQ":
        return str(value).lower() != str(target).lower()
    if op == "CONTAINS_TOKEN":
        return str(target).lower().strip("*") in str(value).lower()
    if op == "HAS_PROPERTY":
        return value not in (None, "")
    return False


def hubspot_handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    path = request.url.path
    params = request.url.params
    if path == "/account-info/v3/details":
        portal = fixture("hubspot")["portal"]
        return json_response(
            {"portalId": portal["hub_id"], "uiDomain": "app-eu1.hubspot.com", "dataHostingLocation": "eu1"}
        )
    if m := route(path, r"/crm/v3/objects/(\w+)/search"):
        body = request_json(request)
        found = _hs_filter(_hs_records(m.group(1), clock), body)
        limit = int(body.get("limit") or 10)
        start = int(body.get("after") or 0)
        page = found[start : start + limit]
        paging = {"next": {"after": str(start + limit)}} if start + limit < len(found) else None
        return json_response({"total": len(found), "results": page, **({"paging": paging} if paging else {})})
    if m := route(path, r"/crm/v3/objects/(\w+)"):
        obj = m.group(1)
        if request.method == "POST":
            body = request_json(request)
            now = iso(clock.now)
            return json_response(_hs_record(obj, new_id("hs"), dict(body.get("properties") or {}), now), status=201)
        records = _hs_records(obj, clock)
        limit = int(params.get("limit", "10"))
        start = int(params.get("after", "0") or 0)
        page = records[start : start + limit]
        body_out: dict[str, Any] = {"results": page}
        if start + limit < len(records):
            body_out["paging"] = {"next": {"after": str(start + limit)}}
        return json_response(body_out)
    if m := route(path, r"/crm/v3/objects/(\w+)/([^/]+)"):
        obj, rid = m.group(1), unquote(m.group(2))
        records = {r["id"]: r for r in _hs_records(obj, clock)}
        if request.method == "PATCH":
            if rid not in records:
                return error_response(404, "Object not found")
            props = dict(request_json(request).get("properties") or {})
            rec = records[rid]
            return json_response({**rec, "properties": {**rec["properties"], **props}, "updatedAt": iso(clock.now)})
        if rid not in records:
            return error_response(404, "Object not found")
        return json_response(records[rid])
    return error_response(404, f"Ruta de HubSpot no emulada: {path}")


# ============================================================================= Salesforce

_SOQL_RE = re.compile(
    r"^\s*SELECT\s+(?P<fields>.+?)\s+FROM\s+(?P<obj>\w+)"
    r"(?:\s+WHERE\s+(?P<where>.+?))?"
    r"(?:\s+ORDER\s+BY\s+(?P<order>\w+)(?:\s+(?P<dir>ASC|DESC))?)?"
    r"(?:\s+LIMIT\s+(?P<limit>\d+))?(?:\s+OFFSET\s+(?P<offset>\d+))?\s*$",
    re.IGNORECASE | re.DOTALL,
)


def _sf_stamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _sf_records(obj: str, clock: DemoClock) -> list[dict[str, Any]]:
    data = fixture("salesforce")
    if obj not in data["objects"]:
        raise KeyError(obj)
    out = []
    for rec in data["objects"][obj]:
        when = _sf_stamp(clock.at(rec["offset_min"]))
        out.append(
            {
                **{k: v for k, v in rec.items() if k != "offset_min"},
                "CreatedDate": when,
                "LastModifiedDate": when,
                "SystemModstamp": when,
            }
        )
    if obj == "Lead":
        for k, when, tpl in clock.incoming(data["incoming_leads"]):
            stamp = _sf_stamp(when)
            out.append(
                {
                    **tpl,
                    "Id": f"00Q0000000IN{k + 1:04d}AAA",
                    "CreatedDate": stamp,
                    "LastModifiedDate": stamp,
                    "SystemModstamp": stamp,
                }
            )
    return out


def _sf_field_type(name: str) -> str:
    if name == "Id" or name.endswith("Id"):
        return "id" if name == "Id" else "reference"
    if name in ("CreatedDate", "LastModifiedDate", "SystemModstamp"):
        return "datetime"
    if name == "CloseDate":
        return "date"
    if name in ("Amount", "AnnualRevenue"):
        return "currency"
    if name == "Probability":
        return "percent"
    if name == "NumberOfEmployees":
        return "int"
    return "string"


def _sf_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("\\'", "'")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})", raw):
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if raw.lower() == "null":
        return None
    try:
        return float(raw)
    except ValueError:
        return raw


def _sf_compare(value: Any, op: str, target: Any) -> bool:
    if isinstance(target, datetime):
        if not value:
            return False
        value = datetime.fromisoformat(str(value).replace("+0000", "+00:00"))
    elif isinstance(target, float) and value is not None:
        value = float(value)
    elif isinstance(target, str):
        value = "" if value is None else str(value)
        if op.upper() == "LIKE":
            pattern = "^" + re.escape(target).replace("%", ".*").replace("_", ".") + "$"
            return re.match(pattern, value, re.IGNORECASE) is not None
    compare = {
        "=": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        ">=": operator.ge,
        "<": operator.lt,
        "<=": operator.le,
    }
    try:
        return bool(compare[op](value, target))
    except TypeError:
        return False


def _soql(query: str, clock: DemoClock) -> dict[str, Any]:
    m = _SOQL_RE.match(query)
    if m is None:
        raise ValueError("MALFORMED_QUERY")
    fields = [f.strip() for f in m.group("fields").split(",")]
    records = _sf_records(m.group("obj"), clock)
    if where := m.group("where"):
        for clause in re.split(r"\s+AND\s+", where, flags=re.IGNORECASE):
            cm = re.match(r"(\w+)\s*(!=|>=|<=|=|>|<|LIKE)\s*(.+)", clause.strip(), re.IGNORECASE)
            if cm is None:
                raise ValueError("MALFORMED_QUERY")
            field, op, raw = cm.group(1), cm.group(2), cm.group(3)
            target = _sf_value(raw)
            records = [r for r in records if _sf_compare(r.get(field), op if op.upper() != "LIKE" else "LIKE", target)]
    if order := m.group("order"):
        records.sort(key=lambda r: str(r.get(order) or ""), reverse=(m.group("dir") or "").upper() == "DESC")
    offset = int(m.group("offset") or 0)
    if m.group("limit"):
        records = records[offset : offset + int(m.group("limit"))]
    else:
        records = records[offset:]
    obj = m.group("obj")
    out = []
    for rec in records:
        row: dict[str, Any] = {
            "attributes": {"type": obj, "url": f"/services/data/v61.0/sobjects/{obj}/{rec.get('Id')}"}
        }
        for f in fields:
            if f.upper().startswith("COUNT("):
                continue
            row[f] = rec.get(f)
        out.append(row)
    return {"totalSize": len(out), "done": True, "records": out}


def salesforce_handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    path = request.url.path
    data = fixture("salesforce")
    if path == "/services/oauth2/userinfo":
        org = data["org"]
        return json_response({"preferred_username": org["user"], "organization_id": org["id"], "name": org["name"]})
    if path.startswith("/services/data/") and path.endswith("/query"):
        try:
            return json_response(_soql(request.url.params.get("q", ""), clock))
        except (ValueError, KeyError) as exc:
            return json_response(
                [{"errorCode": "MALFORMED_QUERY", "message": f"Consulta no válida en la demo: {exc}"}], status=400
            )
    if m := route(path, r"/services/data/v[\d.]+/sobjects/(\w+)/describe"):
        records = _sf_records(m.group(1), clock)
        names = sorted({k for r in records for k in r})
        return json_response(
            {
                "name": m.group(1),
                "fields": [{"name": n, "type": _sf_field_type(n), "label": n, "nillable": n != "Id"} for n in names],
            }
        )
    if m := route(path, r"/services/data/v[\d.]+/sobjects/(\w+)"):
        if request.method == "POST":
            return json_response({"id": new_id("sf"), "success": True, "errors": []}, status=201)
    if m := route(path, r"/services/data/v[\d.]+/sobjects/(\w+)/([^/]+)"):
        if request.method == "PATCH":
            return httpx.Response(204)
        records = {r["Id"]: r for r in _sf_records(m.group(1), clock)}
        rec = records.get(unquote(m.group(2)))
        if rec is None:
            return json_response(
                [{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}], status=404
            )
        return json_response({"attributes": {"type": m.group(1)}, **rec})
    return error_response(404, f"Ruta de Salesforce no emulada: {path}")
