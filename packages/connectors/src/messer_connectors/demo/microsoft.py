"""Fake Microsoft Graph (OneDrive, SharePoint, Outlook mail and calendar) backed by ``data/microsoft.json``."""

from __future__ import annotations

import re
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx

from ..base import ConnectionContext
from . import (
    DemoClock,
    error_response,
    file_bytes,
    fixture,
    iso,
    json_response,
    new_id,
    request_json,
    route,
    words_match,
)

GRAPH = "https://graph.microsoft.com/v1.0"


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _drive_item(drive_id: str, item: dict[str, Any], clock: DemoClock) -> dict[str, Any]:
    when = iso(clock.at(item["offset_min"]))
    out: dict[str, Any] = {
        "id": item["id"],
        "name": item["name"],
        "createdDateTime": when,
        "lastModifiedDateTime": when,
        "webUrl": f"https://albor.sharepoint.example/demo/{item['id']}",
        "eTag": f'"{zlib.crc32(f"{item['id']}:{when}".encode())},1"',
        "parentReference": {"driveId": drive_id, "id": item["parent"]},
    }
    if item.get("folder"):
        children = [i for i in fixture("microsoft")["drives"][drive_id]["items"] if i["parent"] == item["id"]]
        out["folder"] = {"childCount": len(children)}
    else:
        out["file"] = {"mimeType": item.get("mime", "application/octet-stream")}
        out["size"] = len(file_bytes(item["file"]))
    return out


def _drive(request: httpx.Request, drive_id: str, rest: str, clock: DemoClock) -> httpx.Response:
    drives = fixture("microsoft")["drives"]
    if drive_id not in drives:
        return error_response(404, "itemNotFound")
    items = drives[drive_id]["items"]
    by_id = {i["id"]: i for i in items}
    if rest in ("/root/children", "/root/children/"):
        parent = "root"
        return json_response({"value": [_drive_item(drive_id, i, clock) for i in items if i["parent"] == parent]})
    if m := route(rest, r"/items/([^/]+)/children"):
        parent = unquote(m.group(1))
        return json_response({"value": [_drive_item(drive_id, i, clock) for i in items if i["parent"] == parent]})
    if m := route(rest, r"/items/([^/]+)/content"):
        item = by_id[unquote(m.group(1))]
        return httpx.Response(200, content=file_bytes(item["file"]), headers={"Content-Type": item.get("mime", "")})
    if m := route(rest, r"/items/([^/]+)"):
        return json_response(_drive_item(drive_id, by_id[unquote(m.group(1))], clock))
    if m := route(rest, r"/root/search\(q='(.*)'\)"):
        term = unquote(m.group(1))
        found = [
            _drive_item(drive_id, i, clock)
            for i in items
            if not i.get("folder") and words_match(term, i["name"], file_bytes(i["file"]).decode("utf-8", "ignore"))
        ]
        return json_response({"value": found})
    if rest in ("", "/"):
        return json_response({"id": drive_id, "name": drives[drive_id]["name"], "driveType": "business"})
    return error_response(404, f"Ruta de unidad no emulada: {rest}")


def _messages(clock: DemoClock) -> list[dict[str, Any]]:
    data = fixture("microsoft")["mail"]
    # Graph timestamps have second precision.
    out = [{**m, "date": clock.at(m["offset_min"]).replace(microsecond=0)} for m in data["messages"]]
    for k, when, tpl in clock.incoming(data["incoming"]):
        out.append({**tpl, "id": f"olk-in-{k + 1:04d}", "date": when.replace(microsecond=0)})
    out.sort(key=lambda m: m["date"], reverse=True)
    return out


def _message_out(m: dict[str, Any], with_body: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": m["id"],
        "subject": m["subject"],
        "from": {"emailAddress": {"name": m["from"][0], "address": m["from"][1]}},
        "toRecipients": [{"emailAddress": {"address": a}} for a in m["to"]],
        "ccRecipients": [],
        "receivedDateTime": iso(m["date"]).replace(".000Z", "Z"),
        "bodyPreview": m["body"].replace("\n", " ")[:120],
        "isRead": False,
        "hasAttachments": False,
        "conversationId": f"conv-{m['id']}",
        "webLink": f"https://outlook.example/demo/{m['id']}",
    }
    if with_body:
        out["body"] = {"contentType": "text", "content": m["body"]}
    return out


