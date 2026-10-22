"""Connector contracts: catalog specs, actions, connection context, sync and event primitives.

Every connector is a :class:`ConnectorAdapter` subclass with a class-level :class:`ConnectorSpec`.
Adapters are stateless; everything about a concrete connection (decrypted credentials, config,
demo flag, on-prem agent) travels in a :class:`ConnectionContext`.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol

from pydantic import BaseModel, Field, computed_field

AuthType = Literal["oauth2", "api_key", "connection_string", "none", "mcp", "agent"]
SyncMode = Literal["full", "incremental"]

# Column types understood by knowledge tables (contracts §3, ``upsert_table``).
KbColumnType = Literal["text", "integer", "numeric", "boolean", "date", "timestamp", "json"]


# ----------------------------------------------------------------------------- errors


class ConnectorError(Exception):
    """A connector operation failed with a message that is safe to show to the user."""

    code = "connector_error"
    status_code = 400

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details or {}


class ConnectorAuthError(ConnectorError):
    """Credentials are missing, expired or revoked: the user must reconnect."""

    code = "connector_auth"
    status_code = 401


class ConnectorNotSupported(ConnectorError):
    code = "not_supported"
    status_code = 400


class ActionNotFound(ConnectorError):
    code = "action_not_found"
    status_code = 404


class InvalidArguments(ConnectorError):
    code = "invalid_arguments"
    status_code = 422


class ConfigError(ConnectorError):
    code = "invalid_config"
    status_code = 422


class ReadOnlyViolation(ConnectorError):
    code = "read_only"
    status_code = 403


class ProviderError(ConnectorError):
    """The remote provider answered with an error."""

    code = "provider_error"
    status_code = 502


class RateLimitedError(ProviderError):
    code = "provider_rate_limited"
    status_code = 429


class AgentUnavailable(ConnectorError):
    code = "agent_unavailable"
    status_code = 503


# ----------------------------------------------------------------------------- catalog


class OAuthSpec(BaseModel):
    """OAuth 2 authorization-code configuration of a provider."""

    provider: str
    authorize_url: str
    token_url: str
    scopes: list[str] = Field(default_factory=list)
    # Settings attributes holding the OAuth app credentials (``Settings.google_client_id`` …).
    client_id_setting: str
    client_secret_setting: str
    pkce: bool = False
    scope_separator: str = " "
    scope_param: str = "scope"
    # Extra scopes sent in a second parameter (Slack ``user_scope``).
    user_scopes: list[str] = Field(default_factory=list)
    extra_authorize_params: dict[str, str] = Field(default_factory=dict)
    # How the client authenticates at the token endpoint and how the body is encoded.
    token_auth: Literal["body", "basic"] = "body"  # noqa: S105 - auth method, not a secret
    token_body: Literal["form", "json"] = "form"  # noqa: S105 - encoding, not a secret
    supports_refresh: bool = True

    @property
    def env_vars(self) -> list[str]:
        return [self.client_id_setting.upper(), self.client_secret_setting.upper()]


class ConfigField(BaseModel):
    """A field of the connect dialog (rendered by the web app; labels are translated there by key)."""

    key: str
    kind: Literal["text", "secret", "url", "textarea", "boolean", "select", "number", "json", "list"] = "text"
    required: bool = False
    secret: bool = False  # stored encrypted in ``connections.credentials`` instead of ``config``
    default: Any = None
    options: list[str] = Field(default_factory=list)
    placeholder: str | None = None


class Capabilities(BaseModel):
    actions: list[str] = Field(default_factory=list)
    sync: bool = False
    # Resource kinds a sync can target (``folder``, ``table``, ``object``, ``page``, ``path``).
    sync_resources: list[str] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    introspection: bool = False
    demo: bool = False  # can run in demo mode with fixture data when the OAuth app is missing
    agent: bool = False  # can be routed through an on-prem connector agent


class EventSpec(BaseModel):
    """An event a connection can emit to workflow triggers (``triggers.emit`` name ``<connector>.<event>``)."""

    name: str  # full trigger event name, e.g. "gmail.new_email"
    event: str  # adapter event, e.g. "new_email" (``poll_events``)
    title: str
    title_en: str
    description: str
    # poll: the scheduler polls the provider for connections used by enabled triggers; push: emitted on arrival.
    delivery: Literal["poll", "push"] = "poll"


# Event titles shared by connectors (Spanish first, English second).
EVENT_TEXT: dict[str, tuple[str, str, str]] = {
    "new_email": ("Nuevo correo", "New email", "Llega un correo a la bandeja de entrada."),
    "new_contact": ("Nuevo contacto", "New contact", "Se crea un contacto en el CRM."),
    "new_record": (
        "Nuevo registro",
        "New record",
        "Se crea un registro del objeto configurado (por defecto, Lead; config.event_object).",
    ),
    "new_file": (
        "Nuevo archivo",
        "New file",
        "Se crea un archivo (en la carpeta de config.event_folder_id, o en cualquiera).",
    ),
    "received": ("Petición recibida", "Request received", "El webhook recibe una petición con firma válida."),
    "sync_completed": (
        "Sincronización completada",
        "Sync completed",
        "Termina una sincronización con una base de conocimiento (correcta o con error).",
    ),
}
PUSH_EVENTS = {"received", "sync_completed"}


class ConnectorSpec(BaseModel):
    key: str
    name: str
    category: str
    auth_type: AuthType
    description: str
    description_en: str = ""
    capabilities: Capabilities = Field(default_factory=Capabilities)
    icon: str | None = None
    oauth: OAuthSpec | None = None
    config_fields: list[ConfigField] = Field(default_factory=list)
    docs_url: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def events(self) -> list[EventSpec]:
        """Trigger events of this connector: provider events plus ``sync_completed`` for syncable connectors."""
        names = list(self.capabilities.events)
        if self.capabilities.sync:
            names.append("sync_completed")
        out: list[EventSpec] = []
        for name in names:
            title, title_en, description = EVENT_TEXT.get(name, (name, name, ""))
            out.append(
                EventSpec(
                    name=f"{self.key}.{name}",
                    event=name,
                    title=title,
                    title_en=title_en,
                    description=description,
                    delivery="push" if name in PUSH_EVENTS else "poll",
                )
            )
        return out


class ActionSpec(BaseModel):
    name: str
    title: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    # Side-effect actions (send, create, update, any non-GET HTTP) require approval by default.
    side_effect: bool = False


# ----------------------------------------------------------------------------- runtime context


@dataclass(slots=True)
class ConnectionContext:
    """Everything an adapter needs to act on one connection (contracts §4)."""

    connection_id: uuid.UUID
    org_id: uuid.UUID
    credentials: dict[str, Any]
    config: dict[str, Any]
    demo: bool = False
    connector_key: str = ""
    agent_id: uuid.UUID | None = None
    # Called by adapters when a provider rotates credentials mid-call (persisted by the loader).
    on_credentials_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None

    @property
    def access_token(self) -> str:
        token = self.credentials.get("access_token")
        if not token:
            raise ConnectorAuthError("La conexión no tiene un token de acceso. Vuelve a conectarla.")
        return str(token)


@dataclass(slots=True)
class TestResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Resource:
    """Something a sync can target, listed by the sync editor (folders, tables, CRM objects…)."""

    id: str  # value stored in ``syncs.resource`` (e.g. ``folder:1AbC`` or ``table:public.invoices``)
    name: str
    kind: str
    has_children: bool = False
    parent: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- syncs


@dataclass(slots=True)
class ColumnDef:
    name: str
    type: KbColumnType = "text"
    nullable: bool = True
    comment: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "nullable": self.nullable, "comment": self.comment}


@dataclass(slots=True)
class SyncFile:
    external_id: str
    filename: str
    data: bytes
    mime: str | None = None
    version: str | None = None  # provider revision/etag/modified time, used to skip unchanged files
    modified_at: str | None = None
    url: str | None = None
    path: str | None = None


@dataclass(slots=True)
class SyncRequest:
    resource: str
    mode: SyncMode = "full"
    cursor_field: str | None = None
    cursor: str | None = None
    primary_key: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)
    batch_size: int = 500


class SyncSink(Protocol):
    """Receives what an adapter syncs. Implemented by the control plane (writes into a knowledge base)."""

    async def file(self, item: SyncFile) -> None: ...

    async def rows(
        self, table: str, columns: list[ColumnDef], rows: list[dict[str, Any]], primary_key: list[str]
    ) -> None: ...

    async def should_skip(self, external_id: str, version: str | None) -> bool:
        """True when the file is already synced at this version (adapters may then skip the download)."""
        ...


@dataclass(slots=True)
class SyncOutcome:
    next_cursor: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------- adapter base


class ConnectorAdapter:
    """Base class for connectors. Subclasses set ``spec`` and override what they support."""

    spec: ClassVar[ConnectorSpec]

    @property
    def key(self) -> str:
        return self.spec.key

    # -- actions
    def actions(self) -> list[ActionSpec]:
        return []

    def action(self, name: str) -> ActionSpec:
        for spec in self.actions():
            if spec.name == name:
                return spec
        raise ActionNotFound(f"La acción «{name}» no existe en {self.spec.name}", details={"action": name})

    async def run_action(self, ctx: ConnectionContext, action: str, args: dict[str, Any]) -> Any:
        raise ActionNotFound(f"La acción «{action}» no existe en {self.spec.name}", details={"action": action})

    # -- connection lifecycle
    def validate_config(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        """Raise :class:`ConfigError` when the connect form is incomplete or invalid."""

    def prepare(self, config: dict[str, Any], credentials: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Normalize config/credentials before they are stored (e.g. generate a webhook secret)."""
        return config, credentials

    async def test(self, ctx: ConnectionContext) -> TestResult:
        return TestResult(ok=True, message="Conexión configurada")

    # -- sync
    async def list_resources(self, ctx: ConnectionContext, parent: str | None = None) -> list[Resource]:
        raise ConnectorNotSupported(f"{self.spec.name} no admite sincronización")

    async def sync(self, ctx: ConnectionContext, request: SyncRequest, sink: SyncSink) -> SyncOutcome:
        raise ConnectorNotSupported(f"{self.spec.name} no admite sincronización")

    # -- introspection (databases)
    async def introspect(self, ctx: ConnectionContext) -> dict[str, Any]:
        raise ConnectorNotSupported(f"{self.spec.name} no admite introspección de esquema")

    # -- events (workflow triggers)
    async def poll_events(
        self, ctx: ConnectionContext, event: str, cursor: str | None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Return ``(new_events, next_cursor)``.

        ``cursor=None`` establishes a baseline: no historical backfill, just the cursor to poll from.
        Each event is ``{"id", "event", "occurred_at", "data"}``.
        """
        raise ConnectorNotSupported(f"{self.spec.name} no emite eventos")

    def _check_event(self, event: str) -> str:
        base = event.split(":", 1)[0]
        if base not in self.spec.capabilities.events:
            raise ConnectorNotSupported(
                f"{self.spec.name} no emite el evento «{event}»",
                details={"supported": self.spec.capabilities.events},
            )
        return base


def obj_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    """Small helper to write action input schemas compactly."""
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema
