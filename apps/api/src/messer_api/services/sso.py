"""Enterprise SSO: connections and presets, verified domains, discovery, JIT provisioning, group → role
mapping and "enforce SSO for this domain".

Security model
--------------
Users are global (one account per email across organizations), so an identity provider may only assert
emails of a domain its organization has **verified** (DNS TXT, ``org_domains``). Without that rule an
organization could configure an IdP that asserts ``ceo@another-company.com`` and take over that account.
Discovery, login, enforcement and SCIM user creation all require the verified domain.

Roles granted through SSO/SCIM are ``admin``, ``builder`` or ``viewer``; ``owner`` is never assigned or
removed by an identity provider. Memberships created by SSO have ``source = "sso"``; their role follows the
group mappings on every login (when the connection has mappings). Manually managed memberships keep their role.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import dns.asyncresolver
import dns.exception
import dns.resolver
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import (
    AuthCredential,
    Membership,
    OneTimeToken,
    Org,
    SsoConnection,
    SsoGroupMapping,
    User,
)
from messer_common.db.models.enterprise import OrgDomain, OrgIdentity
from messer_common.logging import get_logger
from messer_common.plans import plan_has_feature
from messer_common.security import decrypt_json, encrypt_json, hash_token, random_token

from ..errors import ApiError
from .auth import find_user_by_email
from .limits import org_plan
from .sso_oidc import OidcConfig, SsoIdentity, SsoProtocolError
from .sso_saml import NAMEID_EMAIL, NAMEID_PERSISTENT, SamlConfig, normalize_certificate, parse_idp_metadata

log = get_logger("messer.sso")

AssignableRole = Literal["admin", "builder", "viewer"]
ASSIGNABLE_ROLES: tuple[str, ...] = ("admin", "builder", "viewer")
ROLE_RANK = {"viewer": 1, "builder": 2, "admin": 3, "owner": 4}
VERIFICATION_RECORD_PREFIX = "_messer-challenge"
VERIFICATION_VALUE_PREFIX = "messer-verification="

_DOMAIN_RE = re.compile(
    r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{1,59})$"
)

ENTRA_CLAIMS = "http://schemas.xmlsoap.org/ws/2005/05/identity/claims"

# Technical defaults per identity provider. ``{placeholders}`` are filled in by the admin in the UI.
PRESETS: dict[str, dict[str, Any]] = {
    "entra": {
        "label": "Microsoft Entra ID",
        "placeholders": ["tenant_id"],
        "oidc": {
            "issuer": "https://login.microsoftonline.com/{tenant_id}/v2.0",
            "scopes": ["openid", "email", "profile"],
            "email_claim": "email",
            "fallback_email_claims": ["preferred_username", "upn"],
            "groups_claim": "groups",
            "name_claim": "name",
        },
        "saml": {
            "idp_entity_id": "https://sts.windows.net/{tenant_id}/",
            "idp_sso_url": "https://login.microsoftonline.com/{tenant_id}/saml2",
            "name_id_format": NAMEID_EMAIL,
            "email_attribute": f"{ENTRA_CLAIMS}/emailaddress",
            "first_name_attribute": f"{ENTRA_CLAIMS}/givenname",
            "last_name_attribute": f"{ENTRA_CLAIMS}/surname",
            "display_name_attribute": "http://schemas.microsoft.com/identity/claims/displayname",
            "groups_attribute": "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
        },
    },
    "google": {
        "label": "Google Workspace",
        "placeholders": ["idp_id"],
        "oidc": {
            "issuer": "https://accounts.google.com",
            "scopes": ["openid", "email", "profile"],
            "email_claim": "email",
            "groups_claim": "",
            "hosted_domain_claim": "hd",
        },
        "saml": {
            "idp_entity_id": "https://accounts.google.com/o/saml2?idpid={idp_id}",
            "idp_sso_url": "https://accounts.google.com/o/saml2/idp?idpid={idp_id}",
            "name_id_format": NAMEID_EMAIL,
            "first_name_attribute": "firstName",
            "last_name_attribute": "lastName",
            "groups_attribute": "groups",
        },
    },
    "okta": {
        "label": "Okta",
        "placeholders": ["okta_domain", "app_id"],
        "oidc": {
            "issuer": "https://{okta_domain}",
            "scopes": ["openid", "email", "profile", "groups"],
            "email_claim": "email",
            "groups_claim": "groups",
        },
        "saml": {
            "idp_entity_id": "http://www.okta.com/{app_id}",
            "idp_sso_url": "https://{okta_domain}/app/messer/{app_id}/sso/saml",
            "name_id_format": NAMEID_EMAIL,
            "email_attribute": "email",
            "first_name_attribute": "firstName",
            "last_name_attribute": "lastName",
            "groups_attribute": "groups",
        },
    },
    "generic": {
        "label": "OIDC / SAML 2.0",
        "placeholders": [],
        "oidc": {"scopes": ["openid", "email", "profile"], "email_claim": "email", "groups_claim": "groups"},
        "saml": {"name_id_format": NAMEID_EMAIL, "email_attribute": "email", "groups_attribute": "groups"},
    },
}
NAME_ID_FORMATS = (NAMEID_EMAIL, NAMEID_PERSISTENT, "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified")


# ----------------------------------------------------------------------------- domains


def normalize_domain(value: str) -> str:
    raw = value.strip().lower().lstrip("@").rstrip(".")
    try:
        ascii_domain = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ApiError("Dominio no válido", code="invalid_domain") from exc
    if not _DOMAIN_RE.match(ascii_domain):
        raise ApiError("Dominio no válido", code="invalid_domain")
    return ascii_domain


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].strip().lower() if "@" in email else ""


def verification_record(domain: OrgDomain) -> dict[str, str]:
    return {
        "type": "TXT",
        "name": f"{VERIFICATION_RECORD_PREFIX}.{domain.domain}",
        "value": f"{VERIFICATION_VALUE_PREFIX}{domain.verification_token}",
    }


async def lookup_txt(name: str) -> list[str]:
    """TXT records of ``name`` (tests replace this function)."""
    try:
        answer = await dns.asyncresolver.resolve(name, "TXT", lifetime=5)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers, dns.exception.Timeout):
        return []
    values: list[str] = []
    for record in answer:
        strings = getattr(record, "strings", ())
        values.append(b"".join(strings).decode("utf-8", "replace"))
    return values


async def create_domain(session: AsyncSession, *, principal: Principal, domain: str) -> OrgDomain:
    assert principal.org_id is not None
    normalized = normalize_domain(domain)
    existing = (
        await session.execute(
            select(OrgDomain).where(OrgDomain.org_id == principal.org_id, OrgDomain.domain == normalized)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError("Ese dominio ya está añadido", code="domain_exists", status_code=409)
    row = OrgDomain(org_id=principal.org_id, domain=normalized, verification_token=random_token(18))
    session.add(row)
    await session.flush()
    await audit.record(
        session,
        action="sso.domain_added",
        principal=principal,
        entity_type="org_domain",
        entity_id=row.id,
        diff={"domain": normalized},
    )
    return row


async def verify_domain(
    session: AsyncSession, row: OrgDomain, *, principal: Principal, manual: bool = False
) -> OrgDomain:
    """Check the DNS TXT challenge (or, for superadmins, mark verified manually)."""
    now = datetime.now(UTC)
    row.last_checked_at = now
    if row.verified_at is not None:
        return row
    taken = (
        await session.execute(
            select(OrgDomain.id).where(
                OrgDomain.domain == row.domain, OrgDomain.verified_at.is_not(None), OrgDomain.id != row.id
            )
        )
    ).first()
    if taken is not None:
        raise ApiError("Otra organización ya ha verificado este dominio", code="domain_taken", status_code=409)
    if manual:
        if not principal.is_superadmin:
            raise ApiError("Solo un superadministrador puede verificar manualmente", code="forbidden", status_code=403)
        method = "manual"
    else:
        record = verification_record(row)
        values = await lookup_txt(record["name"])
        if record["value"] not in [v.strip() for v in values]:
            raise ApiError(
                "No encontramos el registro TXT de verificación. Los cambios de DNS pueden tardar unos minutos.",
                code="domain_unverified",
                status_code=409,
                details={"record": record, "found": values[:5]},
            )
        method = "dns"
    row.verified_at = now
    row.verified_by = principal.user_id
    row.verification_method = method
    await audit.record(
        session,
        action="sso.domain_verified",
        principal=principal,
        entity_type="org_domain",
        entity_id=row.id,
        diff={"domain": row.domain, "method": method},
    )
    return row


async def verified_domain(session: AsyncSession, org_id: uuid.UUID, domain: str) -> OrgDomain | None:
    return (
        await session.execute(
            select(OrgDomain).where(
                OrgDomain.org_id == org_id, OrgDomain.domain == domain.lower(), OrgDomain.verified_at.is_not(None)
            )
        )
    ).scalar_one_or_none()


async def org_verified_domains(session: AsyncSession, org_id: uuid.UUID) -> set[str]:
    rows = await session.execute(
        select(OrgDomain.domain).where(OrgDomain.org_id == org_id, OrgDomain.verified_at.is_not(None))
    )
    return {r[0] for r in rows}


# ----------------------------------------------------------------------------- plan features


async def org_has_feature(session: AsyncSession, org_id: uuid.UUID, feature: str) -> bool:
    plan = await org_plan(session, org_id)
    return plan is not None and plan_has_feature(plan.limits, feature)


# ----------------------------------------------------------------------------- configuration

ConnectionConfig = OidcConfig | SamlConfig


def apply_preset_defaults(kind: str, raw: dict[str, Any]) -> dict[str, Any]:
    preset = str(raw.get("preset") or "generic")
    if preset not in PRESETS:
        raise ApiError("Proveedor predefinido desconocido", code="invalid_preset")
    defaults = dict(PRESETS[preset].get(kind, {}))
    merged = {**{k: v for k, v in defaults.items() if "{" not in str(v)}, **raw}
    merged["preset"] = preset
    return merged


def parse_config(kind: str, raw: dict[str, Any]) -> ConnectionConfig:
    """Validate a connection configuration (SAML accepts pasted IdP metadata in ``metadata_xml``)."""
    data = apply_preset_defaults(kind, raw)
    try:
        if kind == "oidc":
            cfg = OidcConfig.model_validate(data)
            if not cfg.client_secret:
                raise ApiError("El client secret es obligatorio", code="invalid_config")
            if not cfg.issuer.startswith(("https://", "http://")):
                raise ApiError("El emisor debe ser una URL", code="invalid_config")
            return cfg
        if kind == "saml":
            metadata_xml = data.pop("metadata_xml", None)
            if metadata_xml:
                data = {**data, **parse_idp_metadata(str(metadata_xml))}
            certs = data.get("idp_certificates")
            if isinstance(certs, str):
                certs = [certs]
            data["idp_certificates"] = [normalize_certificate(str(c)) for c in (certs or []) if str(c).strip()]
            cfg = SamlConfig.model_validate(data)
            if not cfg.idp_sso_url.startswith(("https://", "http://")):
                raise ApiError("La URL de inicio de sesión del IdP debe ser una URL", code="invalid_config")
            return cfg
    except SsoProtocolError as exc:
        raise ApiError(exc.message, code=exc.code) from exc
    except ValueError as exc:  # pydantic.ValidationError is a ValueError
        raise ApiError(
            "Configuración SSO no válida", code="invalid_config", details={"error": str(exc)[:2000]}
        ) from exc
    raise ApiError("Tipo de conexión no válido", code="invalid_type")


def load_config(conn: SsoConnection) -> ConnectionConfig:
    data = decrypt_json(conn.config_encrypted)
    if conn.type == "oidc":
        return OidcConfig.model_validate(data)
    return SamlConfig.model_validate(data)


def store_config(conn: SsoConnection, cfg: ConnectionConfig) -> None:
    conn.config_encrypted = encrypt_json(cfg.model_dump(mode="json"))


def merge_config(conn: SsoConnection, patch: dict[str, Any]) -> ConnectionConfig:
    current = load_config(conn).model_dump(mode="json")
    patch = dict(patch)
    if conn.type == "oidc" and not patch.get("client_secret"):
        patch.pop("client_secret", None)  # keep the stored secret
    return parse_config(conn.type, {**current, **patch})


# ----------------------------------------------------------------------------- discovery & enforcement


async def discover(session: AsyncSession, email: str) -> SsoConnection | None:
    """Enabled connection for the email's domain whose organization verified the domain and has SSO."""
    domain = email_domain(email)
    if not domain:
        return None
    rows = (
        await session.execute(
            select(SsoConnection)
            .join(
                OrgDomain,
                (OrgDomain.org_id == SsoConnection.org_id)
                & (OrgDomain.domain == func.lower(SsoConnection.domain))
                & OrgDomain.verified_at.is_not(None),
            )
            .join(Org, Org.id == SsoConnection.org_id)
            .where(func.lower(SsoConnection.domain) == domain, SsoConnection.enabled.is_(True), Org.status != "blocked")
            .order_by(SsoConnection.created_at)
        )
    ).scalars()
    for conn in rows:
        if await org_has_feature(session, conn.org_id, "sso"):
            return conn
    return None


