"""Central configuration for every Messer service.

Values come from the process environment and, for local development, from the
repository-root ``.env`` file. Every external integration is optional: the
``has_*`` properties tell callers whether to use the real adapter or the
mock/sandbox one. Missing keys are surfaced in the UI and in PROGRESS.md.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".env.example").exists() and (parent / "pyproject.toml").exists():
            return parent
    return Path.cwd()


REPO_ROOT = _find_repo_root()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_ROOT / ".env"),),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core
    messer_env: Literal["local", "test", "staging", "production"] = "local"
    messer_web_url: str = "http://localhost:3000"
    messer_api_url: str = "http://localhost:8000"
    messer_runtime_url: str = "http://localhost:8100"
    messer_voice_url: str = "http://localhost:8300"
    messer_mcp_url: str = "http://localhost:8400"
    messer_secrets_key: str = ""
    messer_jwt_secret: str = ""
    messer_service_token: str = ""
    messer_mtls_ca: str = ""
    messer_mtls_cert: str = ""
    messer_mtls_key: str = ""
    messer_projects_dir: str = "./.data/projects"
    messer_storage_dir: str = "./.data/storage"
    messer_runtime_cache_dir: str = "./.data/runtime"
    messer_superadmin_email: str = "admin@messer.local"
    messer_superadmin_password: str = ""
    messer_credit_margin: float = 0.3
    messer_credit_usd: float = 0.01
    messer_root_domain: str = "localhost"
    messer_cname_target: str = "cname.messer.local"
    messer_inbound_email_domain: str = "in.messer.local"
    messer_inbound_email_secret: str = ""
    messer_access_token_ttl_s: int = 3600
    messer_refresh_token_ttl_s: int = 60 * 60 * 24 * 30

    # --- database
    database_url: str = "postgresql+psycopg://messer:messer@localhost:5432/messer"
    database_app_url: str = "postgresql+psycopg://messer_app:messer_app@localhost:5432/messer"
    database_readonly_url: str = "postgresql+psycopg://messer_readonly:messer_readonly@localhost:5432/messer"

    # --- supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # --- redis
    redis_url: str = "redis://localhost:6379/0"

    # --- models
    anthropic_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "eu-central-1"
    openai_api_key: str = ""
    messer_embeddings_provider: Literal["local", "hash", "voyage", "bedrock"] = "local"
    messer_embeddings_model: str = ""  # explicit model id for new knowledge bases (overrides the provider default)
    messer_embeddings_batch_size: int = 32
    voyage_api_key: str = ""
    voyage_embeddings_model: str = "voyage-3.5"
    bedrock_embeddings_model: str = "amazon.titan-embed-text-v2:0"

    # --- knowledge
    messer_kb_max_file_mb: int = 100
    messer_kb_max_files_per_upload: int = 20
    messer_kb_docling_enabled: bool = True

    # --- stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_publishable_key: str = ""

    # --- email
    messer_email_provider: Literal["console", "smtp", "postmark", "resend"] = "smtp"
    messer_email_from: str = "Messer <no-reply@messer.local>"
    # Recipients of public contact-form submissions and of service-health alerts.
    # Both fall back to MESSER_SUPERADMIN_EMAIL when empty.
    messer_sales_email: str = ""
    messer_ops_email: str = ""
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_tls: bool = False
    postmark_server_token: str = ""
    resend_api_key: str = ""
    # Processing region of the email/voice providers (e.g. "eu-west-1", "ie1"); eu_strict orgs require an EU one.
    messer_email_region: str = ""
    messer_voice_region: str = ""

    # --- enterprise (GDPR, retention)
    messer_data_export_ttl_days: int = 7
    messer_retention_batch_size: int = 1000

    # --- observability
    sentry_dsn: str = ""
    otel_exporter_otlp_endpoint: str = ""

    # --- oauth apps
    google_client_id: str = ""
    google_client_secret: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    microsoft_tenant_id: str = "common"
    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_signing_secret: str = ""
    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    notion_client_id: str = ""
    notion_client_secret: str = ""
    github_client_id: str = ""
    github_client_secret: str = ""
    github_webhook_secret: str = ""

    # --- channels and voice
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    telegram_bot_token: str = ""
    teams_app_id: str = ""
    teams_app_password: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    telnyx_api_key: str = ""
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    deepgram_api_key: str = ""
    elevenlabs_api_key: str = ""

    # --- tuning
    runtime_sandbox_memory_mb: int = Field(default=2048)
    runtime_sandbox_cpu_seconds: int = Field(default=600)
    runtime_run_timeout_s: int = Field(default=300)
    sql_statement_timeout_ms: int = Field(default=5000)
    sql_row_limit: int = Field(default=1000)

    # --- connectors
    # Allow connector HTTP/MCP/database targets on private networks (always allowed in local/test).
    messer_connectors_allow_private_networks: bool = False
    # stdio MCP servers spawn a local process; enabled by default only in local/test (the runtime sandbox
    # and on-prem agents run them in production).
    messer_mcp_stdio_enabled: bool | None = None
    messer_connector_agent_rpc_timeout_s: int = Field(default=30)
    messer_connectors_max_file_mb: int = Field(default=100)

    @property
    def mcp_stdio_enabled(self) -> bool:
        if self.messer_mcp_stdio_enabled is not None:
            return self.messer_mcp_stdio_enabled
        return self.messer_env in ("local", "test")

    # ------------------------------------------------------------------ helpers
    def model_post_init(self, __context: object) -> None:
        # Supabase and most providers hand out postgres:// URLs; we always use psycopg 3.
        for attr in ("database_url", "database_app_url", "database_readonly_url"):
            value = getattr(self, attr)
            for prefix in ("postgresql://", "postgres://"):
                if value.startswith(prefix):
                    object.__setattr__(self, attr, "postgresql+psycopg://" + value[len(prefix) :])

    @property
    def is_production(self) -> bool:
        return self.messer_env == "production"

    @property
    def has_anthropic(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def has_bedrock(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)

    @property
    def has_stripe(self) -> bool:
        return bool(self.stripe_secret_key)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def has_supabase_storage(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def sales_email(self) -> str:
        return self.messer_sales_email or self.messer_superadmin_email

    @property
    def ops_email(self) -> str:
        return self.messer_ops_email or self.messer_superadmin_email

    @property
    def jwt_secret(self) -> str:
        if self.messer_jwt_secret:
            return self.messer_jwt_secret
        if self.messer_env in ("local", "test"):
            return "messer-local-development-jwt-secret-change-me"
        raise RuntimeError("MESSER_JWT_SECRET must be set outside local/test environments.")

    @property
    def secrets_key(self) -> bytes:
        if self.messer_secrets_key:
            key = self.messer_secrets_key.encode()
            if len(base64.urlsafe_b64decode(key)) != 32:
                raise RuntimeError("MESSER_SECRETS_KEY must be a urlsafe base64-encoded 32-byte key.")
            return key
        if self.messer_env in ("local", "test"):
            # Deterministic development key: never used in staging/production.
            return base64.urlsafe_b64encode(b"messer-local-dev-secrets-key-32b")
        raise RuntimeError("MESSER_SECRETS_KEY must be set outside local/test environments.")

    @property
    def service_token(self) -> str:
        if self.messer_service_token:
            return self.messer_service_token
        if self.messer_env in ("local", "test"):
            return "messer-local-service-token"
        raise RuntimeError("MESSER_SERVICE_TOKEN must be set outside local/test environments.")

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def projects_dir(self) -> Path:
        return self.resolve_path(self.messer_projects_dir)

    @property
    def storage_dir(self) -> Path:
        return self.resolve_path(self.messer_storage_dir)

    @property
    def runtime_cache_dir(self) -> Path:
        return self.resolve_path(self.messer_runtime_cache_dir)

    def pending_keys(self) -> list[dict[str, str]]:
        """Integrations running in mock/sandbox mode because their keys are missing."""
        checks: list[tuple[str, bool, str]] = [
            ("ANTHROPIC_API_KEY", self.has_anthropic, "Modelos de Claude (modo demo activo)"),
            ("SUPABASE_URL / SUPABASE_ANON_KEY", self.has_supabase, "Supabase Auth (auth local activa)"),
            ("STRIPE_SECRET_KEY", self.has_stripe, "Facturación Stripe (modo prueba simulado)"),
            ("AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY", self.has_bedrock, "Claude en AWS Bedrock UE (eu_strict)"),
            ("SENTRY_DSN", bool(self.sentry_dsn), "Sentry"),
            ("GOOGLE_CLIENT_ID", bool(self.google_client_id), "Conectores y login de Google"),
            ("MICROSOFT_CLIENT_ID", bool(self.microsoft_client_id), "Conectores y login de Microsoft"),
            ("SLACK_CLIENT_ID", bool(self.slack_client_id), "Conector y canal de Slack"),
            ("HUBSPOT_CLIENT_ID", bool(self.hubspot_client_id), "Conector de HubSpot"),
            ("SALESFORCE_CLIENT_ID", bool(self.salesforce_client_id), "Conector de Salesforce"),
            ("NOTION_CLIENT_ID", bool(self.notion_client_id), "Conector de Notion"),
            ("WHATSAPP_ACCESS_TOKEN", bool(self.whatsapp_access_token), "Canal de WhatsApp"),
            ("TWILIO_ACCOUNT_SID / TELNYX_API_KEY", bool(self.twilio_account_sid or self.telnyx_api_key), "Telefonía"),
            ("LIVEKIT_URL", bool(self.livekit_url), "Salas LiveKit"),
        ]
        return [{"variable": var, "feature": feature} for var, ok, feature in checks if not ok]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
