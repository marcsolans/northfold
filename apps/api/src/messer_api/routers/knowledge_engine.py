"""Engine-compatible knowledge endpoints (``messer.platform.knowledge_bases`` and the platform tools).

``POST /api/v1/orgs/{org_id}/knowledge-bases/{kb_id}/query``  body ``{"sql", "params", "explain"}``
``POST /api/v1/orgs/{org_id}/knowledge-bases/{kb_id}/search`` body ``{"query", "mode", "k"}``

Authenticated with a user JWT or an organization API key; the organization in the path must be the key's
organization or one the user belongs to. API keys use the ``agent`` policies.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from messer_common.db import Principal, rls_session, system_session
from messer_common.db.models import Membership

from ..deps import client_ip, get_principal, org_billing_state
from ..errors import Forbidden
from ..services.knowledge.schemas import QueryIn, QueryOut, SearchIn, SearchOut
from .knowledge import query_kb, search_kb

router = APIRouter(prefix="/orgs/{org_id}/knowledge-bases", tags=["knowledge"])


async def org_path_principal(org_id: uuid.UUID, principal: Principal = Depends(get_principal)) -> Principal:
    if principal.api_key_id is not None:
        if principal.org_id != org_id:
            raise Forbidden("La API key pertenece a otra organización", code="org_mismatch")
        return principal
    if principal.org_id != org_id:
        async with system_session() as s:
            role = (
                await s.execute(
                    select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == principal.user_id)
                )
            ).scalar_one_or_none()
        if role is None and not principal.is_superadmin:
            raise Forbidden("No perteneces a esta organización", code="not_a_member")
        principal = Principal(
            user_id=principal.user_id,
            org_id=org_id,
            role=role or "owner",
            is_superadmin=principal.is_superadmin,
            email=principal.email,
            impersonated_by=principal.impersonated_by,
            mfa_verified=principal.mfa_verified,
        )
    if principal.role is None and not principal.is_superadmin:
        raise Forbidden("No perteneces a esta organización", code="not_a_member")
    state = await org_billing_state(org_id)
    if state["blocked"] and not principal.is_superadmin:
        raise Forbidden("Esta organización está bloqueada. Contacta con soporte.", code="org_blocked")
    return principal


@router.post("/{kb_id}/query", response_model=QueryOut)
async def engine_query(
    kb_id: uuid.UUID, body: QueryIn, request: Request, principal: Principal = Depends(org_path_principal)
) -> QueryOut:
    async with rls_session(principal) as db:
        return await query_kb(db, principal, kb_id, body, client_ip(request))


@router.post("/{kb_id}/search", response_model=SearchOut)
async def engine_search(
    kb_id: uuid.UUID, body: SearchIn, principal: Principal = Depends(org_path_principal)
) -> SearchOut:
    async with rls_session(principal) as db:
        return await search_kb(db, principal, kb_id, body)
