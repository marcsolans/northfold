"""Provider webhooks (signatures, parsing, idempotency) and replies through each provider's API (mocked HTTP)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import select

from messer_common.channels import http as channels_http
from messer_common.channels import processing, teams
from messer_common.channels.base import ReplyTarget, SendError
from messer_common.channels.context import channel_context
from messer_common.channels.whatsapp import WhatsAppAdapter
from messer_common.db import system_session
from messer_common.db.models import Channel
from messer_common.db.models.channels import ChannelMessage
from messer_common.email import ConsoleEmailAdapter
from messer_common.settings import get_settings
from messer_runtime.testing import Harness

Handler = Callable[[httpx.Request], httpx.Response]


class FakeProviders:
    """Mock of every provider API: register handlers by URL prefix; every request is recorded."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.routes: list[tuple[str, str, Handler]] = []

    def on(self, method: str, prefix: str, handler: Handler | dict[str, Any]) -> None:
        fn: Handler = handler if callable(handler) else (lambda _r, body=handler: httpx.Response(200, json=body))
        self.routes.insert(0, (method, prefix, fn))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        for method, prefix, fn in self.routes:
            if request.method == method and str(request.url).startswith(prefix):
                return fn(request)
        return httpx.Response(404, json={"error": f"no mock for {request.method} {request.url}"})

    def sent(self, prefix: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if str(r.url).startswith(prefix) and r.content]


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> FakeProviders:
    fake = FakeProviders()
    monkeypatch.setattr(channels_http, "transport", httpx.MockTransport(fake))
    teams.reset_caches()
    return fake


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    jobs: list[str] = []

    async def fake_enqueue(job: str, *args: Any, **kwargs: Any) -> None:
        jobs.append(str(args[0]))

    monkeypatch.setattr(processing, "enqueue", fake_enqueue)
    return jobs


async def signup_project(client: httpx.AsyncClient) -> str:
    res = await client.post(
        "/api/v1/auth/signup", json={"email": "pau@acme.example", "password": "Contrasena123", "name": "Pau"}
    )
    assert res.status_code == 200, res.text
    pid = (await client.post("/api/v1/projects", json={"name": "Soporte"})).json()["id"]
    assert (await client.post(f"/api/v1/projects/{pid}/workforce", json={"name": "soporte"})).status_code in (200, 201)
    return str(pid)


async def connect(client: httpx.AsyncClient, pid: str, body: dict[str, Any]) -> dict[str, Any]:
    res = await client.post(f"/api/v1/projects/{pid}/channels", json={"workforce": "soporte", **body})
    assert res.status_code == 201, res.text
    return res.json()


async def inbound_rows(channel_id: str) -> list[ChannelMessage]:
    async with system_session() as s:
        return list(
            (
                await s.execute(
                    select(ChannelMessage)
                    .where(ChannelMessage.channel_id == uuid.UUID(channel_id), ChannelMessage.direction == "inbound")
                    .order_by(ChannelMessage.created_at)
                )
            )
            .scalars()
            .all()
        )


async def reply_to(row: ChannelMessage, text: str) -> dict[str, Any]:
    assert row.conversation_id is not None
    result = {"status": "success", "run_id": uuid.uuid4().hex, "output": {"content": [{"type": "text", "text": text}]}}
    return await processing.deliver(row.channel_id, row.conversation_id, result, inbound_id=row.id)


# =============================================================================================== WhatsApp


