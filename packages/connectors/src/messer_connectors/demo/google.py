"""Fake Google Drive, Gmail and Calendar APIs backed by ``data/google.json`` (demo mode)."""

from __future__ import annotations

import base64
import re
import zlib
from datetime import UTC, datetime, timedelta
from email import message_from_bytes
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

FOLDER = "application/vnd.google-apps.folder"


# ----------------------------------------------------------------------------- Drive


def drive_items(clock: DemoClock) -> list[dict[str, Any]]:
    data = fixture("google")["drive"]
    items: list[dict[str, Any]] = []
    for item in data["items"]:
        when = clock.at(item["offset_min"])
        items.append({**item, "createdTime": iso(when), "modifiedTime": iso(when)})
    for k, when, tpl in clock.incoming(data["incoming"]):
        items.append(
            {
                **tpl,
                "id": f"incoming-file-{k + 1}",
                "name": f"{tpl['name']} {when.strftime('%d-%m-%Y %H:%M')}",
                "createdTime": iso(when),
                "modifiedTime": iso(when),
            }
        )
    return items


def _drive_meta(item: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": item["id"],
        "name": item["name"],
        "mimeType": item["mimeType"],
        "parents": [item["parent"]],
        "createdTime": item["createdTime"],
        "modifiedTime": item["modifiedTime"],
        "version": str(zlib.crc32(f"{item['id']}:{item['modifiedTime']}".encode())),
        "webViewLink": f"https://drive.example/demo/{item['id']}",
        "trashed": False,
    }
    if item.get("file") and not item["mimeType"].startswith("application/vnd.google-apps"):
        out["size"] = str(len(file_bytes(item["file"])))
    return out


def _ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


_CLAUSE_RE = re.compile(r"\s+and\s+", re.IGNORECASE)


def _drive_filter(q: str) -> list[tuple[str, str, str]]:
    clauses: list[tuple[str, str, str]] = []
    for raw in _CLAUSE_RE.split(q.strip()) if q.strip() else []:
        part = raw.strip().strip("()")
        if m := re.fullmatch(r"'([^']+)'\s+in\s+parents", part):
            clauses.append(("parent", "=", m.group(1)))
        elif m := re.fullmatch(r"(\w+)\s*(=|!=|>|>=|<|contains)\s*'([^']*)'", part):
            clauses.append((m.group(1), m.group(2), m.group(3)))
        elif m := re.fullmatch(r"trashed\s*=\s*(true|false)", part):
            clauses.append(("trashed", "=", m.group(1)))
    return clauses


def _drive_matches(item: dict[str, Any], clauses: list[tuple[str, str, str]]) -> bool:
    for field, op, value in clauses:
        if field == "parent":
            if item["parent"] != value:
                return False
        elif field == "trashed":
            if value == "true":
                return False
        elif field in ("mimeType", "name"):
            current = str(item[field])
            if op == "=" and current != value:
                return False
            if op == "!=" and current == value:
                return False
            if op == "contains" and value.lower() not in current.lower():
                return False
        elif field == "fullText":
            body = file_bytes(item["file"]).decode("utf-8", "ignore") if item.get("file") else ""
            if not words_match(value, item["name"], body):
                return False
        elif field in ("createdTime", "modifiedTime"):
            current, threshold = _ts(item[field]), _ts(value)
            if op == ">" and not current > threshold:
                return False
            if op == ">=" and not current >= threshold:
                return False
    return True


def _drive(request: httpx.Request, path: str, clock: DemoClock) -> httpx.Response:
    items = drive_items(clock)
    by_id = {i["id"]: i for i in items}
    params = request.url.params
    if path == "/drive/v3/about":
        user = fixture("google")["user"]
        return json_response({"user": {"displayName": user["name"], "emailAddress": user["email"]}})
    if path == "/drive/v3/files":
        clauses = _drive_filter(params.get("q", ""))
        found = [_drive_meta(i) for i in items if _drive_matches(i, clauses)]
        order = params.get("orderBy", "")
        if order.startswith("createdTime"):
            found.sort(key=lambda f: f["createdTime"])
        elif order.startswith("modifiedTime"):
            found.sort(key=lambda f: f["modifiedTime"], reverse="desc" in order)
        else:
            found.sort(key=lambda f: (f["mimeType"] != FOLDER, f["name"].lower()))
        size = int(params.get("pageSize", "100"))
        start = int(params.get("pageToken", "0") or 0)
        page = found[start : start + size]
        body: dict[str, Any] = {"files": page}
        if start + size < len(found):
            body["nextPageToken"] = str(start + size)
        return json_response(body)
    if m := route(path, r"/drive/v3/files/([^/]+)/export"):
        item = by_id[unquote(m.group(1))]
        if not item.get("file"):
            return error_response(400, "Export not supported for this file")
        mime = params.get("mimeType", "text/plain")
        return httpx.Response(200, content=file_bytes(item["file"]), headers={"Content-Type": mime})
    if m := route(path, r"/drive/v3/files/([^/]+)"):
        item = by_id[unquote(m.group(1))]
        if params.get("alt") == "media":
            if item["mimeType"].startswith("application/vnd.google-apps"):
                return error_response(403, "Only files with binary content can be downloaded. Use Export.")
            return httpx.Response(200, content=file_bytes(item["file"]), headers={"Content-Type": item["mimeType"]})
        return json_response(_drive_meta(item))
    return error_response(404, f"Ruta de Drive no emulada: {path}")


# ----------------------------------------------------------------------------- Gmail


def gmail_messages(clock: DemoClock) -> list[dict[str, Any]]:
    data = fixture("google")["gmail"]
    out: list[dict[str, Any]] = []
    for msg in data["messages"]:
        out.append({**msg, "date": clock.at(msg["offset_min"])})
    for k, when, tpl in clock.incoming(data["incoming"]):
        out.append(
            {
                **tpl,
                "id": f"msg-in-{k + 1:04d}",
                "threadId": f"thr-in-{k + 1:04d}",
                "date": when,
                "labels": ["INBOX", "UNREAD"],
            }
        )
    out.sort(key=lambda m: m["date"], reverse=True)
    return out


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _gmail_resource(msg: dict[str, Any], fmt: str) -> dict[str, Any]:
    date: datetime = msg["date"]
    headers = [
        {"name": "From", "value": msg["from"]},
        {"name": "To", "value": msg["to"]},
        {"name": "Subject", "value": msg["subject"]},
        {"name": "Date", "value": date.strftime("%a, %d %b %Y %H:%M:%S +0000")},
    ]
    resource: dict[str, Any] = {
        "id": msg["id"],
        "threadId": msg["threadId"],
        "labelIds": msg.get("labels", []),
        "snippet": msg["body"].replace("\n", " ")[:120],
        "internalDate": str(int(date.timestamp() * 1000)),
        "sizeEstimate": len(msg["body"]) + 400,
        "payload": {"mimeType": "text/plain", "headers": headers},
    }
    if fmt == "full":
        resource["payload"] = {
            "mimeType": "multipart/alternative",
            "headers": headers,
            "parts": [
                {
                    "partId": "0",
                    "mimeType": "text/plain",
                    "body": {"size": len(msg["body"]), "data": _b64(msg["body"])},
                },
            ],
        }
    return resource


def _gmail_query(messages: list[dict[str, Any]], q: str) -> list[dict[str, Any]]:
    out = messages
    terms: list[str] = []
    for token in q.split():
        lowered = token.lower()
        if lowered == "in:inbox":
            out = [m for m in out if "INBOX" in m.get("labels", [])]
        elif lowered == "is:unread":
            out = [m for m in out if "UNREAD" in m.get("labels", [])]
        elif lowered.startswith("after:"):
            value = lowered[6:]
            if value.isdigit():
                threshold = int(value)
                out = [m for m in out if m["date"].timestamp() > threshold]
        elif lowered.startswith("from:"):
            needle = lowered[5:]
            out = [m for m in out if needle in m["from"].lower()]
        else:
            terms.append(token)
    if terms:
        query = " ".join(terms)
        out = [m for m in out if words_match(query, m["subject"], m["body"], m["from"])]
    return out