async def enforced_connection(session: AsyncSession, email: str) -> SsoConnection | None:
    conn = await discover(session, email)
    return conn if conn is not None and conn.enforce else None


async def assert_password_login_allowed(session: AsyncSession, email: str) -> None:
    """Login hook: refuse password (and social) login for emails of a domain that enforces SSO."""
    conn = await enforced_connection(session, email)
    if conn is None:
        return
    user = await find_user_by_email(session, email)
    if user is not None and user.is_superadmin:
        return  # platform operators keep break-glass access
    raise ApiError(
        "Tu organización exige iniciar sesión con SSO. Usa «SSO empresarial» para entrar.",
        code="sso_required",
        status_code=403,
        details={"sso_url": "/sso", "connection_name": conn.name},
    )


# ----------------------------------------------------------------------------- roles


def resolve_role(groups: list[str], mappings: list[SsoGroupMapping], default_role: str) -> str:
    wanted = {g.casefold() for g in groups}
    matched = [m.role for m in mappings if m.external_group.casefold() in wanted and m.role in ASSIGNABLE_ROLES]
    if not matched:
        return default_role if default_role in ASSIGNABLE_ROLES else "viewer"
    return max(matched, key=lambda r: ROLE_RANK[r])


async def connection_mappings(session: AsyncSession, connection_id: uuid.UUID) -> list[SsoGroupMapping]:
    rows = await session.execute(select(SsoGroupMapping).where(SsoGroupMapping.connection_id == connection_id))
    return list(rows.scalars())


