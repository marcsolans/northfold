"""Public channel webhooks (no session): providers call these URLs with signed requests.

* ``/api/channels/{channel_id}/{provider}`` — per-channel URL shown in the Channels page (WhatsApp, Slack,
  Teams, Telegram, email). ``GET`` answers provider verification handshakes (WhatsApp).
* ``/api/channels/inbound/email`` — shared inbound email webhook that routes ``ch-<token>@`` addresses.
* ``/api/channels/whatsapp`` — webhook of the platform's own Meta app (``WHATSAPP_*`` variables).

Every message is acknowledged immediately and processed by the worker (``channel_inbound``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response

from ..services import channels as svc

public_router = APIRouter(prefix="/api/channels", tags=["channel webhooks"])


@public_router.post("/inbound/email", status_code=202)
async def shared_inbound_email(request: Request) -> Response:
    """Inbound email provider webhook (Postmark JSON). Secret: ``?token=`` or HTTP Basic/Bearer."""
    return await svc.receive_shared_email(request)


@public_router.api_route("/whatsapp", methods=["GET", "POST"])
async def platform_whatsapp(request: Request) -> Response:
    """Meta webhook of the platform WhatsApp number (verification handshake and signed events)."""
    return await svc.receive_shared_whatsapp(request)


@public_router.api_route("/{channel_id}/{provider}", methods=["GET", "POST"])
async def channel_webhook(channel_id: uuid.UUID, provider: str, request: Request) -> Response:
    """Provider webhook of one channel (signature verified per provider; demo channels need ``?token=``)."""
    return await svc.receive_webhook(channel_id, provider, request)
