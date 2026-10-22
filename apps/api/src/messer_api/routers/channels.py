"""/api/v1 channels: connect WhatsApp, Slack, Teams, Telegram or email to an agent; test, simulate, inspect."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common.db import Principal

from ..deps import ensure_project_access, get_db, require_role
from ..services import channels as svc
from ..services import projects as projects_svc

router = APIRouter(tags=["channels"])


@router.get("/channels/providers", response_model=list[svc.ProviderOut])
async def list_providers(_: Principal = Depends(require_role("viewer"))) -> list[svc.ProviderOut]:
    """Supported providers, the credentials each one needs and whether the platform already provides them."""
    return svc.providers()


@router.get("/projects/{project_id}/channels", response_model=list[svc.ChannelOut])
async def list_channels(
    project_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> list[svc.ChannelOut]:
    ensure_project_access(principal, project_id)
    project = await projects_svc.get_project(session, project_id)
    return await svc.list_channels(session, project)


@router.post("/projects/{project_id}/channels", response_model=svc.ChannelCreated, status_code=201)
async def connect_channel(
    project_id: uuid.UUID,
    body: svc.ChannelIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> svc.ChannelCreated:
    """Connect a channel to an agent. Without credentials (or with ``demo: true``) it runs in demo mode.

    The response carries the webhook secret once (WhatsApp verify token, email webhook token, demo token).
    """
    ensure_project_access(principal, project_id)
    project = await projects_svc.get_project(session, project_id)
    return await svc.connect(session, principal, project, body)


@router.get("/channels/{channel_id}", response_model=svc.ChannelOut)
async def get_channel(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> svc.ChannelOut:
    return await svc.describe(session, await svc.get_channel(session, principal, channel_id))


@router.patch("/channels/{channel_id}", response_model=svc.ChannelOut)
async def update_channel(
    channel_id: uuid.UUID,
    body: svc.ChannelPatch,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> svc.ChannelOut:
    channel = await svc.get_channel(session, principal, channel_id)
    return await svc.update(session, principal, channel, body)


@router.delete("/channels/{channel_id}", status_code=204)
async def disconnect_channel(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Disconnect: unregisters the webhook where the provider supports it. Conversations stay in the inbox."""
    channel = await svc.get_channel(session, principal, channel_id)
    await svc.disconnect(session, principal, channel)


@router.post("/channels/{channel_id}/test", response_model=svc.TestOut)
async def test_channel(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> svc.TestOut:
    """Check the credentials with the provider and refresh the channel status."""
    channel = await svc.get_channel(session, principal, channel_id)
    return await svc.test(session, principal, channel)


@router.post("/channels/{channel_id}/rotate-secret", response_model=svc.SecretOut)
async def rotate_secret(
    channel_id: uuid.UUID,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> svc.SecretOut:
    channel = await svc.get_channel(session, principal, channel_id)
    return await svc.rotate_secret(session, principal, channel)


@router.post("/channels/{channel_id}/simulate", response_model=svc.SimulateOut, status_code=202)
async def simulate(
    channel_id: uuid.UUID,
    body: svc.SimulateIn,
    principal: Principal = Depends(require_role("builder")),
    session: AsyncSession = Depends(get_db),
) -> svc.SimulateOut:
    """Write to the agent as a user of this channel. Replies are stored on the conversation, never sent."""
    channel = await svc.get_channel(session, principal, channel_id)
    return await svc.simulate(principal, channel, body)


@router.get("/channels/{channel_id}/messages", response_model=svc.ChannelMessagePage)
async def channel_messages(
    channel_id: uuid.UUID,
    direction: str | None = Query(default=None, pattern="^(inbound|outbound)$"),
    cursor: str | None = Query(default=None, description="created_at|id of the last item of the previous page"),
    limit: int = Query(default=50, ge=1, le=200),
    principal: Principal = Depends(require_role("viewer")),
    session: AsyncSession = Depends(get_db),
) -> svc.ChannelMessagePage:
    """Delivery log: every message received and sent, with its status and errors."""
    channel = await svc.get_channel(session, principal, channel_id)
    return await svc.messages(session, channel, cursor=cursor, limit=limit, direction=direction)
