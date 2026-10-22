"""/api/public/v1 — public pages: published apps and dashboards, public chat and the embeddable widget.

Everything runs against the **production** environment (the deployed version; ``409 not_deployed`` before the
first deployment) and is charged to the organization. Interfaces with ``auth.required`` need a Messer session
of a member of the organization (with one of ``auth.roles`` when set); otherwise visitors are anonymous end
users identified by a signed httpOnly cookie (``messer_eu``; embedded widgets that cannot keep third-party
cookies send the same signed token in ``X-Messer-End-User``). End users never see queries, ids, tool calls or
costs, and never approve anything. Every endpoint is rate limited per visitor.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse

from messer_common.db import system_session
from messer_common.settings import get_settings

from ..deps import client_ip, get_optional_principal
from ..errors import ApiError, NotFound, RateLimited
from ..ratelimit import hit
from ..services import interfaces as svc
from ..services.limits import require_feature
from .interfaces import ActionIn, ChatIn, DataIn, DecisionIn
from .studio import stream_response

public_router = APIRouter(prefix="/api/public/v1", tags=["public-interfaces"])

UPLOAD_LIMIT = 100 * 1024 * 1024
LIMITS = {
    "read": (240, 60),  # requests per window (s) per visitor
    "data": (240, 60),
    "action": (30, 60),
    "upload": (20, 60),
    "chat": (20, 60),
}
CHAT_PER_INTERFACE = (600, 60)


# ------------------------------------------------------------------------------------------------ helpers


async def _limit(request: Request, bucket: str, key: str | None = None) -> None:
    limit, window = LIMITS[bucket]
    ident = key or client_ip(request) or "unknown"
    allowed, retry_after = await hit(f"pub:{bucket}:{ident}", limit, window)
    if not allowed:
        raise RateLimited(
            "Demasiadas solicitudes. Inténtalo de nuevo en unos segundos.", details={"retry_after": retry_after}
        )


def _cookie_kwargs() -> dict[str, Any]:
    settings = get_settings()
    secure = settings.messer_web_url.startswith("https://") or settings.is_production
    # Embedded widgets live in third-party pages: there the cookie must be SameSite=None (and partitioned).
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "none" if secure else "lax",
        "partitioned": secure,
        "path": "/api/public/v1",
        "max_age": svc.END_USER_TTL_S,
    }


def _set_end_user_cookie(response: Response, actor: svc.Actor) -> None:
    if actor.new_end_user_token:
        response.set_cookie(svc.END_USER_COOKIE, actor.new_end_user_token, **_cookie_kwargs())
        response.headers["X-Messer-End-User"] = actor.new_end_user_token


async def _actor(request: Request, target: svc.PublicTarget) -> svc.Actor:
    """The visitor: a member (when signed in to the organization) or an anonymous end user."""
    try:
        principal = await get_optional_principal(request)
    except ApiError:
        principal = None  # an expired session is just an anonymous visit (unless the interface needs login)
    role, is_superadmin = await svc.member_role(target.org.id, principal)
    svc.check_access(target.spec, role, signed_in=principal is not None, is_superadmin=is_superadmin)
    if principal is not None and (role is not None or is_superadmin):
        return svc.Actor(
            org_id=target.org.id,
            user_id=principal.user_id,
            email=principal.email,
            role=role,
            is_superadmin=is_superadmin,
            api_key_id=principal.api_key_id,
            end_user=f"user:{principal.user_id}" if principal.user_id else f"key:{principal.api_key_id}",
        )
    token = request.headers.get(svc.END_USER_HEADER) or request.cookies.get(svc.END_USER_COOKIE)
    end_user = svc.read_end_user_token(token)
    actor = svc.Actor(org_id=target.org.id)
    if end_user is None:
        end_user, fresh = svc.issue_end_user_token()
        actor.new_end_user_token = fresh
    actor.end_user = f"anon:{end_user}"
    return actor


def _viewer(actor: svc.Actor) -> dict[str, Any]:
    return {
        "authenticated": actor.is_member,
        "role": actor.role,
        "email": actor.email if actor.is_member else None,
        "can_upload": actor.is_member,
    }


def _component(target: svc.PublicTarget, component_id: str) -> Any:
    comp = target.spec.component(component_id)
    if comp is None:
        raise NotFound("Este componente no existe", code="component_not_found")
    return comp


async def _app(org: str, project: str, slug: str) -> svc.PublicTarget:
    target = await svc.published_app(org, project, slug)
    await svc.ensure_org_available(target.org.id, running=False)
    return target


async def _chat(org: str, project: str, agent: str) -> svc.PublicTarget:
    target = await svc.published_chat(org, project, agent)
    await svc.ensure_org_available(target.org.id, running=False)
    async with system_session() as s:
        await require_feature(s, target.org.id, "public_chat")
    return target


def _public_view(target: svc.PublicTarget, actor: svc.Actor) -> dict[str, Any]:
    return {
        "org": {"name": target.org.name, "slug": target.org.slug},
        "project": {"name": target.project.name, "slug": target.project.slug},
        "interface": svc.client_definition(target.spec),
        "viewer": _viewer(actor),
        "published_at": target.row.published_at.isoformat() if target.row.published_at else None,
    }


# ------------------------------------------------------------------------------------------------ apps


@public_router.get("/apps/{org}/{project}/{slug}")
async def get_app(org: str, project: str, slug: str, request: Request, response: Response) -> dict[str, Any]:
    """The published interface (layout and props only) and who is viewing it."""
    await _limit(request, "read")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    _set_end_user_cookie(response, actor)
    return _public_view(target, actor)


@public_router.post("/apps/{org}/{project}/{slug}/components/{component_id}/data")
async def app_data(
    org: str, project: str, slug: str, component_id: str, body: DataIn, request: Request
) -> dict[str, Any]:
    await _limit(request, "data")
    if body.draft is not None:
        raise ApiError("Las páginas públicas no admiten borradores", code="draft_not_allowed")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    result = await svc.component_data(target.project, _component(target, component_id), actor, body.inputs)
    data = result.to_dict()
    data.pop("policy", None)
    return data


@public_router.post("/apps/{org}/{project}/{slug}/components/{component_id}/action")
async def app_action(
    org: str, project: str, slug: str, component_id: str, body: ActionIn, request: Request, response: Response
) -> dict[str, Any]:
    await _limit(request, "action")
    if body.draft is not None:
        raise ApiError("Las páginas públicas no admiten borradores", code="draft_not_allowed")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    _set_end_user_cookie(response, actor)
    return await svc.run_component(
        target.project,
        _component(target, component_id),
        actor,
        environment="production",
        values=body.values,
        row=body.row,
        inputs=body.inputs,
        row_action=body.row_action,
    )


@public_router.post("/apps/{org}/{project}/{slug}/components/{component_id}/upload", status_code=201)
async def app_upload(
    org: str, project: str, slug: str, component_id: str, request: Request, file: UploadFile = File(...)
) -> dict[str, Any]:
    await _limit(request, "upload")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    data = await file.read(UPLOAD_LIMIT + 1)
    return await svc.upload_file(
        target.project,
        _component(target, component_id),
        actor,
        filename=file.filename or "archivo",
        data=data,
        mime=file.content_type,
        environment="production",
    )


@public_router.post("/apps/{org}/{project}/{slug}/components/{component_id}/chat")
async def app_chat(
    org: str, project: str, slug: str, component_id: str, body: ChatIn, request: Request
) -> StreamingResponse:
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    await _limit(request, "chat", actor.end_user)
    comp = _component(target, component_id)
    run_body = await svc.chat_run_body(
        target.project, target.row, comp, actor, message=body.message, environment="production"
    )
    response = stream_response(svc.end_user_stream(run_body, show_errors=actor.is_member))
    _set_end_user_cookie(response, actor)
    return response


@public_router.get("/apps/{org}/{project}/{slug}/components/{component_id}/conversation")
async def app_conversation(
    org: str, project: str, slug: str, component_id: str, request: Request, response: Response
) -> dict[str, Any]:
    await _limit(request, "read")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    _set_end_user_cookie(response, actor)
    comp = _component(target, component_id)
    conv = await svc.find_conversation(
        target.project,
        channel_key=svc.chat_channel_key(target.row, comp, "production"),
        external_user_id=actor.end_user or "",
    )
    return await svc.conversation_view(conv)


@public_router.delete("/apps/{org}/{project}/{slug}/components/{component_id}/conversation", status_code=204)
async def app_reset_conversation(org: str, project: str, slug: str, component_id: str, request: Request) -> None:
    await _limit(request, "read")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    comp = _component(target, component_id)
    await svc.reset_conversation(
        target.project,
        channel_key=svc.chat_channel_key(target.row, comp, "production"),
        external_user_id=actor.end_user or "",
    )


@public_router.post("/apps/{org}/{project}/{slug}/components/{component_id}/approvals/{approval_id}/decision")
async def app_decision(
    org: str, project: str, slug: str, component_id: str, approval_id: uuid.UUID, body: DecisionIn, request: Request
) -> dict[str, Any]:
    await _limit(request, "action")
    target = await _app(org, project, slug)
    actor = await _actor(request, target)
    return await svc.decide_approval(
        target.project,
        _component(target, component_id),
        actor,
        approval_id,
        decision=body.decision,
        comment=body.comment,
        payload=body.payload,
    )


# ------------------------------------------------------------------------------------------------ public chat


def _chat_component(target: svc.PublicTarget) -> Any:
    return target.spec.components()[0]


@public_router.get("/chat/{org}/{project}/{agent}")
async def get_chat(
    org: str,
    project: str,
    agent: str,
    request: Request,
    response: Response,
    embed: bool = Query(
        default=False, description="Widget: return the end-user token for the X-Messer-End-User header"
    ),
) -> dict[str, Any]:
    """Chat page configuration (theme, greeting, suggestions) and the end user's identity cookie."""
    await _limit(request, "read")
    target = await _chat(org, project, agent)
    actor = await _actor(request, target)
    _set_end_user_cookie(response, actor)
    view = _public_view(target, actor)
    if embed and actor.end_user and actor.end_user.startswith("anon:"):
        # Widgets in third-party pages may lose the cookie: they keep this token and send it as a header.
        view["end_user_token"] = actor.new_end_user_token or svc.end_user_token(actor.end_user.removeprefix("anon:"))
    return view


