"""Messaging channels: WhatsApp, Slack, Microsoft Teams, Telegram and email.

``get_adapter(provider)`` returns the provider adapter (verify, parse, send). ``context`` builds the per-channel
context (decrypted credentials, platform defaults, webhook URL); ``processing`` runs inbound messages through the
connected agent and delivers the answers (worker side).
"""

from __future__ import annotations

from .base import (
    ChannelAdapter,
    ChannelContext,
    ChannelError,
    CheckResult,
    CredentialField,
    InboundMessage,
    InboundRequest,
    InvalidConfig,
    InvalidSignature,
    ReplyTarget,
    SendError,
    WebhookReply,
)
from .email import EmailAdapter
from .slack import SlackAdapter
from .teams import TeamsAdapter
from .telegram import TelegramAdapter
from .whatsapp import WhatsAppAdapter

_ADAPTERS: dict[str, ChannelAdapter] = {
    a.provider: a for a in (WhatsAppAdapter(), SlackAdapter(), TeamsAdapter(), TelegramAdapter(), EmailAdapter())
}
PROVIDERS: tuple[str, ...] = tuple(_ADAPTERS)


def get_adapter(provider: str) -> ChannelAdapter:
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise InvalidConfig(f"Proveedor de canal no soportado: {provider}", code="unknown_provider")
    return adapter


def is_channel_provider(provider: str | None) -> bool:
    return provider in _ADAPTERS


__all__ = [
    "PROVIDERS",
    "ChannelAdapter",
    "ChannelContext",
    "ChannelError",
    "CheckResult",
    "CredentialField",
    "InboundMessage",
    "InboundRequest",
    "InvalidConfig",
    "InvalidSignature",
    "ReplyTarget",
    "SendError",
    "WebhookReply",
    "get_adapter",
    "is_channel_provider",
]
