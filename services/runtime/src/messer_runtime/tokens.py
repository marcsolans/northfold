"""Credentials inside the data plane.

* Service token — control plane → runtime calls (``MESSER_SERVICE_TOKEN``; mTLS can be layered on top).
* Sandbox token — a signed, short-lived token handed to each sandbox process. It is scoped to one
  organization, project and commit; it is the only credential a sandbox ever sees.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request

from messer_common.security import TokenError, constant_time_equals, sign_payload, verify_signed_payload
from messer_common.settings import get_settings

SANDBOX_TTL_S = 60 * 60 * 24


@dataclass(frozen=True, slots=True)
class SandboxClaims:
    org_id: uuid.UUID
    project_id: uuid.UUID
    commit: str
    environment: str


def issue_sandbox_token(*, org_id: uuid.UUID, project_id: uuid.UUID, commit: str, environment: str) -> str:
    return sign_payload(
        {
            "purpose": "sandbox",
            "org": str(org_id),
            "project": str(project_id),
            "commit": commit,
            "env": environment,
            "iat": int(time.time()),
        },
        ttl_s=SANDBOX_TTL_S,
    )


def _extract(request: Request) -> str:
    header = request.headers.get("authorization") or request.headers.get("x-api-key") or ""
    return header.removeprefix("Bearer ").strip()


def sandbox_claims(request: Request) -> SandboxClaims:
    token = _extract(request)
    if not token:
        raise HTTPException(status_code=401, detail="missing sandbox token")
    try:
        claims = verify_signed_payload(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail="invalid sandbox token") from exc
    if claims.get("purpose") != "sandbox":
        raise HTTPException(status_code=401, detail="invalid sandbox token")
    return SandboxClaims(
        org_id=uuid.UUID(claims["org"]),
        project_id=uuid.UUID(claims["project"]),
        commit=claims["commit"],
        environment=claims.get("env", "development"),
    )


def require_service(request: Request) -> None:
    token = _extract(request)
    if not token or not constant_time_equals(token, get_settings().service_token):
        raise HTTPException(status_code=401, detail="invalid service token")


def check_scope(claims: SandboxClaims, org_id: uuid.UUID | str, project_id: uuid.UUID | str | None = None) -> None:
    if str(claims.org_id) != str(org_id) or (project_id is not None and str(claims.project_id) != str(project_id)):
        raise HTTPException(status_code=403, detail="out of sandbox scope")
