"""SCIM 2.0 service provider (RFC 7643/7644) for automatic user provisioning and deprovisioning.

Resources live per organization (the bearer SCIM token identifies it):

* ``User``  — the SCIM ``id`` is the Messer user id; state lives in ``org_identities`` (``scim_managed``).
  ``active = false`` (or DELETE) deprovisions: the membership is removed and every session is revoked.
  New accounts can only be created for emails of a domain the organization has verified.
* ``Group`` — ``scim_groups``/``scim_group_members``; roles derive from ``sso_group_mappings`` matching the
  group's displayName, externalId or id. Owners are never changed by SCIM.

The filter grammar supports ``eq ne co sw ew pr gt ge lt le``, ``and``/``or``/``not``, parentheses and value
paths (``emails[type eq "work"]``), which covers Okta, Microsoft Entra ID and OneLogin request flows.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from messer_common import audit
from messer_common.db import Principal
from messer_common.db.models import AuthCredential, AuthSession, Membership, SsoConnection, SsoGroupMapping, User
from messer_common.db.models.enterprise import OrgIdentity, ScimGroup, ScimGroupMember
from messer_common.settings import get_settings

from .auth import find_user_by_email
from .sso import ASSIGNABLE_ROLES, apply_membership_role, email_domain, org_verified_domains, resolve_role

SCHEMA_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
SCHEMA_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
SCHEMA_ENTERPRISE_USER = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
SCHEMA_LIST = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCHEMA_PATCH = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
SCHEMA_ERROR = "urn:ietf:params:scim:api:messages:2.0:Error"
SCHEMA_SPC = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
SCHEMA_RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:Schema"
MAX_PAGE = 200
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ScimError(Exception):
    def __init__(self, status: int, detail: str, scim_type: str | None = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schemas": [SCHEMA_ERROR], "status": str(self.status), "detail": self.detail}
        if self.scim_type:
            out["scimType"] = self.scim_type
        return out


@dataclass(slots=True)
class ScimContext:
    org_id: uuid.UUID
    token_id: uuid.UUID

    @property
    def principal(self) -> Principal:
        return Principal(user_id=None, org_id=self.org_id)


def base_url() -> str:
    return f"{get_settings().messer_api_url.rstrip('/')}/scim/v2"


# ============================================================================= filters


@dataclass(slots=True)
class Compare:
    attr: str
    op: str
    value: Any = None


@dataclass(slots=True)
class Logical:
    op: str  # and | or
    left: Node
    right: Node


@dataclass(slots=True)
class Negation:
    node: Node


@dataclass(slots=True)
class ValuePath:
    attr: str
    node: Node
    sub_attr: str | None = None


Node = Compare | Logical | Negation | ValuePath

_TOKEN_RE = re.compile(
    r"""\s*(?:
        (?P<lparen>\() | (?P<rparen>\)) | (?P<lbracket>\[) | (?P<rbracket>\]) |
        (?P<string>"(?:[^"\\]|\\.)*") |
        (?P<number>-?\d+(?:\.\d+)?(?![\w.:])) |
        (?P<subattr>\.[A-Za-z_$][\w$\-]*) |
        (?P<word>[A-Za-z_$][\w$.:\-]*)
    )""",
    re.VERBOSE,
)
_OPS = {"eq", "ne", "co", "sw", "ew", "pr", "gt", "ge", "lt", "le"}


def _tokenize(text: str) -> list[tuple[str, str]]:
    pos, tokens = 0, []
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN_RE.match(text, pos)
        if match is None or match.end() == pos:
            raise ScimError(400, f"Filtro no válido cerca de: {text[pos : pos + 20]!r}", "invalidFilter")
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind)))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.tokens = _tokenize(text)
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self, kind: str | None = None) -> tuple[str, str]:
        tok = self.peek()
        if tok is None or (kind is not None and tok[0] != kind):
            raise ScimError(400, "Filtro incompleto o mal formado", "invalidFilter")
        self.i += 1
        return tok

    def keyword(self, word: str) -> bool:
        tok = self.peek()
        if tok is not None and tok[0] == "word" and tok[1].lower() == word:
            self.i += 1
            return True
        return False

    def parse(self) -> Node:
        node = self.parse_or()
        if self.peek() is not None:
            raise ScimError(400, "Filtro con elementos sobrantes", "invalidFilter")
        return node

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.keyword("or"):
            node = Logical("or", node, self.parse_and())
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self.keyword("and"):
            node = Logical("and", node, self.parse_not())
        return node

    def parse_not(self) -> Node:
        if self.keyword("not"):
            self.take("lparen")
            inner = self.parse_or()
            self.take("rparen")
            return Negation(inner)
        return self.parse_atom()

    def parse_atom(self) -> Node:
        tok = self.peek()
        if tok is None:
            raise ScimError(400, "Filtro vacío", "invalidFilter")
        if tok[0] == "lparen":
            self.take()
            inner = self.parse_or()
            self.take("rparen")
            return inner
        attr = self.take("word")[1]
        nxt = self.peek()
        if nxt is not None and nxt[0] == "lbracket":
            self.take()
            inner = self.parse_or()
            self.take("rbracket")
            sub = None
            after = self.peek()
            if after is not None and after[0] == "subattr":
                sub = self.take()[1][1:]
            return ValuePath(attr, inner, sub)
        op = self.take("word")[1].lower()
        if op not in _OPS:
            raise ScimError(400, f"Operador de filtro no soportado: {op}", "invalidFilter")
        if op == "pr":
            return Compare(attr, op)
        kind, raw = self.take()
        value: Any
        if kind == "string":
            value = bytes(raw[1:-1], "utf-8").decode("unicode_escape")
        elif kind == "number":
            value = float(raw) if "." in raw else int(raw)
        elif kind == "word" and raw.lower() in ("true", "false", "null"):
            value = {"true": True, "false": False, "null": None}[raw.lower()]
        else:
            raise ScimError(400, "Valor de filtro no válido", "invalidFilter")
        return Compare(attr, op, value)


def parse_filter(text: str) -> Node:
    return _Parser(text).parse()


def _strip_schema(attr: str) -> str:
    # "urn:ietf:params:scim:schemas:core:2.0:User:userName" → "userName"
    if attr.lower().startswith("urn:"):
        for schema in (SCHEMA_USER, SCHEMA_GROUP, SCHEMA_ENTERPRISE_USER):
            if attr.lower().startswith(schema.lower() + ":"):
                rest = attr[len(schema) + 1 :]
                return rest if schema != SCHEMA_ENTERPRISE_USER else f"{SCHEMA_ENTERPRISE_USER}:{rest}"
    return attr


def _get(obj: Any, key: str) -> Any:
    if not isinstance(obj, dict):
        return None
    for k, v in obj.items():
        if str(k).lower() == key.lower():
            return v
    return None


def _values(resource: dict[str, Any], attr: str) -> list[Any]:
    attr = _strip_schema(attr)
    if attr.startswith(SCHEMA_ENTERPRISE_USER + ":"):
        ext = _get(resource, SCHEMA_ENTERPRISE_USER) or {}
        return _values(ext, attr[len(SCHEMA_ENTERPRISE_USER) + 1 :])
    current: list[Any] = [resource]
    for part in attr.split("."):
        nxt: list[Any] = []
        for item in current:
            value = _get(item, part)
            if isinstance(value, list):
                nxt.extend(value)
            elif value is not None:
                nxt.append(value)
        current = nxt
    # A bare multi-valued complex attribute ("emails eq x") compares its "value" sub-attribute.
    flat: list[Any] = []
    for item in current:
        flat.append(_get(item, "value") if isinstance(item, dict) else item)
    return flat


_CASE_EXACT = {"id", "externalid"}


def _compare(op: str, actual: Any, expected: Any, case_exact: bool) -> bool:
    a: Any
    e: Any
    if isinstance(actual, str) and isinstance(expected, str) and not case_exact:
        a, e = actual.lower(), expected.lower()
    else:
        a, e = actual, expected
    if isinstance(a, bool) or isinstance(e, bool):
        if isinstance(a, str):
            a = a.lower() == "true"
    try:
        if op == "eq":
            return a == e
        if op == "ne":
            return a != e
        if op == "co":
            return isinstance(a, str) and isinstance(e, str) and e in a
        if op == "sw":
            return isinstance(a, str) and isinstance(e, str) and a.startswith(e)
        if op == "ew":
            return isinstance(a, str) and isinstance(e, str) and a.endswith(e)
        if op == "gt":
            return a > e
        if op == "ge":
            return a >= e
        if op == "lt":
            return a < e
        if op == "le":
            return a <= e
    except TypeError:
        return False
    return False


def matches(node: Node, resource: dict[str, Any]) -> bool:
    if isinstance(node, Logical):
        if node.op == "and":
            return matches(node.left, resource) and matches(node.right, resource)
        return matches(node.left, resource) or matches(node.right, resource)
    if isinstance(node, Negation):
        return not matches(node.node, resource)
    if isinstance(node, ValuePath):
        items = _get(resource, _strip_schema(node.attr))
        items = items if isinstance(items, list) else ([items] if isinstance(items, dict) else [])
        return any(isinstance(item, dict) and matches(node.node, item) for item in items)
    values = _values(resource, node.attr)
    if node.op == "pr":
        return any(v not in (None, "", [], {}) for v in values)
    case_exact = _strip_schema(node.attr).split(".")[-1].lower() in _CASE_EXACT
    if node.op == "ne":
        return all(_compare("ne", v, node.value, case_exact) for v in values) if values else node.value is not None
    return any(_compare(node.op, v, node.value, case_exact) for v in values)


def project(resource: dict[str, Any], attributes: str | None, excluded: str | None) -> dict[str, Any]:
    """``attributes`` / ``excludedAttributes`` query parameters (top-level attributes)."""
    always = {"schemas", "id", "meta"}
    if attributes:
        wanted = {_strip_schema(a.strip()).split(".")[0].lower() for a in attributes.split(",") if a.strip()}
        return {k: v for k, v in resource.items() if k.lower() in wanted or k in always}
    if excluded:
        drop = {_strip_schema(a.strip()).split(".")[0].lower() for a in excluded.split(",") if a.strip()}
        return {k: v for k, v in resource.items() if k.lower() not in drop or k in always}
    return resource


# ============================================================================= helpers


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


def _version(*parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in ("true", "1", "yes"):
            return True
        if value.strip().lower() in ("false", "0", "no"):
            return False
    if isinstance(value, int):
        return bool(value)
    raise ScimError(400, f"Valor booleano no válido: {value!r}", "invalidValue")


def _parse_uuid(value: str, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ScimError(404, f"{what} {value} no encontrado") from exc


async def org_mappings(session: AsyncSession, org_id: uuid.UUID) -> list[SsoGroupMapping]:
    rows = await session.execute(select(SsoGroupMapping).where(SsoGroupMapping.org_id == org_id))
    return list(rows.scalars())


async def org_default_role(session: AsyncSession, org_id: uuid.UUID) -> str:
    role = (
        await session.execute(
            select(SsoConnection.default_role)
            .where(SsoConnection.org_id == org_id, SsoConnection.enabled.is_(True))
            .order_by(SsoConnection.created_at)
        )
    ).first()
    return role[0] if role and role[0] in ASSIGNABLE_ROLES else "viewer"


async def _user_groups(
    session: AsyncSession, org_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ScimGroup]]:
    out: dict[uuid.UUID, list[ScimGroup]] = {uid: [] for uid in user_ids}
    if not user_ids:
        return out
    rows = await session.execute(
        select(ScimGroupMember.user_id, ScimGroup)
        .join(ScimGroup, ScimGroup.id == ScimGroupMember.group_id)
        .where(ScimGroupMember.org_id == org_id, ScimGroupMember.user_id.in_(user_ids))
        .order_by(ScimGroup.display_name)
    )
    for user_id, group in rows:
        out.setdefault(user_id, []).append(group)
    return out


async def compute_role(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> tuple[str, bool]:
    """(role from the user's SCIM groups through the org's group mappings, whether mappings exist)."""
    groups = (await _user_groups(session, org_id, [user_id]))[user_id]
    names: list[str] = []
    for g in groups:
        names.extend([g.display_name, str(g.id), *([g.external_id] if g.external_id else [])])
    mappings = await org_mappings(session, org_id)
    return resolve_role(names, mappings, await org_default_role(session, org_id)), bool(mappings)


async def sync_role(session: AsyncSession, ctx: ScimContext, user_id: uuid.UUID) -> None:
    ident = await _identity(session, ctx.org_id, user_id)
    if ident is None or not ident.active:
        return
    role, has_mappings = await compute_role(session, ctx.org_id, user_id)
    await apply_membership_role(
        session,
        org_id=ctx.org_id,
        user_id=user_id,
        role=role,
        source="scim",
        principal=ctx.principal,
        force_role=has_mappings,
    )


async def _identity(session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID) -> OrgIdentity | None:
    return (
        await session.execute(select(OrgIdentity).where(OrgIdentity.org_id == org_id, OrgIdentity.user_id == user_id))
    ).scalar_one_or_none()


async def _owner_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.org_id == org_id, Membership.role == "owner")
            )
        ).scalar_one()
    )


async def deprovision(session: AsyncSession, ctx: ScimContext, user_id: uuid.UUID, *, reason: str) -> bool:
    """Remove the membership and revoke every session of the user. Returns whether a membership was removed."""
    membership = (
        await session.execute(select(Membership).where(Membership.org_id == ctx.org_id, Membership.user_id == user_id))
    ).scalar_one_or_none()
    removed = False
    if membership is not None:
        if membership.role == "owner" and await _owner_count(session, ctx.org_id) <= 1:
            raise ScimError(400, "No se puede desactivar al único propietario de la organización", "mutability")
        await session.delete(membership)
        removed = True
    now = datetime.now(UTC)
    revoked = cast(
        "CursorResult[Any]",
        await session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        ),
    )
    await audit.record(
        session,
        action="member.deprovisioned",
        principal=ctx.principal,
        entity_type="user",
        entity_id=user_id,
        diff={"source": "scim", "reason": reason, "membership_removed": removed, "sessions_revoked": revoked.rowcount},
    )
    return removed


# ============================================================================= users


def user_resource(user: User, ident: OrgIdentity, groups: list[ScimGroup]) -> dict[str, Any]:
    location = f"{base_url()}/Users/{user.id}"
    given, family = ident.given_name, ident.family_name
    formatted = " ".join(p for p in (given, family) if p) or None
    resource: dict[str, Any] = {
        "schemas": [SCHEMA_USER],
        "id": str(user.id),
        "userName": ident.scim_user_name or user.email,
        "name": {k: v for k, v in {"givenName": given, "familyName": family, "formatted": formatted}.items() if v},
        "displayName": ident.display_name or user.name or formatted or user.email,
        "emails": [{"value": user.email, "type": "work", "primary": True}],
        "active": bool(ident.active),
        "groups": [
            {"value": str(g.id), "display": g.display_name, "$ref": f"{base_url()}/Groups/{g.id}"} for g in groups
        ],
        "meta": {
            "resourceType": "User",
            "created": _iso(ident.created_at),
            "lastModified": _iso(ident.updated_at),
            "location": location,
            "version": _version(user.id, ident.updated_at, ident.active, user.email),
        },
    }
    if ident.scim_external_id:
        resource["externalId"] = ident.scim_external_id
    extra = dict(ident.attributes or {})
    enterprise = extra.pop(SCHEMA_ENTERPRISE_USER, None)
    for key in ("title", "nickName", "preferredLanguage", "locale", "timezone", "userType"):
        if key in extra:
            resource[key] = extra[key]
    if isinstance(enterprise, dict) and enterprise:
        resource["schemas"].append(SCHEMA_ENTERPRISE_USER)
        resource[SCHEMA_ENTERPRISE_USER] = enterprise
    return resource


@dataclass(slots=True)
class _UserState:
    user_name: str | None = None
    external_id: str | None = None
    active: bool = True
    given_name: str | None = None
    family_name: str | None = None
    display_name: str | None = None
    email: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


def _email_from(payload_emails: Any) -> str | None:
    if not isinstance(payload_emails, list):
        return None
    candidates = [e for e in payload_emails if isinstance(e, dict) and isinstance(e.get("value"), str)]
    primary = [e for e in candidates if e.get("primary") in (True, "true", "True")]
    work = [e for e in candidates if str(e.get("type", "")).lower() == "work"]
    for group in (primary, work, candidates):
        if group:
            return str(group[0]["value"]).strip().lower()
    return None


def _state_from_payload(payload: dict[str, Any]) -> _UserState:
    state = _UserState()
    _apply_user_value(state, None, payload)
    if "active" not in {k.lower() for k in payload}:
        state.active = True
    return state


def _apply_user_value(state: _UserState, path: str | None, value: Any, op: str = "replace") -> None:
    """Apply one attribute (or a dict of attributes when ``path`` is None) to the editable user state."""
    if path is None:
        if not isinstance(value, dict):
            raise ScimError(400, "La operación sin path requiere un objeto", "invalidValue")
        for key, sub in value.items():
            if key == "schemas" or key == "id" or key == "meta":
                continue
            if str(key).lower() == SCHEMA_ENTERPRISE_USER.lower() and isinstance(sub, dict):
                ext = dict(state.attributes.get(SCHEMA_ENTERPRISE_USER) or {})
                ext.update(sub)
                state.attributes[SCHEMA_ENTERPRISE_USER] = ext
                continue
            _apply_user_value(state, str(key), sub, op)
        return
    raw = _strip_schema(path)
    if raw.startswith(SCHEMA_ENTERPRISE_USER + ":"):
        attr = raw[len(SCHEMA_ENTERPRISE_USER) + 1 :]
        ext = dict(state.attributes.get(SCHEMA_ENTERPRISE_USER) or {})
        if op == "remove":
            ext.pop(attr, None)
        else:
            ext[attr] = value
        state.attributes[SCHEMA_ENTERPRISE_USER] = ext
        return
    key = raw.lower()
    removing = op == "remove"
    if key == "username":
        if removing or not isinstance(value, str) or not value.strip():
            raise ScimError(400, "userName es obligatorio", "invalidValue")
        state.user_name = value.strip()
    elif key == "externalid":
        state.external_id = None if removing else (str(value) if value is not None else None)
    elif key == "active":
        state.active = False if removing else _bool(value)
    elif key == "displayname":
        state.display_name = None if removing else (str(value) if value else None)
    elif key == "name":
        if removing:
            state.given_name = state.family_name = None
        elif isinstance(value, dict):
            lowered = {str(k).lower(): v for k, v in value.items()}
            if "givenname" in lowered:
                state.given_name = str(lowered["givenname"]) if lowered["givenname"] else None
            if "familyname" in lowered:
                state.family_name = str(lowered["familyname"]) if lowered["familyname"] else None
    elif key == "name.givenname":
        state.given_name = None if removing else (str(value) if value else None)
    elif key == "name.familyname":
        state.family_name = None if removing else (str(value) if value else None)
    elif key == "name.formatted":
        return
    elif key.startswith("emails"):
        if removing:
            return  # the account email is required; ignore removals of secondary emails
        if isinstance(value, list):
            email = _email_from(value)
        elif isinstance(value, str):
            email = value.strip().lower()
        elif isinstance(value, dict):
            email = _email_from([value])
        else:
            email = None
        if email:
            state.email = email
    elif key in ("groups", "meta", "id", "schemas", "password"):
        return  # read-only / ignored (Messer does not accept SCIM passwords)
    else:
        top = raw.split(".")[0].split("[")[0]
        if removing:
            state.attributes.pop(top, None)
        else:
            state.attributes[top] = value


def _resolved_email(state: _UserState) -> str:
    email = state.email or (state.user_name.strip().lower() if state.user_name and "@" in state.user_name else None)
    if not email or not EMAIL_RE.match(email):
        raise ScimError(400, "El usuario necesita un email válido (userName o emails)", "invalidValue")
    return email


async def _load_user(session: AsyncSession, ctx: ScimContext, user_id: str) -> tuple[User, OrgIdentity]:
    uid = _parse_uuid(user_id, "Usuario")
    ident = await _identity(session, ctx.org_id, uid)
    user = await session.get(User, uid)
    if ident is None or not ident.scim_managed or user is None or user.deleted_at is not None:
        raise ScimError(404, f"Usuario {user_id} no encontrado")
    return user, ident


async def get_user(session: AsyncSession, ctx: ScimContext, user_id: str) -> dict[str, Any]:
    user, ident = await _load_user(session, ctx, user_id)
    groups = (await _user_groups(session, ctx.org_id, [user.id]))[user.id]
    return user_resource(user, ident, groups)


async def list_users(
    session: AsyncSession, ctx: ScimContext, *, filter_text: str | None, start_index: int, count: int
) -> tuple[int, list[dict[str, Any]]]:
    node = parse_filter(filter_text) if filter_text else None
    q = (
        select(User, OrgIdentity)
        .join(OrgIdentity, OrgIdentity.user_id == User.id)
        .where(OrgIdentity.org_id == ctx.org_id, OrgIdentity.scim_managed.is_(True), User.deleted_at.is_(None))
        .order_by(OrgIdentity.created_at, User.id)
    )
    # Fast path for the lookups identity providers do before every create.
    if isinstance(node, Compare) and node.op == "eq" and isinstance(node.value, str):
        attr = _strip_schema(node.attr).lower()
        if attr == "username":
            q = q.where(func.lower(func.coalesce(OrgIdentity.scim_user_name, User.email)) == node.value.lower())
        elif attr == "externalid":
            q = q.where(OrgIdentity.scim_external_id == node.value)
        elif attr == "id":
            try:
                q = q.where(User.id == uuid.UUID(node.value))
            except ValueError:
                return 0, []
    rows = (await session.execute(q)).all()
    groups = await _user_groups(session, ctx.org_id, [u.id for u, _ in rows])
    resources = [user_resource(u, i, groups.get(u.id, [])) for u, i in rows]
    if node is not None:
        resources = [r for r in resources if matches(node, r)]
    total = len(resources)
    start = max(start_index, 1) - 1
    return total, resources[start : start + max(0, min(count, MAX_PAGE))]


async def _persist_user_state(
    session: AsyncSession, ctx: ScimContext, user: User, ident: OrgIdentity, state: _UserState, *, is_new: bool = False
) -> None:
    verified = await org_verified_domains(session, ctx.org_id)
    owns_account = email_domain(user.email) in verified
    new_email = _resolved_email(state)
    if new_email != user.email:
        if not owns_account or email_domain(new_email) not in verified:
            raise ScimError(400, "Solo se puede cambiar el email dentro de un dominio verificado", "invalidValue")
        taken = await find_user_by_email(session, new_email)
        if taken is not None and taken.id != user.id:
            raise ScimError(409, "Ya existe un usuario con ese email", "uniqueness")
        user.email = new_email
    if state.user_name:
        duplicate = (
            await session.execute(
                select(OrgIdentity.id).where(
                    OrgIdentity.org_id == ctx.org_id,
                    OrgIdentity.scim_managed.is_(True),
                    func.lower(OrgIdentity.scim_user_name) == state.user_name.lower(),
                    OrgIdentity.id != ident.id,
                )
            )
        ).first()
        if duplicate is not None:
            raise ScimError(409, "userName ya existe", "uniqueness")
    ident.scim_user_name = state.user_name or new_email
    ident.scim_external_id = state.external_id
    ident.given_name = state.given_name
    ident.family_name = state.family_name
    ident.display_name = state.display_name
    ident.attributes = state.attributes
    ident.updated_at = datetime.now(UTC)
    if owns_account:
        full = state.display_name or " ".join(p for p in (state.given_name, state.family_name) if p)
        if full:
            user.name = full[:200]
    was_active = ident.active
    ident.active = state.active
    await session.flush()
    if state.active:
        await sync_role(session, ctx, user.id)
        if not was_active and not is_new:
            await audit.record(
                session,
                action="member.reactivated",
                principal=ctx.principal,
                entity_type="user",
                entity_id=user.id,
                diff={"source": "scim"},
            )
    elif (
        was_active
        or (
            await session.execute(
                select(Membership.id).where(Membership.org_id == ctx.org_id, Membership.user_id == user.id)
            )
        ).first()
        is not None
    ):
        await deprovision(session, ctx, user.id, reason="active=false")


async def create_user(session: AsyncSession, ctx: ScimContext, payload: dict[str, Any]) -> dict[str, Any]:
    state = _state_from_payload(payload)
    if not state.user_name:
        raise ScimError(400, "userName es obligatorio", "invalidValue")
    email = _resolved_email(state)
    user = await find_user_by_email(session, email)
    created = False
    if user is None:
        if email_domain(email) not in await org_verified_domains(session, ctx.org_id):
            raise ScimError(
                400,
                f"El dominio {email_domain(email)} no está verificado por la organización: verifica el dominio en Messer",
                "invalidValue",
            )
        user = User(id=uuid.uuid4(), email=email, name=None, locale="es")
        session.add(user)
        await session.flush()
        session.add(AuthCredential(user_id=user.id, email_verified_at=datetime.now(UTC)))
        created = True
    elif user.deleted_at is not None:
        raise ScimError(409, "La cuenta asociada a este email fue eliminada", "uniqueness")
    ident = await _identity(session, ctx.org_id, user.id)
    if ident is not None and ident.scim_managed:
        raise ScimError(409, "El usuario ya está aprovisionado", "uniqueness")
    if ident is None:
        ident = OrgIdentity(org_id=ctx.org_id, user_id=user.id, active=True)
        session.add(ident)
    ident.scim_managed = True
    ident.active = False  # _persist_user_state provisions the membership when the state is active
    await session.flush()
    await _persist_user_state(session, ctx, user, ident, state, is_new=True)
    await audit.record(
        session,
        action="scim.user_created",
        principal=ctx.principal,
        entity_type="user",
        entity_id=user.id,
        diff={"email": user.email, "new_account": created, "active": state.active},
    )
    groups = (await _user_groups(session, ctx.org_id, [user.id]))[user.id]
    return user_resource(user, ident, groups)


def _state_from_identity(user: User, ident: OrgIdentity) -> _UserState:
    return _UserState(
        user_name=ident.scim_user_name or user.email,
        external_id=ident.scim_external_id,
        active=ident.active,
        given_name=ident.given_name,
        family_name=ident.family_name,
        display_name=ident.display_name,
        email=user.email,
        attributes=dict(ident.attributes or {}),
    )


async def replace_user(
    session: AsyncSession, ctx: ScimContext, user_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    user, ident = await _load_user(session, ctx, user_id)
    state = _state_from_payload(payload)
    if not state.user_name:
        raise ScimError(400, "userName es obligatorio", "invalidValue")
    if state.email is None:
        state.email = state.user_name.lower() if "@" in state.user_name else user.email
    await _persist_user_state(session, ctx, user, ident, state)
    await audit.record(
        session,
        action="scim.user_replaced",
        principal=ctx.principal,
        entity_type="user",
        entity_id=user.id,
        diff={"active": state.active},
    )
    return await get_user(session, ctx, user_id)


def _operations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ops = payload.get("Operations") or payload.get("operations")
    if not isinstance(ops, list) or not ops:
        raise ScimError(400, "PatchOp sin Operations", "invalidSyntax")
    out: list[dict[str, Any]] = []
    for op in ops:
        if not isinstance(op, dict) or str(op.get("op", "")).lower() not in ("add", "replace", "remove"):
            raise ScimError(400, "Operación PATCH no válida", "invalidSyntax")
        out.append({"op": str(op["op"]).lower(), "path": op.get("path"), "value": op.get("value")})
    return out


async def patch_user(session: AsyncSession, ctx: ScimContext, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    user, ident = await _load_user(session, ctx, user_id)
    state = _state_from_identity(user, ident)
    for op in _operations(payload):
        path = op["path"]
        if path is None and op["op"] == "remove":
            raise ScimError(400, "remove requiere path", "noTarget")
        _apply_user_value(state, str(path) if path is not None else None, op["value"], op["op"])
    await _persist_user_state(session, ctx, user, ident, state)
    await audit.record(
        session,
        action="scim.user_patched",
        principal=ctx.principal,
        entity_type="user",
        entity_id=user.id,
        diff={
            "operations": [{"op": o["op"], "path": o["path"]} for o in _operations(payload)][:20],
            "active": state.active,
        },
    )
    return await get_user(session, ctx, user_id)


async def delete_user(session: AsyncSession, ctx: ScimContext, user_id: str) -> None:
    user, ident = await _load_user(session, ctx, user_id)
    await deprovision(session, ctx, user.id, reason="deleted")
    await session.execute(
        delete(ScimGroupMember).where(ScimGroupMember.org_id == ctx.org_id, ScimGroupMember.user_id == user.id)
    )
    await session.delete(ident)
    await audit.record(
        session,
        action="scim.user_deleted",
        principal=ctx.principal,
        entity_type="user",
        entity_id=user.id,
        diff={"email": user.email},
    )


# ============================================================================= groups


async def _group_members(
    session: AsyncSession, group_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[tuple[uuid.UUID, str]]]:
    out: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {gid: [] for gid in group_ids}
    if not group_ids:
        return out
    rows = await session.execute(
        select(ScimGroupMember.group_id, User.id, User.email)
        .join(User, User.id == ScimGroupMember.user_id)
        .where(ScimGroupMember.group_id.in_(group_ids))
        .order_by(User.email)
    )
    for gid, uid, email in rows:
        out.setdefault(gid, []).append((uid, email))
    return out


def group_resource(group: ScimGroup, members: list[tuple[uuid.UUID, str]]) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "schemas": [SCHEMA_GROUP],
        "id": str(group.id),
        "displayName": group.display_name,
        "members": [
            {"value": str(uid), "display": email, "$ref": f"{base_url()}/Users/{uid}"} for uid, email in members
        ],
        "meta": {
            "resourceType": "Group",
            "created": _iso(group.created_at),
            "lastModified": _iso(group.updated_at),
            "location": f"{base_url()}/Groups/{group.id}",
            "version": _version(group.id, group.updated_at, len(members)),
        },
    }
    if group.external_id:
        resource["externalId"] = group.external_id
    return resource


async def _load_group(session: AsyncSession, ctx: ScimContext, group_id: str) -> ScimGroup:
    gid = _parse_uuid(group_id, "Grupo")
    group = await session.get(ScimGroup, gid)
    if group is None or group.org_id != ctx.org_id:
        raise ScimError(404, f"Grupo {group_id} no encontrado")
    return group


async def get_group(session: AsyncSession, ctx: ScimContext, group_id: str) -> dict[str, Any]:
    group = await _load_group(session, ctx, group_id)
    members = (await _group_members(session, [group.id]))[group.id]
    return group_resource(group, members)


async def list_groups(
    session: AsyncSession, ctx: ScimContext, *, filter_text: str | None, start_index: int, count: int
) -> tuple[int, list[dict[str, Any]]]:
    node = parse_filter(filter_text) if filter_text else None
    q = select(ScimGroup).where(ScimGroup.org_id == ctx.org_id).order_by(ScimGroup.created_at, ScimGroup.id)
    if isinstance(node, Compare) and node.op == "eq" and isinstance(node.value, str):
        attr = _strip_schema(node.attr).lower()
        if attr == "displayname":
            q = q.where(func.lower(ScimGroup.display_name) == node.value.lower())
        elif attr == "externalid":
            q = q.where(ScimGroup.external_id == node.value)
    groups = list((await session.execute(q)).scalars())
    members = await _group_members(session, [g.id for g in groups])
    resources = [group_resource(g, members.get(g.id, [])) for g in groups]
    if node is not None:
        resources = [r for r in resources if matches(node, r)]
    total = len(resources)
    start = max(start_index, 1) - 1
    return total, resources[start : start + max(0, min(count, MAX_PAGE))]


async def _member_ids(session: AsyncSession, ctx: ScimContext, value: Any) -> set[uuid.UUID]:
    items = value if isinstance(value, list) else ([value] if value is not None else [])
    ids: set[uuid.UUID] = set()
    for item in items:
        raw = item.get("value") if isinstance(item, dict) else item
        try:
            ids.add(uuid.UUID(str(raw)))
        except ValueError as exc:
            raise ScimError(400, f"Miembro no válido: {raw}", "invalidValue") from exc
    if ids:
        known = {
            r[0]
            for r in await session.execute(
                select(OrgIdentity.user_id).where(
                    OrgIdentity.org_id == ctx.org_id, OrgIdentity.scim_managed.is_(True), OrgIdentity.user_id.in_(ids)
                )
            )
        }
        unknown = ids - known
        if unknown:
            raise ScimError(
                400, f"Usuarios no aprovisionados: {', '.join(sorted(str(u) for u in unknown))}", "invalidValue"
            )
    return ids


async def _set_members(
    session: AsyncSession, ctx: ScimContext, group: ScimGroup, wanted: set[uuid.UUID]
) -> set[uuid.UUID]:
    current = {
        r[0] for r in await session.execute(select(ScimGroupMember.user_id).where(ScimGroupMember.group_id == group.id))
    }
    to_add, to_remove = wanted - current, current - wanted
    if to_remove:
        await session.execute(
            delete(ScimGroupMember).where(ScimGroupMember.group_id == group.id, ScimGroupMember.user_id.in_(to_remove))
        )
    for uid in to_add:
        session.add(ScimGroupMember(group_id=group.id, user_id=uid, org_id=ctx.org_id))
    if to_add or to_remove:
        group.updated_at = datetime.now(UTC)
    await session.flush()
    return to_add | to_remove


async def _current_members(session: AsyncSession, group: ScimGroup) -> set[uuid.UUID]:
    return {
        r[0] for r in await session.execute(select(ScimGroupMember.user_id).where(ScimGroupMember.group_id == group.id))
    }


async def _resync(session: AsyncSession, ctx: ScimContext, user_ids: set[uuid.UUID]) -> None:
    for uid in sorted(user_ids, key=str):
        await sync_role(session, ctx, uid)


async def _ensure_unique_name(session: AsyncSession, ctx: ScimContext, name: str, exclude: uuid.UUID | None) -> None:
    q = select(ScimGroup.id).where(ScimGroup.org_id == ctx.org_id, func.lower(ScimGroup.display_name) == name.lower())
    if exclude is not None:
        q = q.where(ScimGroup.id != exclude)
    if (await session.execute(q)).first() is not None:
        raise ScimError(409, "Ya existe un grupo con ese displayName", "uniqueness")


async def create_group(session: AsyncSession, ctx: ScimContext, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(_get(payload, "displayName") or "").strip()
    if not name:
        raise ScimError(400, "displayName es obligatorio", "invalidValue")
    await _ensure_unique_name(session, ctx, name, None)
    external = _get(payload, "externalId")
    group = ScimGroup(org_id=ctx.org_id, display_name=name[:255], external_id=str(external) if external else None)
    session.add(group)
    await session.flush()
    changed = await _set_members(session, ctx, group, await _member_ids(session, ctx, _get(payload, "members")))
    await _resync(session, ctx, changed)
    await audit.record(
        session,
        action="scim.group_created",
        principal=ctx.principal,
        entity_type="scim_group",
        entity_id=group.id,
        diff={"display_name": group.display_name, "members": len(changed)},
    )
    return await get_group(session, ctx, str(group.id))


async def replace_group(
    session: AsyncSession, ctx: ScimContext, group_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    group = await _load_group(session, ctx, group_id)
    name = str(_get(payload, "displayName") or "").strip()
    if not name:
        raise ScimError(400, "displayName es obligatorio", "invalidValue")
    await _ensure_unique_name(session, ctx, name, group.id)
    renamed = name != group.display_name
    group.display_name = name[:255]
    external = _get(payload, "externalId")
    group.external_id = str(external) if external else None
    group.updated_at = datetime.now(UTC)
    before = await _current_members(session, group)
    changed = await _set_members(session, ctx, group, await _member_ids(session, ctx, _get(payload, "members")))
    await _resync(session, ctx, (before | await _current_members(session, group)) if renamed else changed)
    await audit.record(
        session,
        action="scim.group_replaced",
        principal=ctx.principal,
        entity_type="scim_group",
        entity_id=group.id,
        diff={"display_name": group.display_name},
    )
    return await get_group(session, ctx, group_id)


_MEMBER_FILTER_RE = re.compile(r'^members\[\s*value\s+eq\s+"([^"]+)"\s*\]$', re.IGNORECASE)


async def patch_group(session: AsyncSession, ctx: ScimContext, group_id: str, payload: dict[str, Any]) -> None:
    group = await _load_group(session, ctx, group_id)
    affected: set[uuid.UUID] = set()
    renamed = False
    for op in _operations(payload):
        path = str(op["path"]).strip() if op["path"] is not None else None
        value = op["value"]
        lowered = (path or "").lower()
        if path is None:
            if not isinstance(value, dict):
                raise ScimError(400, "La operación sin path requiere un objeto", "invalidValue")
            for key, sub in value.items():
                k = str(key).lower()
                if k == "displayname" and sub:
                    await _ensure_unique_name(session, ctx, str(sub), group.id)
                    renamed = renamed or str(sub) != group.display_name
                    group.display_name = str(sub)[:255]
                elif k == "externalid":
                    group.external_id = str(sub) if sub else None
                elif k == "members":
                    ids = await _member_ids(session, ctx, sub)
                    current = await _current_members(session, group)
                    wanted = ids if op["op"] == "replace" else current | ids
                    affected |= await _set_members(session, ctx, group, wanted)
            continue
        if lowered == "displayname":
            if op["op"] == "remove" or not value:
                raise ScimError(400, "displayName es obligatorio", "mutability")
            await _ensure_unique_name(session, ctx, str(value), group.id)
            renamed = renamed or str(value) != group.display_name
            group.display_name = str(value)[:255]
        elif lowered == "externalid":
            group.external_id = None if op["op"] == "remove" or not value else str(value)
        elif lowered == "members":
            current = await _current_members(session, group)
            ids = await _member_ids(session, ctx, value) if value is not None else set()
            if op["op"] == "add":
                wanted = current | ids
            elif op["op"] == "replace":
                wanted = ids
            else:
                wanted = current - ids if value is not None else set()
            affected |= await _set_members(session, ctx, group, wanted)
        elif match := _MEMBER_FILTER_RE.match(path):
            if op["op"] != "remove":
                raise ScimError(400, "Solo se admite remove sobre members[value eq ...]", "invalidPath")
            try:
                target = uuid.UUID(match.group(1))
            except ValueError as exc:
                raise ScimError(400, "Miembro no válido", "invalidValue") from exc
            current = await _current_members(session, group)
            affected |= await _set_members(session, ctx, group, current - {target})
        else:
            raise ScimError(400, f"Path no soportado: {path}", "invalidPath")
    group.updated_at = datetime.now(UTC)
    await session.flush()
    if renamed:
        affected |= await _current_members(session, group)
    await _resync(session, ctx, affected)
    await audit.record(
        session,
        action="scim.group_patched",
        principal=ctx.principal,
        entity_type="scim_group",
        entity_id=group.id,
        diff={"display_name": group.display_name, "affected_users": len(affected)},
    )


async def delete_group(session: AsyncSession, ctx: ScimContext, group_id: str) -> None:
    group = await _load_group(session, ctx, group_id)
    members = await _current_members(session, group)
    await session.delete(group)
    await session.flush()
    await _resync(session, ctx, members)
    await audit.record(
        session,
        action="scim.group_deleted",
        principal=ctx.principal,
        entity_type="scim_group",
        entity_id=group.id,
        diff={"display_name": group.display_name},
    )


# ============================================================================= discovery documents


def service_provider_config() -> dict[str, Any]:
    return {
        "schemas": [SCHEMA_SPC],
        "documentationUri": f"{get_settings().messer_web_url.rstrip('/')}/docs/scim",
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": MAX_PAGE},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "OAuth Bearer Token",
                "description": "Token SCIM creado en Ajustes → SSO y SCIM",
                "primary": True,
            }
        ],
        "meta": {"resourceType": "ServiceProviderConfig", "location": f"{base_url()}/ServiceProviderConfig"},
    }


def resource_types() -> list[dict[str, Any]]:
    return [
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "description": "Usuario de la organización",
            "schema": SCHEMA_USER,
            "schemaExtensions": [{"schema": SCHEMA_ENTERPRISE_USER, "required": False}],
            "meta": {"resourceType": "ResourceType", "location": f"{base_url()}/ResourceTypes/User"},
        },
        {
            "schemas": [SCHEMA_RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "description": "Grupo (se asigna a roles mediante el mapeo de grupos)",
            "schema": SCHEMA_GROUP,
            "meta": {"resourceType": "ResourceType", "location": f"{base_url()}/ResourceTypes/Group"},
        },
    ]


def _attr(
    name: str,
    type_: str = "string",
    *,
    multi: bool = False,
    required: bool = False,
    mutability: str = "readWrite",
    uniqueness: str = "none",
    sub: list[dict[str, Any]] | None = None,
    case_exact: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "type": type_,
        "multiValued": multi,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": "default",
        "uniqueness": uniqueness,
    }
    if sub:
        out["subAttributes"] = sub
    return out


def schemas() -> list[dict[str, Any]]:
    user_attrs = [
        _attr("userName", required=True, uniqueness="server"),
        _attr("externalId", case_exact=True),
        _attr("name", "complex", sub=[_attr("givenName"), _attr("familyName"), _attr("formatted")]),
        _attr("displayName"),
        _attr("emails", "complex", multi=True, sub=[_attr("value"), _attr("type"), _attr("primary", "boolean")]),
        _attr("active", "boolean"),
        _attr("title"),
        _attr("groups", "complex", multi=True, mutability="readOnly", sub=[_attr("value"), _attr("display")]),
    ]
    group_attrs = [
        _attr("displayName", required=True, uniqueness="server"),
        _attr("externalId", case_exact=True),
        _attr("members", "complex", multi=True, sub=[_attr("value"), _attr("display")]),
    ]
    enterprise_attrs = [_attr("employeeNumber"), _attr("department"), _attr("organization"), _attr("costCenter")]
    return [
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_USER,
            "name": "User",
            "description": "Usuario",
            "attributes": user_attrs,
            "meta": {"resourceType": "Schema", "location": f"{base_url()}/Schemas/{SCHEMA_USER}"},
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_GROUP,
            "name": "Group",
            "description": "Grupo",
            "attributes": group_attrs,
            "meta": {"resourceType": "Schema", "location": f"{base_url()}/Schemas/{SCHEMA_GROUP}"},
        },
        {
            "schemas": [SCHEMA_SCHEMA],
            "id": SCHEMA_ENTERPRISE_USER,
            "name": "EnterpriseUser",
            "description": "Extensión empresarial",
            "attributes": enterprise_attrs,
            "meta": {"resourceType": "Schema", "location": f"{base_url()}/Schemas/{SCHEMA_ENTERPRISE_USER}"},
        },
    ]


def list_response(total: int, start_index: int, resources: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schemas": [SCHEMA_LIST],
        "totalResults": total,
        "startIndex": max(start_index, 1),
        "itemsPerPage": len(resources),
        "Resources": resources,
    }
