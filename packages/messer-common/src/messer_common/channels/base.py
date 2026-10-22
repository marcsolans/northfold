"""Channel adapter contract: verify inbound webhooks, parse them into normalized messages, send replies.

Every provider module (``whatsapp``, ``slack``, ``teams``, ``telegram``, ``email``) implements
:class:`ChannelAdapter`. Adapters are stateless; everything about one channel (decrypted credentials, config,
webhook secret) travels in a :class:`ChannelContext`. Demo channels never reach a provider: their replies are
stored by the delivery layer instead of calling :meth:`ChannelAdapter.send_text`.
"""

from __future__ import annotations

import abc
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from ..settings import Settings
from .formatting import split_text
from .texts import normalize_common


class ChannelError(Exception):
    """Base error with a stable machine code and a user-facing (Spanish) message."""

    code = "channel_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class InvalidSignature(ChannelError):
    """The inbound request is not authentic (bad signature, token or JWT)."""

    code = "invalid_signature"


class InvalidConfig(ChannelError):
    """Credentials or configuration are missing or malformed."""

    code = "invalid_config"


class SendError(ChannelError):
    """A reply could not be delivered. ``retryable`` errors are retried with backoff; ``auth`` ones flag the
    channel as misconfigured."""

    code = "send_failed"

    def __init__(self, message: str, *, code: str | None = None, retryable: bool = False, auth: bool = False) -> None:
        super().__init__(message, code=code)
        self.retryable = retryable
        self.auth = auth


@dataclass(frozen=True, slots=True)
class CredentialField:
    """A credential the channel needs. ``platform`` is the settings attribute that may provide a default."""

    key: str
    required: bool = True
    secret: bool = True
    platform: str | None = None


@dataclass(slots=True)
class ChannelContext:
    channel_id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID
    provider: str
    credentials: dict[str, Any]
    config: dict[str, Any]
    webhook_secret: str | None
    demo: bool
    webhook_url: str
    name: str = ""


@dataclass(slots=True)
class InboundRequest:
    method: str
    headers: dict[str, str]  # lower-case names
    query: dict[str, str]
    body: bytes

    def header(self, name: str) -> str | None:
        return self.headers.get(name.lower())

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ChannelError("El cuerpo de la petición no es JSON válido", code="invalid_body") from exc


@dataclass(slots=True)
class WebhookReply:
    """Immediate answer to a webhook call (handshakes such as WhatsApp verification or Slack url_verification)."""

    status_code: int = 200
    body: Any = None
    media_type: str = "application/json"


@dataclass(slots=True)
class InboundMessage:
    """A provider message normalized for processing.

    ``conversation_key`` identifies the thread (it becomes ``conversations.external_user_id`` together with the
    channel); ``reply`` carries what the adapter needs to answer (chat id, thread ts, service URL, email headers).
    """

    external_id: str
    conversation_key: str
    sender_id: str
    text: str
    sender_name: str | None = None
    kind: str = "text"
    attachments: list[dict[str, Any]] = field(default_factory=list)
    thread_id: str | None = None
    reply: dict[str, Any] = field(default_factory=dict)
    sent_at: datetime | None = None
    # Slack thread replies without a mention are only answered in threads the agent already takes part in.
    requires_existing_conversation: bool = False

    def payload(self) -> dict[str, Any]:
        return {
            "conversation_key": self.conversation_key,
            "thread_id": self.thread_id,
            "reply": self.reply,
            "attachments": self.attachments,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "requires_existing_conversation": self.requires_existing_conversation,
        }


@dataclass(slots=True)
class ReplyTarget:
    """Where a reply goes: the reply context of the inbound message being answered."""

    conversation_key: str
    reply: dict[str, Any]
    thread_id: str | None = None
    last_inbound_at: datetime | None = None