def _gmail(request: httpx.Request, path: str, clock: DemoClock) -> httpx.Response:
    params = request.url.params
    messages = gmail_messages(clock)
    by_id = {m["id"]: m for m in messages}
    user = fixture("google")["user"]
    if path == "/gmail/v1/users/me/profile":
        return json_response({"emailAddress": user["email"], "messagesTotal": len(messages), "historyId": "1000"})
    if path == "/gmail/v1/users/me/messages" and request.method == "GET":
        found = _gmail_query(messages, params.get("q", ""))
        limit = int(params.get("maxResults", "20"))
        return json_response(
            {
                "messages": [{"id": m["id"], "threadId": m["threadId"]} for m in found[:limit]],
                "resultSizeEstimate": len(found),
            }
        )
    if m := route(path, r"/gmail/v1/users/me/messages/([^/]+)"):
        if m.group(1) == "send" and request.method == "POST":
            raw = request_json(request).get("raw", "")
            parsed = message_from_bytes(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
            return json_response(
                {"id": new_id("sent"), "threadId": new_id("thr"), "labelIds": ["SENT"], "to": parsed["To"]}
            )
        msg = by_id[m.group(1)]
        return json_response(_gmail_resource(msg, params.get("format", "full")))
    if path == "/gmail/v1/users/me/drafts" and request.method == "POST":
        return json_response({"id": new_id("draft"), "message": {"id": new_id("msg"), "labelIds": ["DRAFT"]}})
    if path == "/gmail/v1/users/me/drafts/send" and request.method == "POST":
        return json_response({"id": new_id("sent"), "threadId": new_id("thr"), "labelIds": ["SENT"]})
    return error_response(404, f"Ruta de Gmail no emulada: {path}")


# ----------------------------------------------------------------------------- Calendar


def _calendar(request: httpx.Request, path: str, clock: DemoClock) -> httpx.Response:
    data = fixture("google")["calendar"]
    if path == "/calendar/v3/users/me/calendarList":
        return json_response({"items": data["calendars"]})
    if m := route(path, r"/calendar/v3/calendars/([^/]+)/events"):
        calendar_id = unquote(m.group(1))
        if request.method == "POST":
            body = request_json(request)
            return json_response(
                {
                    **body,
                    "id": new_id("evt"),
                    "status": "confirmed",
                    "htmlLink": "https://calendar.example/demo",
                    "organizer": {"email": fixture("google")["user"]["email"], "self": True},
                }
            )
        params = request.url.params
        items = []
        for evt in data["events"]:
            if evt["calendarId"] != calendar_id and not (calendar_id == "primary" and evt["calendarId"] == "primary"):
                continue
            start = clock.at(evt["offset_min"])
            end = start + timedelta(minutes=evt["duration_min"])
            if params.get("timeMin") and end < _ts(params["timeMin"]):
                continue
            if params.get("timeMax") and start > _ts(params["timeMax"]):
                continue
            if params.get("q") and not words_match(params["q"], evt["summary"], evt.get("location")):
                continue
            items.append(
                {
                    "id": evt["id"],
                    "status": "confirmed",
                    "summary": evt["summary"],
                    "location": evt.get("location"),
                    "start": {"dateTime": iso(start), "timeZone": "Europe/Madrid"},
                    "end": {"dateTime": iso(end), "timeZone": "Europe/Madrid"},
                    "attendees": [{"email": a} for a in evt.get("attendees", [])],
                    "htmlLink": f"https://calendar.example/demo/{evt['id']}",
                }
            )
        items.sort(key=lambda e: e["start"]["dateTime"])
        return json_response({"items": items[: int(params.get("maxResults", "50"))]})
    return error_response(404, f"Ruta de Calendar no emulada: {path}")


def handler(request: httpx.Request, clock: DemoClock, ctx: ConnectionContext) -> httpx.Response:
    path = request.url.path
    if path.startswith("/drive/"):
        return _drive(request, path, clock)
    if path.startswith("/gmail/"):
        return _gmail(request, path, clock)
    if path.startswith("/calendar/"):
        return _calendar(request, path, clock)
    if path == "/oauth2/v3/userinfo":
        user = fixture("google")["user"]
        return json_response({"email": user["email"], "name": user["name"]})
    return error_response(404, f"Ruta de Google no emulada: {path}")
