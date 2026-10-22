"""/scim/v2 — SCIM 2.0 endpoint for identity providers (Okta, Microsoft Entra ID, OneLogin…).

Authentication: ``Authorization: Bearer scim_…`` (token created in Settings → SSO and SCIM, stored hashed).
Errors use the SCIM error format (``urn:ietf:params:scim:api:messages:2.0:Error``) and media type
``application/scim+json``. The plan feature ``scim`` (Enterprise) is checked on every request.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from messer_common.db import system_session
from messer_common.db.models import Org, ScimToken
from messer_common.logging import get_logger
from messer_common.security import hash_token

from ..errors import ApiError
from ..ratelimit import hit
from ..services import scim as scim_service
from ..services.scim import ScimContext, ScimError
from ..services.sso import org_has_feature

log = get_logger("messer.api.scim")
SCIM_MEDIA_TYPE = "application/scim+json"


def scim_json(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status_code, media_type=SCIM_MEDIA_TYPE, headers=headers)


class ScimRoute(APIRoute):
    """Route class that renders every failure in the SCIM error format."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await original(request)
            except ScimError as exc:
                return scim_json(exc.body(), status_code=exc.status)
            except RequestValidationError as exc:
                detail = "; ".join(str(e.get("msg", "")) for e in exc.errors())[:500] or "Petición no válida"
                return scim_json(ScimError(400, detail, "invalidValue").body(), status_code=400)
            except ApiError as exc:
                return scim_json(ScimError(exc.status_code, exc.message).body(), status_code=exc.status_code)
            except StarletteHTTPException as exc:
                return scim_json(ScimError(exc.status_code, str(exc.detail)).body(), status_code=exc.status_code)

        return handler


public_router = APIRouter(prefix="/scim/v2", tags=["scim"], route_class=ScimRoute)


