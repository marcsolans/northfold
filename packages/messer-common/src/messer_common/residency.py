"""Data residency policy (spec §9.2).

Organizations run in one of two modes:

* ``standard``  — EU infrastructure; models through the direct Anthropic API (or Bedrock EU); any configured
  email/voice provider.
* ``eu_strict`` — nothing leaves the EU: models **only** through Claude on AWS Bedrock in an EU region, local
  embeddings only, and email/voice providers only when they process data in an EU region (or disabled).

Callers (runtime model gateway, embedders, email/voice adapters) ask :func:`allowed_provider` before using a
provider for an organization. The check is pure and cheap; :func:`org_residency` loads the organization's mode.

Provider names: ``model`` providers are the ``provider`` part of a ``provider/model`` string (``anthropic``,
``bedrock``, ``openai``…, ``messer`` for the local demo model); ``embeddings`` providers follow
``MESSER_EMBEDDINGS_PROVIDER`` (``local``, ``hash``, ``voyage``, ``bedrock``); ``email`` providers follow
``MESSER_EMAIL_PROVIDER`` (``console``, ``smtp``, ``postmark``, ``resend``); ``voice`` providers are ``browser``
(WebRTC in the browser), ``livekit``, ``twilio``, ``telnyx``, ``deepgram``, ``elevenlabs``. A provider may carry its
processing region as ``name:region`` (``twilio:ie1``, ``bedrock:eu-west-1``) or through the ``region`` argument.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import Org
from .models_config import bedrock_allowed_regions, bedrock_region
from .settings import get_settings

ResidencyMode = Literal["standard", "eu_strict"]
ProviderKind = Literal["model", "email", "voice", "embeddings"]
PROVIDER_KINDS: tuple[ProviderKind, ...] = ("model", "embeddings", "email", "voice")

# Regions an organization may be pinned to (all in the EU).
EU_REGIONS: dict[str, str] = {
    "eu-central-1": "Frankfurt",
    "eu-west-1": "Irlanda",
    "eu-west-3": "París",
    "eu-north-1": "Estocolmo",
    "eu-south-1": "Milán",
    "eu-south-2": "España",
}

# Providers that never send data to a third party (they run inside the Messer deployment).
LOCAL_PROVIDERS: dict[ProviderKind, frozenset[str]] = {
    "model": frozenset({"messer"}),
    "embeddings": frozenset({"local", "hash", "fastembed"}),
    "email": frozenset({"console", "smtp"}),
    "voice": frozenset({"browser", "webrtc", "livekit"}),
}

# Third-party providers allowed in eu_strict only when they process data in an EU region.
EU_REGION_PROVIDERS: dict[ProviderKind, frozenset[str]] = {
    "model": frozenset({"bedrock"}),
    "embeddings": frozenset(),  # spec: local embeddings only
    "email": frozenset({"resend", "postmark", "ses"}),
    "voice": frozenset({"twilio", "telnyx", "deepgram", "elevenlabs"}),
}

# EU region identifiers used by those providers.
_EU_REGION_ALIASES = {"eu", "ie1", "de1", "eu1", "fra", "fra1", "dub", "dub1", "ams", "ams1", "eu-west", "eu-central"}


@dataclass(frozen=True, slots=True)
class Residency:
    org_id: uuid.UUID
    mode: ResidencyMode
    region: str

    @property
    def strict(self) -> bool:
        return self.mode == "eu_strict"


def is_eu_region(region: str | None) -> bool:
    """True for EU processing regions (``eu-central-1``, ``eu-west-1``…, provider aliases such as ``ie1``)."""
    if not region:
        return False
    value = region.strip().lower()
    return value.startswith("eu-") or value in _EU_REGION_ALIASES or value in EU_REGIONS


def _split(provider: str) -> tuple[str, str | None]:
    name, _, region = provider.strip().lower().partition(":")
    return name, (region or None)


def _configured_region(kind: ProviderKind, name: str) -> str | None:
    """Region the deployment declares for a provider when the caller does not pass one."""
    s = get_settings()
    if kind == "model" and name == "bedrock":
        return s.aws_region or bedrock_region()
    if kind == "email":
        return s.messer_email_region or None
    if kind == "voice":
        return s.messer_voice_region or None
    return None


def allowed_provider(residency: Residency, kind: ProviderKind, provider: str, *, region: str | None = None) -> bool:
    """May ``provider`` process this organization's data for ``kind``?

    Standard organizations may use any provider. ``eu_strict`` organizations may only use local providers or
    EU-region providers (Bedrock in an allowed EU region for models; no hosted embeddings).
    """
    name, inline_region = _split(provider)
    if not name:
        return False
    if not residency.strict:
        return True
    if name in LOCAL_PROVIDERS[kind]:
        return True
    if name not in EU_REGION_PROVIDERS[kind]:
        return False
    effective = (region or inline_region or _configured_region(kind, name) or "").lower()
    if kind == "model":
        return effective in {r.lower() for r in bedrock_allowed_regions()}
    return is_eu_region(effective)


def model_route(residency: Residency) -> Literal["anthropic", "bedrock"]:
    """Route for Claude models: eu_strict organizations always go through Bedrock EU."""
    return "bedrock" if residency.strict else "anthropic"


async def org_residency(session: AsyncSession, org_id: uuid.UUID) -> Residency:
    """Load an organization's residency. Unknown organizations are treated as strict (fail closed)."""
    row = (await session.execute(select(Org.data_residency, Org.region).where(Org.id == org_id))).first()
    if row is None:
        return Residency(org_id=org_id, mode="eu_strict", region=bedrock_region())
    mode: ResidencyMode = "eu_strict" if row[0] == "eu_strict" else "standard"
    return Residency(org_id=org_id, mode=mode, region=str(row[1] or bedrock_region()))


def deployment_providers() -> list[tuple[ProviderKind, str, str | None]]:
    """Providers this deployment is configured to use, as (kind, provider, region)."""
    s = get_settings()
    out: list[tuple[ProviderKind, str, str | None]] = []
    if s.has_anthropic:
        out.append(("model", "anthropic", None))
    if s.has_bedrock:
        out.append(("model", "bedrock", s.aws_region or bedrock_region()))
    if not s.has_anthropic and not s.has_bedrock:
        out.append(("model", "messer", None))
    out.append(("embeddings", s.messer_embeddings_provider, None))
    out.append(("email", s.messer_email_provider, s.messer_email_region or None))
    voice_region = s.messer_voice_region or None
    out.append(("voice", "browser", None))
    if s.livekit_url:
        out.append(("voice", "livekit", voice_region))
    if s.twilio_account_sid:
        out.append(("voice", "twilio", voice_region))
    if s.telnyx_api_key:
        out.append(("voice", "telnyx", voice_region))
    if s.deepgram_api_key:
        out.append(("voice", "deepgram", voice_region))
    if s.elevenlabs_api_key:
        out.append(("voice", "elevenlabs", voice_region))
    return out
