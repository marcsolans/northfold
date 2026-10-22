"""Bearer token verification for the MCP endpoint: API keys and OAuth access tokens (both ``msr_…``) and session
tokens are checked against the platform API (``GET /api/v1/cli/whoami``), with a short in-memory cache."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Any

from mcp.server.auth.provider import AccessToken

from messer_common.logging import get_logger

from .api import ApiClient, MesserApiError

log = get_logger("messer.mcp.auth")

# Every scope of the builder role (an API key without explicit scopes has all of them).
ALL_SCOPES = [
    "projects:read",
    "projects:write",
    "runs:read",
    "runs:write",
    "knowledge:read",
    "knowledge:write",
    "deployments:write",
    "evals:run",
]
CACHE_TTL_S = 30.0
NEGATIVE_TTL_S = 5.0
MAX_CACHE = 5000


class MesserTokenVerifier:
    def __init__(self, api_url: str) -> None:
        self.api_url = api_url
        self._cache: dict[str, tuple[float, AccessToken | None, dict[str, Any] | None]] = {}

    def identity(self, token: str) -> dict[str, Any] | None:
        """The cached ``whoami`` of a verified token (organization, role, key)."""
        entry = self._cache.get(self._key(token))
        return entry[2] if entry else None

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def verify_token(self, token: str) -> AccessToken | None:
        key = self._key(token)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            async with ApiClient(self.api_url, token) as api:
                who = await api.get("/cli/whoami")
        except MesserApiError as exc:
            if exc.status in (401, 403):
                self._remember(key, None, None, NEGATIVE_TTL_S)
                return None
            log.warning("mcp.verify_failed", status=exc.status, code=exc.code)
            return None
        except Exception as exc:  # the API is unreachable: refuse without caching
            log.warning("mcp.verify_unavailable", error=str(exc))
            return None
        access = self._access_token(token, who)
        self._remember(key, access, who, CACHE_TTL_S)
        return access

    def _remember(self, key: str, access: AccessToken | None, who: dict[str, Any] | None, ttl: float) -> None:
        if len(self._cache) >= MAX_CACHE:
            now = time.monotonic()
            for k in [k for k, v in self._cache.items() if v[0] <= now] or list(self._cache)[: MAX_CACHE // 10]:
                self._cache.pop(k, None)
        self._cache[key] = (time.monotonic() + ttl, access, who)

    @staticmethod
    def _access_token(token: str, who: dict[str, Any]) -> AccessToken:
        key = who.get("api_key") or {}
        oauth = who.get("oauth") or {}
        scopes = list(key.get("scopes") or []) or list(ALL_SCOPES)
        expires_at: int | None = None
        if key.get("expires_at"):
            try:
                expires_at = int(datetime.fromisoformat(str(key["expires_at"])).timestamp())
            except ValueError:
                expires_at = None
        if oauth.get("client_id"):
            client_id = str(oauth["client_id"])
        elif key.get("id"):
            client_id = f"api_key:{key['id']}"
        else:
            client_id = f"session:{(who.get('user') or {}).get('id', '')}"
        return AccessToken(token=token, client_id=client_id, scopes=scopes, expires_at=expires_at)