async def scim_context(request: Request) -> ScimContext:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not token:
        raise ScimError(401, "Falta el token SCIM (Authorization: Bearer)")
    now = datetime.now(UTC)
    async with system_session() as s:
        row = (
            await s.execute(select(ScimToken).where(ScimToken.hashed_token == hash_token(token)))
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise ScimError(401, "Token SCIM no válido o revocado")
        org = await s.get(Org, row.org_id)
        if org is None or org.status == "blocked":
            raise ScimError(403, "La organización no está disponible")
        if not await org_has_feature(s, row.org_id, "scim"):
            raise ScimError(403, "El plan de la organización no incluye SCIM")
        if row.last_used_at is None or now - row.last_used_at > timedelta(minutes=1):
            row.last_used_at = now
        ctx = ScimContext(org_id=row.org_id, token_id=row.id)
    allowed, retry_after = await hit(f"scim:{ctx.token_id}", 1200, 60)
    if not allowed:
        raise ScimError(429, f"Demasiadas peticiones SCIM. Reintenta en {retry_after} s")
    return ctx


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        data = json.loads(await request.body() or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ScimError(400, "El cuerpo no es JSON válido", "invalidSyntax") from exc
    if not isinstance(data, dict):
        raise ScimError(400, "El cuerpo debe ser un objeto JSON", "invalidSyntax")
    return data


def _location(resource: dict[str, Any]) -> dict[str, str]:
    location = resource.get("meta", {}).get("location")
    return {"Location": str(location)} if location else {}


# ----------------------------------------------------------------------------- discovery


@public_router.get("/ServiceProviderConfig")
async def service_provider_config(_: ScimContext = Depends(scim_context)) -> JSONResponse:
    return scim_json(scim_service.service_provider_config())


@public_router.get("/ResourceTypes")
async def resource_types(_: ScimContext = Depends(scim_context)) -> JSONResponse:
    items = scim_service.resource_types()
    return scim_json(scim_service.list_response(len(items), 1, items))


@public_router.get("/ResourceTypes/{type_id}")
async def resource_type(type_id: str, _: ScimContext = Depends(scim_context)) -> JSONResponse:
    for item in scim_service.resource_types():
        if item["id"].lower() == type_id.lower():
            return scim_json(item)
    raise ScimError(404, f"ResourceType {type_id} no encontrado")


@public_router.get("/Schemas")
async def schemas(_: ScimContext = Depends(scim_context)) -> JSONResponse:
    items = scim_service.schemas()
    return scim_json(scim_service.list_response(len(items), 1, items))


@public_router.get("/Schemas/{schema_id}")
async def schema(schema_id: str, _: ScimContext = Depends(scim_context)) -> JSONResponse:
    for item in scim_service.schemas():
        if item["id"] == schema_id:
            return scim_json(item)
    raise ScimError(404, f"Schema {schema_id} no encontrado")


# ----------------------------------------------------------------------------- users


@public_router.get("/Users")
async def list_users(
    filter: str | None = None,
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0),
    attributes: str | None = None,
    excludedAttributes: str | None = None,
    ctx: ScimContext = Depends(scim_context),
) -> JSONResponse:
    async with system_session() as s:
        total, items = await scim_service.list_users(s, ctx, filter_text=filter, start_index=startIndex, count=count)
    items = [scim_service.project(i, attributes, excludedAttributes) for i in items]
    return scim_json(scim_service.list_response(total, startIndex, items))


@public_router.post("/Users")
async def create_user(request: Request, ctx: ScimContext = Depends(scim_context)) -> JSONResponse:
    payload = await _json_body(request)
    async with system_session() as s:
        resource = await scim_service.create_user(s, ctx, payload)
    return scim_json(resource, status_code=201, headers=_location(resource))


@public_router.get("/Users/{user_id}")
async def get_user(
    user_id: str,
    attributes: str | None = None,
    excludedAttributes: str | None = None,
    ctx: ScimContext = Depends(scim_context),
) -> JSONResponse:
    async with system_session() as s:
        resource = await scim_service.get_user(s, ctx, user_id)
    return scim_json(scim_service.project(resource, attributes, excludedAttributes))


@public_router.put("/Users/{user_id}")
async def replace_user(user_id: str, request: Request, ctx: ScimContext = Depends(scim_context)) -> JSONResponse:
    payload = await _json_body(request)
    async with system_session() as s:
        resource = await scim_service.replace_user(s, ctx, user_id, payload)
    return scim_json(resource)


@public_router.patch("/Users/{user_id}")
async def patch_user(user_id: str, request: Request, ctx: ScimContext = Depends(scim_context)) -> JSONResponse:
    payload = await _json_body(request)
    async with system_session() as s:
        resource = await scim_service.patch_user(s, ctx, user_id, payload)
    return scim_json(resource)


@public_router.delete("/Users/{user_id}", status_code=204)
async def delete_user(user_id: str, ctx: ScimContext = Depends(scim_context)) -> Response:
    async with system_session() as s:
        await scim_service.delete_user(s, ctx, user_id)
    return Response(status_code=204)


# ----------------------------------------------------------------------------- groups


@public_router.get("/Groups")
async def list_groups(
    filter: str | None = None,
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=0),
    attributes: str | None = None,
    excludedAttributes: str | None = None,
    ctx: ScimContext = Depends(scim_context),
) -> JSONResponse:
    async with system_session() as s:
        total, items = await scim_service.list_groups(s, ctx, filter_text=filter, start_index=startIndex, count=count)
    items = [scim_service.project(i, attributes, excludedAttributes) for i in items]
    return scim_json(scim_service.list_response(total, startIndex, items))


@public_router.post("/Groups")
async def create_group(request: Request, ctx: ScimContext = Depends(scim_context)) -> JSONResponse:
    payload = await _json_body(request)
    async with system_session() as s:
        resource = await scim_service.create_group(s, ctx, payload)
    return scim_json(resource, status_code=201, headers=_location(resource))


@public_router.get("/Groups/{group_id}")
async def get_group(
    group_id: str,
    attributes: str | None = None,
    excludedAttributes: str | None = None,
    ctx: ScimContext = Depends(scim_context),
) -> JSONResponse:
    async with system_session() as s:
        resource = await scim_service.get_group(s, ctx, group_id)
    return scim_json(scim_service.project(resource, attributes, excludedAttributes))


@public_router.put("/Groups/{group_id}")
async def replace_group(group_id: str, request: Request, ctx: ScimContext = Depends(scim_context)) -> JSONResponse:
    payload = await _json_body(request)
    async with system_session() as s:
        resource = await scim_service.replace_group(s, ctx, group_id, payload)
    return scim_json(resource)


@public_router.patch("/Groups/{group_id}", status_code=204)
async def patch_group(group_id: str, request: Request, ctx: ScimContext = Depends(scim_context)) -> Response:
    payload = await _json_body(request)
    async with system_session() as s:
        await scim_service.patch_group(s, ctx, group_id, payload)
    return Response(status_code=204)


@public_router.delete("/Groups/{group_id}", status_code=204)
async def delete_group(group_id: str, ctx: ScimContext = Depends(scim_context)) -> Response:
    async with system_session() as s:
        await scim_service.delete_group(s, ctx, group_id)
    return Response(status_code=204)