@public_router.get("/chat/{org}/{project}/{agent}/conversation")
async def chat_conversation(org: str, project: str, agent: str, request: Request, response: Response) -> dict[str, Any]:
    """The end user's messages (memory) and whether an answer is waiting for a human approval."""
    await _limit(request, "read")
    target = await _chat(org, project, agent)
    actor = await _actor(request, target)
    _set_end_user_cookie(response, actor)
    conv = await svc.find_conversation(
        target.project,
        channel_key=svc.chat_channel_key(target.row, _chat_component(target), "production"),
        external_user_id=actor.end_user or "",
    )
    return await svc.conversation_view(conv)


@public_router.post("/chat/{org}/{project}/{agent}/messages")
async def chat_message(org: str, project: str, agent: str, body: ChatIn, request: Request) -> StreamingResponse:
    """Send a message; the answer streams as SSE (TEXT, ACTIVITY, APPROVAL_PENDING, DONE, ERROR)."""
    await _limit(request, "data")
    target = await _chat(org, project, agent)
    actor = await _actor(request, target)
    await _limit(request, "chat", actor.end_user)
    limit, window = CHAT_PER_INTERFACE
    allowed, retry_after = await hit(f"pub:chat-interface:{target.row.id}", limit, window)
    if not allowed:
        raise RateLimited(
            "El chat está recibiendo demasiados mensajes. Inténtalo en unos segundos.",
            details={"retry_after": retry_after},
        )
    run_body = await svc.chat_run_body(
        target.project, target.row, _chat_component(target), actor, message=body.message, environment="production"
    )
    response = stream_response(svc.end_user_stream(run_body, show_errors=actor.is_member))
    _set_end_user_cookie(response, actor)
    return response


@public_router.delete("/chat/{org}/{project}/{agent}/conversation", status_code=204)
async def chat_reset(org: str, project: str, agent: str, request: Request) -> None:
    """Start a new conversation (the previous one is closed and kept for the team's inbox)."""
    await _limit(request, "read")
    target = await _chat(org, project, agent)
    actor = await _actor(request, target)
    await svc.reset_conversation(
        target.project,
        channel_key=svc.chat_channel_key(target.row, _chat_component(target), "production"),
        external_user_id=actor.end_user or "",
    )
