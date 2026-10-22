"""OAuth URL construction, code exchange and refresh against mock providers (httpx.MockTransport)."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from messer_common.settings import reset_settings_cache
from messer_connectors import http as chttp
from messer_connectors import oauth, registry
from messer_connectors.base import ConnectorAuthError


@pytest.fixture
def oauth_apps(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ("GOOGLE", "MICROSOFT", "SLACK", "NOTION", "HUBSPOT", "SALESFORCE"):
        monkeypatch.setenv(f"{key}_CLIENT_ID", f"{key.lower()}-client")
        monkeypatch.setenv(f"{key}_CLIENT_SECRET", f"{key.lower()}-secret")
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "contoso.example")
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def no_oauth_apps(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in ("GOOGLE", "MICROSOFT", "SLACK", "NOTION", "HUBSPOT", "SALESFORCE"):
        monkeypatch.setenv(f"{key}_CLIENT_ID", "")
        monkeypatch.setenv(f"{key}_CLIENT_SECRET", "")
    reset_settings_cache()
    yield
    reset_settings_cache()


def _query(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


def test_missing_app_means_demo(no_oauth_apps: None) -> None:
    spec = registry.get_adapter("gmail").spec
    assert oauth.oauth_app(spec) is None
    assert oauth.missing_env(spec) == ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]


def test_authorize_urls(oauth_apps: None) -> None:
    redirect = "https://app.example/api/v1/connections/oauth/x/callback"
    google = oauth.authorize_url(
        registry.get_adapter("google_drive").spec, redirect_uri=redirect, state="st", code_challenge="ch"
    )
    q = _query(google)
    assert google.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert q["client_id"] == "google-client" and q["state"] == "st" and q["redirect_uri"] == redirect
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["code_challenge"] == "ch" and q["code_challenge_method"] == "S256"
    assert "https://www.googleapis.com/auth/drive.readonly" in q["scope"].split(" ")

    ms = oauth.authorize_url(
        registry.get_adapter("outlook").spec, redirect_uri=redirect, state="st", code_challenge="ch"
    )
    assert ms.startswith("https://login.microsoftonline.com/contoso.example/oauth2/v2.0/authorize?")
    assert "offline_access" in _query(ms)["scope"].split(" ")

    slack = _query(oauth.authorize_url(registry.get_adapter("slack").spec, redirect_uri=redirect, state="st"))
    assert "chat:write" in slack["scope"].split(",") and slack["user_scope"] == "search:read"
    assert "code_challenge" not in slack

    notion = _query(oauth.authorize_url(registry.get_adapter("notion").spec, redirect_uri=redirect, state="st"))
    assert notion["owner"] == "user" and "scope" not in notion


def _token_transport(seen: list[httpx.Request], responses: dict[str, dict[str, object]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = request.content.decode()
        grant = json.loads(body)["grant_type"] if body.startswith("{") else parse_qs(body)["grant_type"][0]
        return httpx.Response(200, json=responses[grant])

    return httpx.MockTransport(handler)


async def test_exchange_and_refresh_google(oauth_apps: None) -> None:
    seen: list[httpx.Request] = []
    chttp.set_transport(
        _token_transport(
            seen,
            {
                "authorization_code": {
                    "access_token": "at-1",
                    "refresh_token": "rt-1",
                    "expires_in": 3600,
                    "scope": "a b",
                    "token_type": "Bearer",
                },
                "refresh_token": {"access_token": "at-2", "expires_in": 3600},
            },
        )
    )
    try:
        spec = registry.get_adapter("gmail").spec
        creds = await oauth.exchange_code(spec, code="c0de", redirect_uri="https://cb", code_verifier="v" * 50)
        assert creds["access_token"] == "at-1" and creds["refresh_token"] == "rt-1"
        assert creds["expires_at"] > time.time() + 3000
        form = parse_qs(seen[0].content.decode())
        assert (
            form["code"] == ["c0de"]
            and form["code_verifier"] == ["v" * 50]
            and form["client_secret"] == ["google-secret"]
        )
        assert str(seen[0].url) == "https://oauth2.googleapis.com/token"

        expired = {**creds, "expires_at": time.time() - 10}
        assert oauth.needs_refresh(expired)
        fresh = await oauth.refresh(spec, expired)
        assert fresh["access_token"] == "at-2"
        assert fresh["refresh_token"] == "rt-1"  # Google does not rotate refresh tokens
    finally:
        chttp.set_transport(None)


async def test_slack_and_notion_token_quirks(oauth_apps: None) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "slack.com":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "access_token": "xoxb-1",
                    "authed_user": {"id": "U1", "access_token": "xoxp-1"},
                    "team": {"id": "T1", "name": "Albor"},
                    "scope": "chat:write",
                },
            )
        return httpx.Response(200, json={"access_token": "secret_n", "workspace_name": "Albor", "bot_id": "b1"})

    chttp.set_transport(httpx.MockTransport(handler))
    try:
        slack = await oauth.exchange_code(registry.get_adapter("slack").spec, code="c", redirect_uri="https://cb")
        assert slack["access_token"] == "xoxb-1" and slack["extra"]["user_token"] == "xoxp-1"
        assert slack["extra"]["team_name"] == "Albor"
        notion = await oauth.exchange_code(registry.get_adapter("notion").spec, code="c", redirect_uri="https://cb")
        assert notion["extra"]["workspace_name"] == "Albor"
        notion_req = seen[-1]
        assert (
            notion_req.headers["authorization"] == "Basic " + base64.b64encode(b"notion-client:notion-secret").decode()
        )
        assert json.loads(notion_req.content)["grant_type"] == "authorization_code"
    finally:
        chttp.set_transport(None)


async def test_revoked_refresh_token_is_an_auth_error(oauth_apps: None) -> None:
    chttp.set_transport(httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    try:
        with pytest.raises(ConnectorAuthError):
            await oauth.refresh(registry.get_adapter("hubspot").spec, {"refresh_token": "old", "expires_at": 1})
        with pytest.raises(ConnectorAuthError):
            await oauth.refresh(registry.get_adapter("hubspot").spec, {"expires_at": 1})  # nothing to refresh with
    finally:
        chttp.set_transport(None)