@dataclass(slots=True)
class CheckResult:
    """Outcome of a connection test: details to show and config values learnt from the provider."""

    details: dict[str, Any] = field(default_factory=dict)
    config_updates: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(abc.ABC):
    provider: ClassVar[str]
    label: ClassVar[str]
    max_text: ClassVar[int] = 4000
    credential_fields: ClassVar[tuple[CredentialField, ...]] = ()
    # Non-secret settings accepted in ``channels.config`` (besides the common ones in COMMON_CONFIG).
    config_keys: ClassVar[tuple[str, ...]] = ()
    # Platform settings that provide non-secret config defaults (config key → settings attribute).
    platform_config: ClassVar[dict[str, str]] = {}

    # ------------------------------------------------------------------ configuration

    def platform_credentials(self, settings: Settings) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in self.credential_fields:
            if f.platform:
                value = getattr(settings, f.platform, "")
                if value:
                    out[f.key] = value
        return out

    def platform_defaults(self, settings: Settings) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, attr in self.platform_config.items():
            value = getattr(settings, attr, "")
            if value:
                out[key] = value
        return out

    def missing_credentials(self, credentials: dict[str, Any]) -> list[str]:
        return [f.key for f in self.credential_fields if f.required and not credentials.get(f.key)]

    # Non-secret config keys that must be present for a live (non-demo) channel.
    required_config: ClassVar[tuple[str, ...]] = ()

    def normalize_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Validate the common and provider-specific config keys. Raises :class:`InvalidConfig`."""
        try:
            return {**normalize_common(config), **self.provider_config(config)}
        except ValueError as exc:
            raise InvalidConfig(str(exc)) from exc

    def provider_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Provider keys (raise ValueError with a user-facing message when invalid)."""
        return {k: v for k, v in config.items() if k in self.config_keys and v not in (None, "")}

    def missing_config(self, config: dict[str, Any]) -> list[str]:
        return [k for k in self.required_config if not config.get(k)]

    def initial_config(self) -> dict[str, Any]:
        """Config generated when the channel is created (e.g. the inbound email address token)."""
        return {}

    # ------------------------------------------------------------------ inbound

    def handshake(self, ctx: ChannelContext, request: InboundRequest) -> WebhookReply | None:
        """Answer provider verification calls that come before (or instead of) signed events."""
        return None

    @abc.abstractmethod
    async def verify(self, ctx: ChannelContext, request: InboundRequest) -> None:
        """Raise :class:`InvalidSignature` unless the request comes from the provider."""

    def immediate_reply(self, ctx: ChannelContext, request: InboundRequest) -> WebhookReply | None:
        """A signed request that must be answered synchronously instead of processed (Slack url_verification)."""
        return None

    @abc.abstractmethod
    def parse(self, ctx: ChannelContext, request: InboundRequest) -> list[InboundMessage]:
        """Messages to process (empty for statuses, bot echoes, unsupported events)."""

    def ack(self, ctx: ChannelContext, request: InboundRequest) -> WebhookReply:
        return WebhookReply(200, {"ok": True})

    # ------------------------------------------------------------------ outbound

    def format_text(self, markdown: str) -> str:
        """Convert the agent's Markdown answer to the provider's formatting."""
        return markdown

    def parts(self, text: str) -> list[str]:
        """Split a formatted reply into messages within the provider's size limit."""
        return split_text(text, self.max_text)

    @abc.abstractmethod
    async def send_text(self, ctx: ChannelContext, target: ReplyTarget, text: str) -> list[str]:
        """Send a formatted reply (split with :meth:`parts` when needed). Returns the provider message ids.

        Raises :class:`SendError`.
        """

    async def check(self, ctx: ChannelContext) -> CheckResult:
        """Verify the credentials with the provider (connection test)."""
        return CheckResult()

    async def on_connect(self, ctx: ChannelContext) -> CheckResult:
        """Register the webhook with the provider when it supports it (Telegram)."""
        return await self.check(ctx)

    async def on_disconnect(self, ctx: ChannelContext) -> None:
        """Unregister the webhook (best effort)."""
        return None
