"""OAuth 2.1 for the MCP server and developer tools (see :mod:`messer_api.services.oauth`).

Public (root):

* ``GET  /.well-known/oauth-authorization-server`` — RFC 8414 metadata (issuer = the API's public URL)
* ``POST /oauth/register``  — dynamic client registration (RFC 7591)
* ``GET  /oauth/authorize`` — validates the request and sends the browser to the consent page (web)
* ``POST /oauth/token``     — ``authorization_code`` (PKCE S256) and ``refresh_token`` grants
* ``POST /oauth/revoke``    — RFC 7009

Consent page support and connected applications (``/api/v1/oauth``, user session):

* ``GET  /api/v1/oauth/authorize/request`` · ``POST /api/v1/oauth/authorize``
* ``GET  /api/v1/oauth/grants`` · ``DELETE /api/v1/oauth/grants/{id}``
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from messer_common.db import Principal, system_session
from messer_common.db.models.developers import OAuthGrant
from messer_common.roles import at_least

from ..deps import client_ip, get_org_principal, get_principal
from ..errors import ApiError, Forbidden, NotFound
from ..ratelimit import rate_limit
from ..services import oauth as svc

router = APIRouter(prefix="/oauth", tags=["oauth"])
public_router = APIRouter(tags=["oauth"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _oauth_error(exc: svc.OAuthError) -> JSONResponse:
    headers = dict(NO_STORE)
    if exc.status == 401:
        headers["WWW-Authenticate"] = 'Basic realm="Messer OAuth"'
    return JSONResponse(exc.body(), status_code=exc.status, headers=headers)


async def _form(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: value for key, value in form.items() if isinstance(value, str)}


# ------------------------------------------------------------------------------------------- public


@public_router.get("/.well-known/oauth-authorization-server")
async def authorization_server_metadata() -> JSONResponse:
    return JSONResponse(svc.metadata(), headers={"Cache-Control": "public, max-age=300"})


@public_router.post("/oauth/register", status_code=201, dependencies=[Depends(rate_limit("oauth_register", 20, 60))])
async def register(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return _oauth_error(svc.OAuthError("invalid_client_metadata", "Cuerpo JSON no válido"))
    try:
        client = await svc.register_client(body)
    except svc.OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(client, status_code=201, headers=NO_STORE)


@public_router.get("/oauth/authorize")
async def authorize(request: Request) -> Response:
    """Validate the request; errors about the client or redirect URI are shown by Messer (never redirected)."""
    params = {k: v for k, v in request.query_params.items()}
    try:
        await svc.validate_authorize(params)
    except svc.OAuthError as exc:
        if exc.redirectable and params.get("redirect_uri"):
            return RedirectResponse(
                svc.error_redirect(params["redirect_uri"], exc.error, exc.description, params.get("state")),
                status_code=302,
            )
        return RedirectResponse(
            svc.consent_url({"error": exc.error, "error_description": exc.description}), status_code=302
        )
    return RedirectResponse(svc.consent_url(params), status_code=302)


@public_router.post("/oauth/token", dependencies=[Depends(rate_limit("oauth_token", 120, 60))])
async def token(request: Request) -> JSONResponse:
    form = await _form(request)
    try:
        client = await svc.authenticate_client(form, request.headers.get("authorization"))
        grant_type = form.get("grant_type")
        if grant_type == "authorization_code":
            body = await svc.exchange_code(client, form, client_ip(request))
        elif grant_type == "refresh_token":
            body = await svc.refresh_tokens(client, form, client_ip(request))
        else:
            raise svc.OAuthError("unsupported_grant_type", "grant_type admitidos: authorization_code, refresh_token")
    except svc.OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(body, headers=NO_STORE)


@public_router.post("/oauth/revoke", dependencies=[Depends(rate_limit("oauth_revoke", 120, 60))])
async def revoke(request: Request) -> Response:
    form = await _form(request)
    try:
        client = await svc.authenticate_client(form, request.headers.get("authorization"))
    except svc.OAuthError as exc:
        return _oauth_error(exc)
    if form.get("token"):
        await svc.revoke_token(client, form["token"], client_ip(request))
    return Response(status_code=200, headers=NO_STORE)


# ------------------------------------------------------------------------------- consent page support


class AuthorizeParams(BaseModel):
    client_id: str = Field(max_length=64)
    redirect_uri: str = Field(default="", max_length=2000)
    response_type: str = "code"
    code_challenge: str = Field(default="", max_length=128)
    code_challenge_method: str = "S256"
    state: str | None = Field(default=None, max_length=2000)
    scope: str | None = Field(default=None, max_length=2000)
    resource: str | None = Field(default=None, max_length=2000)

    def params(self) -> dict[str, str]:
        data = self.model_dump(include=set(AuthorizeParams.model_fields))
        return {k: str(v) for k, v in data.items() if v not in (None, "")}


class DecisionIn(AuthorizeParams):
    org_id: uuid.UUID | None = None
    approve: bool


def _session_only(principal: Principal) -> Principal:
    if principal.api_key_id is not None:
        raise Forbidden("Autoriza aplicaciones desde una sesión de Messer, no con una API key", code="session_required")
    return principal


async def _validated(params: dict[str, str]) -> tuple[Any, svc.AuthorizeRequest]:
    try:
        return await svc.validate_authorize(params)
    except svc.OAuthError as exc:
        raise ApiError(exc.description, code=f"oauth_{exc.error}") from exc


@router.get("/authorize/request")
async def authorize_request(
    params: AuthorizeParams = Depends(), principal: Principal = Depends(get_principal)
) -> dict[str, Any]:
    """What the consent page shows: the client, the requested scopes and the user's organizations."""
    _session_only(principal)
    assert principal.user_id is not None
    client, req = await _validated(params.params())
    return await svc.consent_view(principal.user_id, client, req)


@router.post("/authorize")
async def authorize_decision(
    body: DecisionIn, request: Request, principal: Principal = Depends(get_principal)
) -> dict[str, str]:
    """Approve (one organization) or deny; returns the client redirect the browser must follow."""
    _session_only(principal)
    client, req = await _validated(body.params())
    if not body.approve:
        return {"redirect_to": svc.deny(req)}
    if body.org_id is None:
        raise ApiError("Elige una organización", code="org_required")
    try:
        redirect = await svc.approve(principal, client, req, body.org_id, client_ip(request))
    except svc.OAuthError as exc:
        raise Forbidden(exc.description, code=f"oauth_{exc.error}") from exc
    return {"redirect_to": redirect}


@router.get("/grants")
async def list_grants(principal: Principal = Depends(get_org_principal)) -> list[dict[str, Any]]:
    """Connected applications: the user's own, or every member's for admins."""
    return await svc.list_grants(principal, all_users=principal.is_superadmin or at_least(principal.role, "admin"))


@router.delete("/grants/{grant_id}", status_code=204)
async def revoke_grant(
    grant_id: uuid.UUID, request: Request, principal: Principal = Depends(get_org_principal)
) -> Response:
    async with system_session() as s:
        grant = (
            await s.execute(select(OAuthGrant).where(OAuthGrant.id == grant_id).with_for_update())
        ).scalar_one_or_none()
        if grant is None or grant.org_id != principal.org_id:
            raise NotFound("Aplicación conectada no encontrada")
        if grant.user_id != principal.user_id and not (principal.is_superadmin or at_least(principal.role, "admin")):
            raise Forbidden("Solo puedes desconectar tus propias aplicaciones", code="insufficient_role")
        await svc.revoke_grant(s, grant, actor=principal, ip=client_ip(request))
    return Response(status_code=204)
