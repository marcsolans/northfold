"""Per-channel context: decrypted credentials (channel values over platform defaults), config, URLs."""

from __future__ import annotations

from typing import Any, Literal

from ..db.models import Channel
from ..logging import get_logger
from ..security import DecryptionError, decrypt, decrypt_json
from ..settings import get_settings
from . import get_adapter
from .base import ChannelContext, InvalidConfig
from .email import inbound_address as email_address

log = get_logger("messer.channels")

CredentialSource = Literal["channel", "platform", "mixed", "none"]


def webhook_url(channel: Channel) -> str:
    """Public URL the provider calls (served by the API, also reachable through the web origin's /api rewrite)."""
    return f"{get_settings().messer_web_url.rstrip('/')}/api/channels/{channel.id}/{channel.provider}"


def inbound_address(channel: Channel) -> str | None:
    return email_address(channel.config or {}) if channel.provider == "email" else None


def stored_credentials(channel: Channel) -> dict[str, Any]:
    try:
        return decrypt_json(channel.credentials)
    except (DecryptionError, ValueError):
        log.error("channel.credentials_undecryptable", channel_id=str(channel.id))
        return {}


def webhook_secret(channel: Channel) -> str | None:
    if not channel.webhook_secret:
        return None
    try:
        return decrypt(channel.webhook_secret)
    except DecryptionError:
        log.error("channel.secret_undecryptable", channel_id=str(channel.id))
        return None


def credential_source(channel: Channel) -> CredentialSource:
    try:
        adapter = get_adapter(channel.provider)
    except InvalidConfig:
        return "none"
    stored = {k for k, v in stored_credentials(channel).items() if v}
    platform = set(adapter.platform_credentials(get_settings()))
    keys = [f.key for f in adapter.credential_fields]
    if not keys:
        return "none"
    from_channel = [k for k in keys if k in stored]
    from_platform = [k for k in keys if k not in stored and k in platform]
    if from_channel and from_platform:
        return "mixed"
    if from_channel:
        return "channel"
    if from_platform:
        return "platform"
    return "none"


def channel_context(channel: Channel) -> ChannelContext:
    settings = get_settings()
    adapter = get_adapter(channel.provider)
    stored = {k: v for k, v in stored_credentials(channel).items() if v not in (None, "")}
    credentials = {**adapter.platform_credentials(settings), **stored}
    config: dict[str, Any] = {**adapter.platform_defaults(settings), **(channel.config or {})}
    if channel.provider == "whatsapp" and settings.whatsapp_verify_token:
        config["platform_verify_token"] = settings.whatsapp_verify_token
    return ChannelContext(
        channel_id=channel.id,
        org_id=channel.org_id,
        project_id=channel.project_id,
        provider=channel.provider,
        credentials=credentials,
        config=config,
        webhook_secret=webhook_secret(channel),
        demo=channel.demo,
        webhook_url=webhook_url(channel),
        name=channel.name,
    )