async def apply_membership_role(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
    source: str,
    principal: Principal | None,
    force_role: bool,
) -> tuple[Membership, bool]:
    """Create the membership (``source``) or update an IdP-managed one. Returns (membership, changed)."""
    membership = (
        await session.execute(select(Membership).where(Membership.org_id == org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    if membership is None:
        membership = Membership(org_id=org_id, user_id=user_id, role=role, source=source)
        session.add(membership)
        await session.flush()
        await audit.record(
            session,
            action="member.provisioned",
            principal=principal,
            org_id=org_id,
            entity_type="user",
            entity_id=user_id,
            diff={"role": role, "source": source},
        )
        return membership, True
    if membership.role == "owner" or membership.source == "manual" or not force_role or membership.role == role:
        return membership, False
    before = membership.role
    membership.role = role
    await audit.record(
        session,
        action="member.role_changed",
        principal=principal,
        org_id=org_id,
        entity_type="user",
        entity_id=user_id,
        diff={"before": before, "after": role, "source": source},
    )
    return membership, True


# ----------------------------------------------------------------------------- login


@dataclass(slots=True)
class LoginOutcome:
    user: User
    org_id: uuid.UUID
    role: str
    created_user: bool
    created_membership: bool
    notes: list[str] = field(default_factory=list)


async def _check_identity(
    session: AsyncSession, conn: SsoConnection, cfg: ConnectionConfig, identity: SsoIdentity
) -> None:
    domain = email_domain(identity.email)
    if domain != conn.domain.lower():
        raise SsoProtocolError(
            "domain_mismatch", f"El email {identity.email} no pertenece al dominio {conn.domain} de esta conexión"
        )
    if await verified_domain(session, conn.org_id, domain) is None:
        raise SsoProtocolError("domain_not_verified", f"El dominio {domain} no está verificado por la organización")
    if isinstance(cfg, OidcConfig) and cfg.hosted_domain_claim:
        if str(identity.attributes.get(cfg.hosted_domain_claim) or "").lower() != conn.domain.lower():
            raise SsoProtocolError("hosted_domain_mismatch", "La cuenta no pertenece al dominio de Google Workspace")


async def evaluate_login(
    session: AsyncSession, conn: SsoConnection, cfg: ConnectionConfig, identity: SsoIdentity
) -> dict[str, Any]:
    """Dry run used by "test connection": what a real login would do, without changing anything."""
    problems: list[dict[str, str]] = []
    try:
        await _check_identity(session, conn, cfg, identity)
    except SsoProtocolError as exc:
        problems.append({"code": exc.code, "message": exc.message})
    if not await org_has_feature(session, conn.org_id, "sso"):
        problems.append({"code": "plan_feature", "message": "El plan actual no incluye SSO"})
    user = await find_user_by_email(session, identity.email)
    membership = None
    if user is not None:
        membership = (
            await session.execute(
                select(Membership).where(Membership.org_id == conn.org_id, Membership.user_id == user.id)
            )
        ).scalar_one_or_none()
    mappings = await connection_mappings(session, conn.id)
    role = resolve_role(identity.groups, mappings, conn.default_role)
    if membership is not None and (membership.source == "manual" or membership.role == "owner" or not mappings):
        role = membership.role
    if user is None and not cfg.jit_provisioning:
        problems.append(
            {"code": "jit_disabled", "message": "El usuario no existe y el alta automática está desactivada"}
        )
    return {
        "ok": not problems,
        "problems": problems,
        "identity": {
            "subject": identity.subject,
            "email": identity.email,
            "name": identity.name,
            "groups": identity.groups,
            "mfa": identity.mfa,
        },
        "user_exists": user is not None,
        "member": membership is not None,
        "role": role,
        "matched_groups": sorted(
            {
                m.external_group
                for m in mappings
                if m.external_group.casefold() in {g.casefold() for g in identity.groups}
            }
        ),
    }


async def complete_login(
    session: AsyncSession, conn: SsoConnection, cfg: ConnectionConfig, identity: SsoIdentity
) -> LoginOutcome:
    """Validate the asserted identity, provision the user (JIT) and membership, map groups to a role."""
    await _check_identity(session, conn, cfg, identity)
    if not await org_has_feature(session, conn.org_id, "sso"):
        raise SsoProtocolError("plan_feature", "El plan de la organización ya no incluye SSO")
    org = await session.get(Org, conn.org_id)
    if org is None or org.status == "blocked":
        raise SsoProtocolError("org_unavailable", "La organización no está disponible")
    now = datetime.now(UTC)

    link = (
        await session.execute(
            select(OrgIdentity).where(OrgIdentity.connection_id == conn.id, OrgIdentity.sso_subject == identity.subject)
        )
    ).scalar_one_or_none()
    user: User | None = await session.get(User, link.user_id) if link is not None else None
    if user is not None and user.email != identity.email:
        # The IdP renamed the account inside the verified domain: follow it unless the email is taken.
        if await find_user_by_email(session, identity.email) is None:
            user.email = identity.email
    if user is None:
        user = await find_user_by_email(session, identity.email)
    created_user = False
    if user is None:
        if not cfg.jit_provisioning:
            raise SsoProtocolError("jit_disabled", "Tu cuenta no está dada de alta. Pide acceso a tu administrador.")
        user = User(id=uuid.uuid4(), email=identity.email, name=identity.name, locale="es")
        session.add(user)
        await session.flush()
        session.add(AuthCredential(user_id=user.id, email_verified_at=now))
        created_user = True
    if user.deleted_at is not None or user.status == "deleted":
        raise SsoProtocolError("user_deleted", "Esta cuenta ha sido eliminada")
    if user.status == "blocked":
        raise SsoProtocolError("user_blocked", "Tu cuenta está bloqueada. Contacta con soporte.")
    if not user.name and identity.name:
        user.name = identity.name

    org_identity = (
        link
        or (
            await session.execute(
                select(OrgIdentity).where(OrgIdentity.org_id == conn.org_id, OrgIdentity.user_id == user.id)
            )
        ).scalar_one_or_none()
    )
    if org_identity is not None and org_identity.scim_managed and not org_identity.active:
        raise SsoProtocolError("deprovisioned", "Tu acceso a esta organización ha sido desactivado")

    existing = (
        await session.execute(select(Membership).where(Membership.org_id == conn.org_id, Membership.user_id == user.id))
    ).scalar_one_or_none()
    if existing is None and not cfg.jit_provisioning:
        raise SsoProtocolError("jit_disabled", "No eres miembro de esta organización. Pide acceso a tu administrador.")
    mappings = await connection_mappings(session, conn.id)
    role = resolve_role(identity.groups, mappings, conn.default_role)
    actor = Principal(user_id=user.id, org_id=conn.org_id)
    membership, _ = await apply_membership_role(
        session,
        org_id=conn.org_id,
        user_id=user.id,
        role=role,
        source="sso",
        principal=actor,
        force_role=bool(mappings),
    )

    if org_identity is None:
        org_identity = OrgIdentity(org_id=conn.org_id, user_id=user.id)
        session.add(org_identity)
    org_identity.connection_id = conn.id
    org_identity.sso_subject = identity.subject
    org_identity.sso_groups = list(identity.groups)
    org_identity.last_login_at = now
    org_identity.given_name = identity.given_name or org_identity.given_name
    org_identity.family_name = identity.family_name or org_identity.family_name
    org_identity.display_name = identity.name or org_identity.display_name
    await session.flush()

    if created_user:
        await audit.record(
            session,
            action="sso.user_provisioned",
            principal=actor,
            entity_type="user",
            entity_id=user.id,
            diff={"connection_id": str(conn.id), "email": user.email},
        )
    await audit.record(
        session,
        action="sso.login",
        principal=actor,
        entity_type="sso_connection",
        entity_id=conn.id,
        diff={"type": conn.type, "role": membership.role, "groups": identity.groups[:50], "mfa": identity.mfa},
    )
    return LoginOutcome(
        user=user,
        org_id=conn.org_id,
        role=membership.role,
        created_user=created_user,
        created_membership=existing is None,
    )


async def mark_assertion_used(
    session: AsyncSession, *, connection_id: uuid.UUID, assertion_id: str, expires_at: datetime
) -> bool:
    """Replay protection: record a SAML assertion ID; False if it was already used."""
    stmt = (
        pg_insert(OneTimeToken)
        .values(
            id=uuid.uuid4(),
            purpose="saml_assertion",
            token_hash=hash_token(f"saml:{connection_id}:{assertion_id}"),
            payload={"connection_id": str(connection_id)},
            expires_at=expires_at,
            used_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["token_hash"])
        .returning(OneTimeToken.id)
    )
    return (await session.execute(stmt)).first() is not None
