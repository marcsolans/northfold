"""/api/v1/connector-agents — on-prem connector agents: enrollment tokens (admin), secret exchange, live status,
ping and the outbound WebSocket the agents keep open (``/api/v1/connector-agents/connect``)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, WebSocket
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal, new_id
from messer_common.db.models import Connection, ConnectorAgent
from messer_common.security import hash_token, random_token
from messer_connectors import agent_rpc
from messer_connectors.base import ConnectorError

from ..deps import client_ip, get_db, get_org_principal, require_role
from ..ratelimit import rate_limit
from ..services import connector_agents as agents_svc
from ..services.connections import api_error

router = APIRouter(prefix="/connector-agents", tags=["connector-agents"])


class AgentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class AgentUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class EnrollIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    hostname: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=40)


def agent_out(agent: ConnectorAgent, *, connections: int = 0) -> dict[str, Any]:
    return {
        "id": agent.id,
        "name": agent.name,
        "status": agents_svc.agent_status(agent),
        "version": agent.version,
        "hostname": agent.hostname,
        "capabilities": agent.capabilities or {},
        "last_seen_at": agent.last_seen_at,
        "enrolled_at": agent.enrolled_at,
        "created_at": agent.created_at,
        "connections": connections,
    }


@router.get("")
async def list_agents(
    principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    agents = (
        (
            await db.execute(
                select(ConnectorAgent)
                .where(ConnectorAgent.org_id == principal.org_id)
                .order_by(ConnectorAgent.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    counts = dict(
        (
            await db.execute(
                select(Connection.agent_id, func.count())
                .where(Connection.org_id == principal.org_id, Connection.agent_id.is_not(None))
                .group_by(Connection.agent_id)
            )
        ).all()
    )
    return [agent_out(a, connections=int(counts.get(a.id, 0))) for a in agents]


@router.post("", status_code=201)
async def create_agent(
    body: AgentCreateIn, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    agent = ConnectorAgent(
        id=new_id(),
        org_id=principal.org_id,
        name=body.name.strip(),
        enrollment_token_hash=hash_token(random_token(32)),
        status="pending",
    )
    db.add(agent)
    await db.flush()
    token = await agents_svc.issue_enrollment_token(agent, principal.user_id)
    await audit.record(
        db,
        action="connector_agent.created",
        principal=principal,
        entity_type="connector_agent",
        entity_id=agent.id,
        diff={"name": agent.name},
    )
    await db.flush()
    await db.refresh(agent)
    return {
        "agent": agent_out(agent),
        "enrollment_token": token,
        "commands": agents_svc.enroll_command(token),
        "expires_in_s": int(agents_svc.ENROLL_TTL.total_seconds()),
    }


@router.post("/enroll")
async def enroll_agent(
    body: EnrollIn, request: Request, _: None = Depends(rate_limit("agent_enroll", 10, 60))
) -> dict[str, Any]:
    """Public: exchanges a single-use enrollment token for the agent id and secret (shown once)."""
    return await agents_svc.enroll(body.token, hostname=body.hostname, version=body.version, ip=client_ip(request))


@router.websocket("/connect")
async def agent_socket(websocket: WebSocket) -> None:
    await agents_svc.serve(websocket)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: uuid.UUID, principal: Principal = Depends(get_org_principal), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    agent = await agents_svc.get_agent(db, principal.org_id, agent_id)
    count = (
        await db.execute(select(func.count()).select_from(Connection).where(Connection.agent_id == agent.id))
    ).scalar_one()
    return agent_out(agent, connections=int(count))


@router.patch("/{agent_id}")
async def rename_agent(
    agent_id: uuid.UUID,
    body: AgentUpdateIn,
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    assert principal.org_id is not None
    agent = await agents_svc.get_agent(db, principal.org_id, agent_id)
    agent.name = body.name.strip()
    await audit.record(
        db,
        action="connector_agent.renamed",
        principal=principal,
        entity_type="connector_agent",
        entity_id=agent.id,
        diff={"name": agent.name},
    )
    return agent_out(agent)


@router.post("/{agent_id}/enrollment-token")
async def regenerate_token(
    agent_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    agent = await agents_svc.get_agent(db, principal.org_id, agent_id)
    token = await agents_svc.issue_enrollment_token(agent, principal.user_id)
    await audit.record(
        db,
        action="connector_agent.token_issued",
        principal=principal,
        entity_type="connector_agent",
        entity_id=agent.id,
    )
    return {
        "enrollment_token": token,
        "commands": agents_svc.enroll_command(token),
        "expires_in_s": int(agents_svc.ENROLL_TTL.total_seconds()),
    }


@router.post("/{agent_id}/ping")
async def ping_agent(
    agent_id: uuid.UUID, principal: Principal = Depends(require_role("builder")), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    assert principal.org_id is not None
    agent = await agents_svc.get_agent(db, principal.org_id, agent_id)
    started = time.monotonic()
    try:
        info = await agent_rpc.call(agent.id, "ping", {}, timeout_s=10)
    except ConnectorError as exc:
        raise api_error(exc) from exc
    return {
        "ok": True,
        "latency_ms": int((time.monotonic() - started) * 1000),
        "agent": info,
        "checked_at": datetime.now(UTC),
    }


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: uuid.UUID, principal: Principal = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)
) -> Response:
    assert principal.org_id is not None
    agent = await agents_svc.get_agent(db, principal.org_id, agent_id)
    connections = (await db.execute(select(Connection).where(Connection.agent_id == agent.id))).scalars().all()
    for conn in connections:
        conn.status = "error"
        conn.error = "El agente on-premise de esta conexión se ha eliminado"
    await audit.record(
        db,
        action="connector_agent.deleted",
        principal=principal,
        entity_type="connector_agent",
        entity_id=agent.id,
        diff={"name": agent.name, "connections": len(connections)},
    )
    await db.delete(agent)
    agents_svc.disconnect_after_commit(db, agent.id, reason="deleted")
    return Response(status_code=204)