def _mail(request: httpx.Request, rest: str, clock: DemoClock) -> httpx.Response:
    params = request.url.params
    messages = _messages(clock)
    if rest == "/sendMail" and request.method == "POST":
        return httpx.Response(202)
    if rest == "/messages" and request.method == "POST":
        body = request_json(request)
        return json_response(
            {**body, "id": new_id("olk-draft"), "isDraft": True, "webLink": "https://outlook.example/demo"}
        )
    if rest in ("/messages", "/mailFolders/inbox/messages"):
        found = messages
        if search := params.get("$search"):
            found = [m for m in found if words_match(search.strip('"'), m["subject"], m["body"], m["from"][1])]
        if flt := params.get("$filter"):
            if m := re.search(r"receivedDateTime gt (\S+)", flt):
                threshold = _ts(m.group(1))
                found = [msg for msg in found if msg["date"] > threshold]
        if "receivedDateTime asc" in params.get("$orderby", ""):
            found = sorted(found, key=lambda msg: msg["date"])
        return json_response({"value": [_message_out(msg, False) for msg in found[: int(params.get("$top", "25"))]]})
    if m := route(rest, r"/messages/([^/]+)"):
        msg = next((x for x in messages if x["id"] == m.group(1)), None)
        if msg is None:
            return error_response(404, "ErrorItemNotFound")
        return json_response(_message_out(msg, True))
    return error_response(404, f"Ruta de correo no emulada: {rest}")


def _calendar(request: httpx.Request, rest: str, clock: DemoClock) -> httpx.Response:
    params = request.url.params
    if rest == "/events" and request.method == "POST":
        body = request_json(request)
        return json_response({**body, "id": new_id("olk-evt"), "webLink": "https://outlook.example/demo/calendar"})
    if rest == "/calendarView":
        start_bound = _ts(params["startDateTime"]) if params.get("startDateTime") else clock.now
        end_bound = _ts(params["endDateTime"]) if params.get("endDateTime") else clock.now + timedelta(days=7)
        out = []
        for evt in fixture("microsoft")["events"]:
            start = clock.at(evt["offset_min"])
            end = start + timedelta(minutes=evt["duration_min"])
            if end < start_bound or start > end_bound:
                continue
            out.append(
                {
                    "id": evt["id"],
                    "subject": evt["subject"],
                    "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"},
                    "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S.0000000"), "timeZone": "UTC"},
                    "location": {"displayName": evt.get("location", "")},
                    "attendees": [
                        {"emailAddress": {"address": a}, "type": "required"} for a in evt.get("attendees", [])
                    ],
                    "webLink": f"https://outlook.example/demo/{evt['id']}",
                }
            )
        return json_response({"value": out})
    return error_response(404, f"Ruta de calendario no emulada: {rest}")


def handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    path = request.url.path.removeprefix("/v1.0")
    data = fixture("microsoft")
    if path == "/me":
        return json_response(data["user"])
    if path.startswith("/me/drive"):
        return _drive(request, "me", path.removeprefix("/me/drive"), clock)
    if m := route(path, r"/drives/([^/]+)(/.*)?"):
        return _drive(request, unquote(m.group(1)), m.group(2) or "", clock)
    if path == "/sites":
        search = request.url.params.get("search", "*")
        sites = [
            s for s in data["sites"] if search in ("*", "") or words_match(search, s["displayName"], s["description"])
        ]
        return json_response({"value": sites})
    if m := route(path, r"/sites/([^/]+)/drives"):
        site = unquote(m.group(1))
        drives = [
            {
                "id": drive_id,
                "name": d["name"],
                "driveType": "documentLibrary",
                "webUrl": f"https://albor.sharepoint.example/{drive_id}",
            }
            for drive_id, d in data["drives"].items()
            if d.get("site") == site
        ]
        return json_response({"value": drives})
    if path.startswith("/me/messages") or path.startswith("/me/mailFolders") or path == "/me/sendMail":
        return _mail(request, path.removeprefix("/me"), clock)
    if path in ("/me/calendarView", "/me/events"):
        return _calendar(request, path.removeprefix("/me"), clock)
    return error_response(404, f"Ruta de Graph no emulada: {path}")