def wa_payload(message_id: str = "wamid.1", text: str = "Hola", number: str = "1234567890") -> dict[str, Any]:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {"display_phone_number": "34910000000", "phone_number_id": number},
                            "contacts": [{"profile": {"name": "Lucía"}, "wa_id": "34600111222"}],
                            "messages": [
                                {
                                    "from": "34600111222",
                                    "id": message_id,
                                    "timestamp": str(int(time.time())),
                                    "type": "text",
                                    "text": {"body": text},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def wa_signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def live_whatsapp(
    client: httpx.AsyncClient, providers: FakeProviders, pid: str, environment: str = "production"
) -> dict[str, Any]:
    providers.on(
        "GET",
        "https://graph.facebook.com/v21.0/1234567890",
        {"display_phone_number": "+34 910 000 000", "verified_name": "Acme", "id": "1234567890"},
    )
    channel = await connect(
        client,
        pid,
        {
            "provider": "whatsapp",
            "environment": environment,
            "credentials": {"access_token": "EAAG-test", "app_secret": "app-secret"},
            "config": {"phone_number_id": "1234567890"},
        },
    )
    assert channel["demo"] is False and channel["status"] == "active", channel
    assert channel["config"]["display_phone_number"] == "+34 910 000 000"
    assert channel["credentials_set"] == ["access_token", "app_secret"]
    assert "EAAG-test" not in json.dumps(channel)
    return channel


async def test_whatsapp_live_webhook_runs_agent_and_replies(
    client: httpx.AsyncClient, runtime: Harness, providers: FakeProviders, queued: list[str]
) -> None:
    from messer_worker.jobs.channels import channel_inbound

    pid = await signup_project(client)
    channel = await live_whatsapp(client, providers, pid, environment="development")
    url = f"/api/channels/{channel['id']}/whatsapp"

    # Meta's verification handshake uses the channel's webhook secret as verify token.
    ok = await client.get(
        url, params={"hub.mode": "subscribe", "hub.verify_token": channel["webhook_secret"], "hub.challenge": "42"}
    )
    assert ok.status_code == 200 and ok.text == "42"
    bad = await client.get(url, params={"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "1"})
    assert bad.status_code == 403

    sent_ids = iter(["wamid.out1", "wamid.out2"])
    providers.on(
        "POST",
        "https://graph.facebook.com/v21.0/1234567890/messages",
        lambda _r: httpx.Response(200, json={"messages": [{"id": next(sent_ids)}]}),
    )
    body = json.dumps(wa_payload(text="Hola, necesito mi factura")).encode()
    res = await client.post(
        url,
        content=body,
        headers={"X-Hub-Signature-256": wa_signature("app-secret", body), "Content-Type": "application/json"},
    )
    assert res.status_code == 200, res.text
    assert len(queued) == 1
    # Meta retries the same delivery: recorded once, queued again only while still waiting.
    again = await client.post(
        url,
        content=body,
        headers={"X-Hub-Signature-256": wa_signature("app-secret", body), "Content-Type": "application/json"},
    )
    assert again.status_code == 200 and len(await inbound_rows(channel["id"])) == 1

    result = await channel_inbound({"job_try": 1}, queued[0])
    assert result["status"] == "processed" and result["delivery"]["status"] == "sent", result
    [sent] = providers.sent("https://graph.facebook.com/v21.0/1234567890/messages")
    assert sent["to"] == "34600111222" and sent["type"] == "text" and sent["text"]["body"]
    auth = next(r for r in providers.requests if r.url.path.endswith("/messages")).headers["authorization"]
    assert auth == "Bearer EAAG-test"
    rows = await inbound_rows(channel["id"])
    assert rows[0].status == "processed" and rows[0].sender_name == "Lucía" and rows[0].run_id is not None

    # A live production channel of a project that is not deployed fails clearly (no silent fallback) and the
    # user gets the channel's error notice.
    patched = await client.patch(f"/api/v1/channels/{channel['id']}", json={"environment": "production"})
    assert patched.status_code == 200 and patched.json()["development_fallback"] is False
    body = json.dumps(wa_payload(message_id="wamid.2", text="¿Sigues ahí?")).encode()
    await client.post(
        url,
        content=body,
        headers={"X-Hub-Signature-256": wa_signature("app-secret", body), "Content-Type": "application/json"},
    )
    failed = await channel_inbound({"job_try": 1}, queued[-1])
    assert failed["status"] == "failed" and failed["error"] == "not_deployed", failed
    notice = providers.sent("https://graph.facebook.com/v21.0/1234567890/messages")[-1]
    assert notice["text"]["body"].startswith("Lo siento")
    rows = await inbound_rows(channel["id"])
    assert rows[-1].status == "failed" and rows[-1].error_code == "not_deployed"
    conv = (await client.get(f"/api/v1/conversations/{rows[-1].conversation_id}")).json()
    assert conv["messages"][-2]["error"]["code"] == "not_deployed"
    assert conv["messages"][-1]["notice"] == "error" and conv["messages"][-1]["delivery"]["status"] == "sent"


async def test_whatsapp_signature_and_payload_rules(
    client: httpx.AsyncClient, providers: FakeProviders, queued: list[str]
) -> None:
    pid = await signup_project(client)
    channel = await live_whatsapp(client, providers, pid)
    url = f"/api/channels/{channel['id']}/whatsapp"
    body = json.dumps(wa_payload()).encode()
    headers = {"Content-Type": "application/json"}
    assert (await client.post(url, content=body, headers=headers)).status_code == 401
    forged = await client.post(url, content=body, headers={**headers, "X-Hub-Signature-256": wa_signature("x", body)})
    assert forged.status_code == 401 and forged.json()["error"]["code"] == "invalid_signature"
    tampered = body.replace(b"Hola", b"Adios")
    bad = await client.post(
        url, content=tampered, headers={**headers, "X-Hub-Signature-256": wa_signature("app-secret", body)}
    )
    assert bad.status_code == 401
    assert queued == []

    statuses = json.dumps(
        {
            "object": "whatsapp_business_account",
            "entry": [
                {"changes": [{"field": "messages", "value": {"statuses": [{"id": "wamid.x", "status": "read"}]}}]}
            ],
        }
    ).encode()
    res = await client.post(
        url, content=statuses, headers={**headers, "X-Hub-Signature-256": wa_signature("app-secret", statuses)}
    )
    assert res.status_code == 200 and queued == []  # delivery receipts are ignored
    other_number = json.dumps(wa_payload(number="999")).encode()
    await client.post(
        url, content=other_number, headers={**headers, "X-Hub-Signature-256": wa_signature("app-secret", other_number)}
    )
    assert queued == []
    image = wa_payload(message_id="wamid.img")
    image["entry"][0]["changes"][0]["value"]["messages"][0] = {
        "from": "34600111222",
        "id": "wamid.img",
        "timestamp": "1700000000",
        "type": "image",
        "image": {"id": "media-1", "mime_type": "image/jpeg", "caption": "La factura"},
    }
    raw = json.dumps(image).encode()
    await client.post(url, content=raw, headers={**headers, "X-Hub-Signature-256": wa_signature("app-secret", raw)})
    [row] = await inbound_rows(channel["id"])
    assert row.text == "[Imagen] La factura" and row.kind == "media"
    assert row.payload["attachments"][0]["id"] == "media-1"

    # Demo channels have no app secret: they accept only calls carrying the channel token.
    demo = await connect(client, pid, {"provider": "whatsapp", "name": "Demo"})
    demo_url = f"/api/channels/{demo['id']}/whatsapp"
    payload = json.dumps(wa_payload(message_id="wamid.demo")).encode()
    assert (await client.post(demo_url, content=payload, headers=headers)).status_code == 401
    accepted = await client.post(demo_url, params={"token": demo["webhook_secret"]}, content=payload, headers=headers)
    assert accepted.status_code == 200 and len(await inbound_rows(demo["id"])) == 1


async def test_whatsapp_24h_window_requires_template(providers: FakeProviders, make_org) -> None:  # type: ignore[no-untyped-def]
    from messer_common.channels.base import ChannelContext

    adapter = WhatsAppAdapter()
    org, _ = await make_org()
    ctx = ChannelContext(
        channel_id=uuid.uuid4(),
        org_id=org.id,
        project_id=uuid.uuid4(),
        provider="whatsapp",
        credentials={"access_token": "t", "app_secret": "s"},
        config={"phone_number_id": "1234567890"},
        webhook_secret=None,
        demo=False,
        webhook_url="https://x",
    )
    old = ReplyTarget(
        conversation_key="34600", reply={"to": "34600"}, last_inbound_at=datetime.now(UTC) - timedelta(hours=25)
    )
    with pytest.raises(SendError) as err:
        await adapter.send_text(ctx, old, "Tu nota de abono está aprobada")
    assert err.value.code == "whatsapp_window_closed"
    providers.on("POST", "https://graph.facebook.com/v21.0/1234567890/messages", {"messages": [{"id": "wamid.tpl"}]})
    ctx.config["template"] = {"name": "respuesta_pendiente", "language": "es", "body_parameter": True}
    ids = await adapter.send_text(ctx, old, "Tu nota de abono\n\nestá aprobada")
    assert ids == ["wamid.tpl"]
    [body] = providers.sent("https://graph.facebook.com")
    assert body["type"] == "template" and body["template"]["name"] == "respuesta_pendiente"
    assert body["template"]["components"][0]["parameters"][0]["text"] == "Tu nota de abono está aprobada"

    # Inside the window, Meta's re-engagement error falls back to the template too.
    providers.requests.clear()
    calls = {"n": 0}

    def reengage(_r: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(400, json={"error": {"code": 131047, "message": "Re-engagement message"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.tpl2"}]})

    providers.on("POST", "https://graph.facebook.com/v21.0/1234567890/messages", reengage)
    fresh = ReplyTarget(conversation_key="34600", reply={"to": "34600"}, last_inbound_at=datetime.now(UTC))
    assert await adapter.send_text(ctx, fresh, "Hola") == ["wamid.tpl2"]
    assert [b["type"] for b in providers.sent("https://graph.facebook.com")] == ["text", "template"]

    providers.on(
        "POST",
        "https://graph.facebook.com/v21.0/1234567890/messages",
        lambda _r: httpx.Response(401, json={"error": {"code": 190, "message": "Token expired"}}),
    )
    with pytest.raises(SendError) as auth:
        await adapter.send_text(ctx, fresh, "Hola")
    assert auth.value.auth is True


# ================================================================================================== Slack


def slack_headers(secret: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    ts = int(time.time()) if ts is None else ts
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{ts}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": str(ts), "X-Slack-Signature": sig, "Content-Type": "application/json"}


def slack_event(event: dict[str, Any], event_id: str = "Ev1") -> bytes:
    return json.dumps(
        {
            "type": "event_callback",
            "team_id": "T1",
            "event_id": event_id,
            "event": event,
            "authorizations": [{"user_id": "UBOT", "is_bot": True}],
        }
    ).encode()


async def test_slack_events_threads_and_replies(
    client: httpx.AsyncClient, providers: FakeProviders, queued: list[str]
) -> None:
    pid = await signup_project(client)
    providers.on(
        "POST",
        "https://slack.com/api/auth.test",
        {"ok": True, "user_id": "UBOT", "team_id": "T1", "team": "Acme", "user": "messer"},
    )
    channel = await connect(
        client, pid, {"provider": "slack", "credentials": {"bot_token": "xoxb-1", "signing_secret": "sign"}}
    )
    assert channel["status"] == "active" and channel["config"]["bot_user_id"] == "UBOT"
    url = f"/api/channels/{channel['id']}/slack"

    challenge = json.dumps({"type": "url_verification", "challenge": "abc"}).encode()
    res = await client.post(url, content=challenge, headers=slack_headers("sign", challenge))
    assert res.status_code == 200 and res.json() == {"challenge": "abc"}
    stale = await client.post(
        url, content=challenge, headers=slack_headers("sign", challenge, ts=int(time.time()) - 600)
    )
    assert stale.status_code == 401
    forged = await client.post(url, content=challenge, headers=slack_headers("other", challenge))
    assert forged.status_code == 401

    mention = slack_event(
        {"type": "app_mention", "user": "U1", "text": "<@UBOT> ¿Mi factura 12?", "ts": "100.1", "channel": "C1"}
    )
    assert (await client.post(url, content=mention, headers=slack_headers("sign", mention))).status_code == 200
    # Slack also delivers the same post as a message event and may retry: processed once.
    dup = slack_event(
        {"type": "app_mention", "user": "U1", "text": "<@UBOT> ¿Mi factura 12?", "ts": "100.1", "channel": "C1"}, "Ev2"
    )
    retry_headers = {**slack_headers("sign", dup), "X-Slack-Retry-Num": "1", "X-Slack-Retry-Reason": "http_timeout"}
    await client.post(url, content=dup, headers=retry_headers)
    bot = slack_event(
        {
            "type": "message",
            "bot_id": "B1",
            "user": "UBOT",
            "text": "eco",
            "ts": "100.2",
            "channel": "C1",
            "thread_ts": "100.1",
        }
    )
    await client.post(url, content=bot, headers=slack_headers("sign", bot))
    stranger = slack_event(
        {
            "type": "message",
            "channel_type": "channel",
            "user": "U2",
            "text": "otro hilo",
            "ts": "200.2",
            "channel": "C1",
            "thread_ts": "200.1",
        }
    )
    await client.post(url, content=stranger, headers=slack_headers("sign", stranger))
    reply_in_thread = slack_event(
        {
            "type": "message",
            "channel_type": "channel",
            "user": "U1",
            "text": "¿Y la 13?",
            "ts": "100.3",
            "channel": "C1",
            "thread_ts": "100.1",
        }
    )
    await client.post(url, content=reply_in_thread, headers=slack_headers("sign", reply_in_thread))
    dm = slack_event(
        {
            "type": "message",
            "channel_type": "im",
            "user": "U3",
            "text": "Hola por privado",
            "ts": "300.1",
            "channel": "D1",
        }
    )
    await client.post(url, content=dm, headers=slack_headers("sign", dm))

    rows = await inbound_rows(channel["id"])
    assert [r.text for r in rows] == ["¿Mi factura 12?", "¿Y la 13?", "Hola por privado"]
    assert rows[0].conversation_id == rows[1].conversation_id != rows[2].conversation_id
    assert rows[0].payload["conversation_key"] == "thread:C1:100.1"

    providers.on("POST", "https://slack.com/api/chat.postMessage", {"ok": True, "channel": "C1", "ts": "100.9"})
    delivery = await reply_to(rows[1], "La factura **13** vence el *30*. Ver [detalle](https://acme.example/f/13)")
    assert delivery["status"] == "sent"
    [post] = providers.sent("https://slack.com/api/chat.postMessage")
    assert post["channel"] == "C1" and post["thread_ts"] == "100.1"
    assert post["text"] == "La factura *13* vence el _30_. Ver <https://acme.example/f/13|detalle>"

    providers.on("POST", "https://slack.com/api/chat.postMessage", {"ok": False, "error": "invalid_auth"})
    failed = await reply_to(rows[2], "Hola")
    assert failed["status"] == "failed" and failed["error"] == "auth_failed"
    detail = (await client.get(f"/api/v1/channels/{channel['id']}")).json()
    assert detail["status"] == "error" and "invalid_auth" in detail["error"]


# ================================================================================================ Telegram


async def test_telegram_set_webhook_secret_and_long_replies(
    client: httpx.AsyncClient, providers: FakeProviders, queued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await signup_project(client)
    # Telegram only accepts public HTTPS webhooks.
    monkeypatch.setattr(get_settings(), "messer_web_url", "https://app.messer.example")
    base = "https://api.telegram.org/bot123:ABC"
    providers.on("POST", f"{base}/setWebhook", {"ok": True, "result": True})
    providers.on("POST", f"{base}/getMe", {"ok": True, "result": {"id": 1, "username": "acme_bot"}})
    providers.on("POST", f"{base}/getWebhookInfo", {"ok": True, "result": {"url": "", "pending_update_count": 0}})
    channel = await connect(client, pid, {"provider": "telegram", "credentials": {"bot_token": "123:ABC"}})
    assert channel["status"] == "active" and channel["config"]["bot_username"] == "acme_bot", channel
    [hook] = providers.sent(f"{base}/setWebhook")
    assert hook["url"] == f"https://app.messer.example/api/channels/{channel['id']}/telegram"
    assert hook["secret_token"] == channel["webhook_secret"]

    url = f"/api/channels/{channel['id']}/telegram"
    update = {
        "update_id": 1,
        "message": {
            "message_id": 5,
            "from": {"id": 9, "first_name": "Iker"},
            "chat": {"id": 9, "type": "private"},
            "date": 1700000000,
            "text": "/start",
        },
    }
    assert (
        await client.post(url, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    ).status_code == 401
    assert (await client.post(url, json=update)).status_code == 401
    secret = {"X-Telegram-Bot-Api-Secret-Token": channel["webhook_secret"]}
    assert (await client.post(url, json=update, headers=secret)).status_code == 200
    group = {
        "update_id": 2,
        "message": {"message_id": 6, "from": {"id": 9}, "chat": {"id": -5, "type": "group"}, "text": "sin mención"},
    }
    await client.post(url, json=group, headers=secret)
    from_bot = {
        "update_id": 3,
        "message": {
            "message_id": 7,
            "from": {"id": 2, "is_bot": True},
            "chat": {"id": 9, "type": "private"},
            "text": "x",
        },
    }
    await client.post(url, json=from_bot, headers=secret)
    mentioned = {
        "update_id": 4,
        "message": {
            "message_id": 8,
            "from": {"id": 9},
            "chat": {"id": -5, "type": "group"},
            "text": "@acme_bot ¿factura?",
        },
    }
    await client.post(url, json=mentioned, headers=secret)
    rows = await inbound_rows(channel["id"])
    assert [r.text for r in rows] == ["Hola", "¿factura?"]
    assert rows[0].sender_name == "Iker"

    providers.on(
        "POST",
        f"{base}/sendMessage",
        lambda r: httpx.Response(200, json={"ok": True, "result": {"message_id": len(providers.requests)}}),
    )
    long_answer = ("Línea de detalle de la factura con importe y vencimiento. " * 200).strip()
    delivery = await reply_to(rows[0], long_answer)
    assert delivery["status"] == "sent" and delivery["parts"] == 3
    sent = providers.sent(f"{base}/sendMessage")
    assert len(sent) == 3 and all(len(m["text"]) <= 4096 for m in sent) and sent[0]["chat_id"] == 9
    group_reply = await reply_to(rows[1], "Sí")
    assert group_reply["status"] == "sent"
    assert providers.sent(f"{base}/sendMessage")[-1]["reply_parameters"]["message_id"] == 8

    providers.on("POST", f"{base}/deleteWebhook", {"ok": True, "result": True})
    assert (await client.delete(f"/api/v1/channels/{channel['id']}")).status_code == 204
    assert providers.sent(f"{base}/deleteWebhook")


async def test_telegram_requires_public_https_url(client: httpx.AsyncClient, providers: FakeProviders) -> None:
    pid = await signup_project(client)
    channel = await connect(client, pid, {"provider": "telegram", "credentials": {"bot_token": "123:ABC"}})
    assert channel["status"] == "error" and "HTTPS" in channel["error"]
    assert providers.requests == []


# =================================================================================================== Teams

APP_ID = "00000000-0000-4000-8000-000000000abc"
SERVICE_URL = "https://smba.trafficmanager.net/emea/"


@pytest.fixture
def bot_keys(providers: FakeProviders) -> rsa.RSAPrivateKey:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "k1", "use": "sig", "endorsements": ["msteams"]})
    providers.on("GET", teams.OPENID_CONFIG_URL, {"jwks_uri": "https://login.botframework.com/v1/.well-known/keys"})
    providers.on("GET", "https://login.botframework.com/v1/.well-known/keys", {"keys": [jwk]})
    return key


def bot_token(key: rsa.RSAPrivateKey, **claims: Any) -> str:
    body = {"iss": teams.ISSUER, "aud": APP_ID, "exp": int(time.time()) + 600, "serviceurl": SERVICE_URL, **claims}
    return jwt.encode(body, key, algorithm="RS256", headers={"kid": "k1"})


def activity(text: str = "<at>Messer</at> Hola equipo", activity_id: str = "act-1") -> dict[str, Any]:
    return {
        "type": "message",
        "id": activity_id,
        "serviceUrl": SERVICE_URL,
        "channelId": "msteams",
        "from": {"id": "29:user", "name": "Nora", "aadObjectId": "aad-1"},
        "recipient": {"id": f"28:{APP_ID}", "name": "Messer"},
        "conversation": {"id": "a:conv-1", "conversationType": "personal", "tenantId": "t1"},
        "text": text,
    }


async def test_teams_jwt_validation_and_reply(
    client: httpx.AsyncClient, providers: FakeProviders, bot_keys: rsa.RSAPrivateKey, queued: list[str]
) -> None:
    pid = await signup_project(client)
    token_url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
    providers.on("POST", token_url, {"access_token": "bf-token", "expires_in": 3600})
    channel = await connect(
        client, pid, {"provider": "teams", "credentials": {"app_password": "pw"}, "config": {"app_id": APP_ID}}
    )
    assert channel["status"] == "active", channel
    url = f"/api/channels/{channel['id']}/teams"

    assert (await client.post(url, json=activity())).status_code == 401
    wrong_aud = bot_token(bot_keys, aud="someone-else")
    assert (
        await client.post(url, json=activity(), headers={"Authorization": f"Bearer {wrong_aud}"})
    ).status_code == 401
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = bot_token(other_key)
    assert (await client.post(url, json=activity(), headers={"Authorization": f"Bearer {forged}"})).status_code == 401
    elsewhere = bot_token(bot_keys, serviceurl="https://evil.example/")
    assert (
        await client.post(url, json=activity(), headers={"Authorization": f"Bearer {elsewhere}"})
    ).status_code == 401
    expired = bot_token(bot_keys, exp=int(time.time()) - 3600)
    assert (await client.post(url, json=activity(), headers={"Authorization": f"Bearer {expired}"})).status_code == 401
    assert queued == []

    good = {"Authorization": f"Bearer {bot_token(bot_keys)}"}
    assert (await client.post(url, json=activity(), headers=good)).status_code == 200
    typing = {**activity(activity_id="act-2"), "type": "typing"}
    await client.post(url, json=typing, headers=good)
    [row] = await inbound_rows(channel["id"])
    assert row.text == "Hola equipo" and row.sender_name == "Nora" and row.sender_id == "aad-1"

    reply_url = f"{SERVICE_URL}v3/conversations/a%3Aconv-1/activities/act-1"
    providers.on("POST", reply_url, {"id": "reply-1"})
    delivery = await reply_to(row, "**Hecho**")
    assert delivery["status"] == "sent", delivery
    [sent] = providers.sent(reply_url)
    assert sent["text"] == "**Hecho**" and sent["textFormat"] == "markdown" and sent["replyToId"] == "act-1"
    reply_req = next(r for r in providers.requests if str(r.url) == reply_url)
    assert reply_req.headers["authorization"] == "Bearer bf-token"

    # Demo mode skips Bot Framework validation but still needs the channel token.
    demo = await connect(client, pid, {"provider": "teams", "name": "Teams demo"})
    demo_url = f"/api/channels/{demo['id']}/teams"
    assert (await client.post(demo_url, json=activity())).status_code == 401
    assert (await client.post(demo_url, params={"token": demo["webhook_secret"]}, json=activity())).status_code == 200


# =================================================================================================== Email


def postmark(sender: str, to: str, subject: str, text: str, message_id: str, **headers: str) -> dict[str, Any]:
    return {
        "From": sender,
        "FromFull": {"Email": sender, "Name": "Clara"},
        "To": to,
        "OriginalRecipient": to,
        "Subject": subject,
        "TextBody": text,
        "MessageID": "pm-" + message_id,
        "Headers": [{"Name": "Message-ID", "Value": f"<{message_id}@mail.example>"}]
        + [{"Name": k.replace("_", "-"), "Value": v} for k, v in headers.items()],
    }


async def test_email_channel_threads_replies(
    client: httpx.AsyncClient, queued: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = await signup_project(client)
    channel = await connect(client, pid, {"provider": "email", "config": {"subject_prefix": "[Acme]"}})
    assert channel["demo"] is False and channel["status"] == "active"
    address = channel["inbound_address"]
    url = f"/api/channels/{channel['id']}/email"
    mail = postmark("clara@cliente.example", address, "Factura 12", "¿Cuándo vence?\n\n> cita anterior", "m1")
    assert (await client.post(url, json=mail)).status_code == 401
    assert (await client.post(url, json=mail, params={"token": "nope"})).status_code == 401
    basic = base64.b64encode(f"postmark:{channel['webhook_secret']}".encode()).decode()
    assert (await client.post(url, json=mail, headers={"Authorization": f"Basic {basic}"})).status_code == 200
    auto = postmark(
        "clara@cliente.example", address, "Fuera de la oficina", "Vuelvo el lunes", "m2", Auto_Submitted="auto-replied"
    )
    await client.post(url, json=auto, params={"token": channel["webhook_secret"]})

    # Shared inbound webhook routes by address (provider-wide secret).
    monkeypatch.setattr(get_settings(), "messer_inbound_email_secret", "inbound-secret")
    follow = postmark(
        "clara@cliente.example",
        f"Soporte <{address}>",
        "Re: Factura 12",
        "Gracias",
        "m3",
        In_Reply_To="<m1@mail.example>",
        References="<m1@mail.example>",
    )
    assert (await client.post("/api/channels/inbound/email", json=follow)).status_code == 401
    routed = await client.post("/api/channels/inbound/email", json=follow, params={"token": "inbound-secret"})
    assert routed.status_code == 202 and routed.json()["routed"] == 1
    rows = await inbound_rows(channel["id"])
    assert [r.text for r in rows] == ["Asunto: Factura 12\n\n¿Cuándo vence?", "Gracias"]
    assert rows[0].conversation_id == rows[1].conversation_id

    ConsoleEmailAdapter.sent.clear()
    delivery = await reply_to(rows[1], "De nada, **Clara**.")
    assert delivery["status"] == "sent"
    [email] = ConsoleEmailAdapter.sent
    assert email.to == "clara@cliente.example" and email.subject == "Re: Factura 12"
    assert email.reply_to == address
    assert email.headers["In-Reply-To"] == "<m3@mail.example>"
    assert email.headers["References"].split() == ["<m1@mail.example>", "<m3@mail.example>"]
    assert "<strong>Clara</strong>" in email.html and "**" not in email.text


async def test_channel_context_prefers_channel_credentials(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "whatsapp_access_token", "platform-token")
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "platform-secret")
    monkeypatch.setattr(get_settings(), "whatsapp_phone_number_id", "555")
    pid = await signup_project(client)
    providers_list = (await client.get("/api/v1/channels/providers")).json()
    assert providers_list[0]["platform_ready"] is True
    channel = await connect(client, pid, {"provider": "whatsapp", "demo": True})
    assert channel["credential_source"] == "platform" and channel["missing_credentials"] == []
    async with system_session() as s:
        row = await s.get(Channel, uuid.UUID(channel["id"]))
        assert row is not None
        row.credentials = None
        ctx = channel_context(row)
    assert ctx.credentials == {"access_token": "platform-token", "app_secret": "platform-secret"}
    assert ctx.config["phone_number_id"] == "555"
