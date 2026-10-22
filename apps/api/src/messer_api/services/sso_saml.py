"""SAML 2.0 service provider for enterprise SSO.

* SP-initiated login: ``AuthnRequest`` over the HTTP-Redirect binding (DEFLATE + base64), ``RelayState``
  carries a single-use state token.
* ACS over HTTP-POST: the XML is parsed with a hardened lxml parser (no DTDs, no entities, no network), the
  ``Response`` and/or ``Assertion`` signature is verified with the IdP certificate(s) using signxml (pure Python),
  and **only the signed subtree returned by the verifier is trusted** (prevents signature wrapping).
* Strict checks: issuer, exactly one assertion, audience, recipient, destination, ``InResponseTo``,
  ``NotBefore``/``NotOnOrAfter`` with a bounded clock skew, bearer confirmation. Replay protection (assertion
  ``ID``) is done by the caller with the returned ``assertion_id``/``expires_at``.
* Encrypted assertions are not supported (TLS protects the browser hop); IdPs must send signed, unencrypted
  assertions.
"""

from __future__ import annotations

import base64
import binascii
import textwrap
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]  # compiled module, no stubs
from pydantic import BaseModel, Field
from signxml import SignatureConfiguration, XMLVerifier
from signxml.exceptions import InvalidInput, SignXMLException

from messer_common.security import random_token
from messer_common.settings import get_settings

from .sso_oidc import SsoIdentity, SsoProtocolError

NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml": "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
    "md": "urn:oasis:names:tc:SAML:2.0:metadata",
}
SAML = "{" + NS["saml"] + "}"
SAMLP = "{" + NS["samlp"] + "}"
DS = "{" + NS["ds"] + "}"
MD = "{" + NS["md"] + "}"

NAMEID_EMAIL = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
NAMEID_UNSPECIFIED = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
NAMEID_PERSISTENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:persistent"
BINDING_POST = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
BINDING_REDIRECT = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
STATUS_SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
CM_BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_CLOCK_SKEW_S = 300


class SamlConfig(BaseModel):
    """Stored (encrypted) configuration of a SAML connection."""

    preset: Literal["generic", "entra", "google", "okta"] = "generic"
    idp_entity_id: str = Field(min_length=1, max_length=500)
    idp_sso_url: str = Field(min_length=8, max_length=1000)
    idp_certificates: list[str] = Field(min_length=1, max_length=4)
    sp_entity_id: str | None = Field(default=None, max_length=500)
    name_id_format: str = NAMEID_EMAIL
    email_attribute: str | None = None  # None → NameID
    first_name_attribute: str | None = None
    last_name_attribute: str | None = None
    display_name_attribute: str | None = None
    groups_attribute: str | None = None
    allow_idp_initiated: bool = False
    require_assertion_signature: bool = False
    clock_skew_s: int = Field(default=120, ge=0, le=MAX_CLOCK_SKEW_S)
    jit_provisioning: bool = True


@dataclass(slots=True)
class SamlLogin:
    identity: SsoIdentity
    assertion_id: str
    expires_at: datetime
    in_response_to: str | None
    attributes: dict[str, list[str]]


# ----------------------------------------------------------------------------- certificates & metadata


def normalize_certificate(value: str) -> str:
    """Accept a PEM certificate or the bare base64 DER found in IdP metadata; return validated PEM."""
    text = value.strip()
    if "BEGIN CERTIFICATE" in text:
        pem = text if text.endswith("\n") else text + "\n"
    else:
        body = "".join(text.split())
        try:
            base64.b64decode(body, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise SsoProtocolError("invalid_certificate", "El certificado del IdP no es válido") from exc
        pem = "-----BEGIN CERTIFICATE-----\n" + "\n".join(textwrap.wrap(body, 64)) + "\n-----END CERTIFICATE-----\n"
    try:
        x509.load_pem_x509_certificate(pem.encode())
    except ValueError as exc:
        raise SsoProtocolError("invalid_certificate", "El certificado del IdP no es válido") from exc
    return pem


def certificate_info(pem: str) -> dict[str, Any]:
    cert = x509.load_pem_x509_certificate(pem.encode())
    return {
        "subject": cert.subject.rfc4514_string(),
        "not_after": cert.not_valid_after_utc.isoformat(),
        "expired": cert.not_valid_after_utc < datetime.now(UTC),
        "fingerprint_sha256": cert.fingerprint(hashes.SHA256()).hex(":").upper(),
    }


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def _parse(data: bytes) -> etree._Element:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise SsoProtocolError("invalid_xml", "XML con DTD o entidades no permitido")
    try:
        return etree.fromstring(data, parser=_parser())
    except etree.XMLSyntaxError as exc:
        raise SsoProtocolError("invalid_xml", "XML SAML mal formado") from exc


def parse_idp_metadata(xml: str) -> dict[str, Any]:
    """Extract entityID, the SSO endpoint (HTTP-Redirect preferred) and signing certificates from IdP metadata."""
    root = _parse(xml.encode())
    descriptor = root if root.tag == f"{MD}EntityDescriptor" else root.find(f".//{MD}EntityDescriptor")
    if descriptor is None:
        raise SsoProtocolError("invalid_metadata", "No se encontró EntityDescriptor en los metadatos")
    idp = descriptor.find(f"{MD}IDPSSODescriptor")
    if idp is None:
        raise SsoProtocolError("invalid_metadata", "Los metadatos no describen un IdP (IDPSSODescriptor)")
    sso_url = None
    for binding in (BINDING_REDIRECT, BINDING_POST):
        el = idp.find(f"{MD}SingleSignOnService[@Binding='{binding}']")
        if el is not None and el.get("Location"):
            sso_url = el.get("Location")
            break
    certs: list[str] = []
    for kd in idp.findall(f"{MD}KeyDescriptor"):
        if kd.get("use") not in (None, "signing"):
            continue
        for cert_el in kd.findall(f".//{DS}X509Certificate"):
            if cert_el.text and cert_el.text.strip():
                certs.append(normalize_certificate(cert_el.text))
    entity_id = descriptor.get("entityID")
    if not entity_id or not sso_url or not certs:
        raise SsoProtocolError("invalid_metadata", "Faltan entityID, SingleSignOnService o certificado")
    return {"idp_entity_id": entity_id, "idp_sso_url": sso_url, "idp_certificates": list(dict.fromkeys(certs))}


# ----------------------------------------------------------------------------- SP side


def acs_url(connection_id: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/sso/saml/{connection_id}/acs"


def metadata_url(connection_id: str) -> str:
    return f"{get_settings().messer_web_url.rstrip('/')}/api/v1/sso/saml/{connection_id}/metadata"


def sp_entity_id(connection_id: str, config: SamlConfig) -> str:
    return config.sp_entity_id or metadata_url(connection_id)


def sp_metadata_xml(connection_id: str, config: SamlConfig) -> bytes:
    root = etree.Element(f"{MD}EntityDescriptor", nsmap={"md": NS["md"]}, entityID=sp_entity_id(connection_id, config))
    sp = etree.SubElement(
        root,
        f"{MD}SPSSODescriptor",
        AuthnRequestsSigned="false",
        WantAssertionsSigned="true" if config.require_assertion_signature else "false",
        protocolSupportEnumeration=NS["samlp"],
    )
    fmt = etree.SubElement(sp, f"{MD}NameIDFormat")
    fmt.text = config.name_id_format
    etree.SubElement(
        sp,
        f"{MD}AssertionConsumerService",
        Binding=BINDING_POST,
        Location=acs_url(connection_id),
        index="0",
        isDefault="true",
    )
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _instant(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_request_id() -> str:
    # NCName: must not start with a digit.
    return "_" + random_token(24).replace("-", "a").replace("_", "b")


def authn_request_url(
    connection_id: str, config: SamlConfig, *, request_id: str, relay_state: str, login_hint: str | None = None
) -> str:
    root = etree.Element(
        f"{SAMLP}AuthnRequest",
        nsmap={"samlp": NS["samlp"], "saml": NS["saml"]},
        ID=request_id,
        Version="2.0",
        IssueInstant=_instant(datetime.now(UTC)),
        Destination=config.idp_sso_url,
        AssertionConsumerServiceURL=acs_url(connection_id),
        ProtocolBinding=BINDING_POST,
    )
    issuer = etree.SubElement(root, f"{SAML}Issuer")
    issuer.text = sp_entity_id(connection_id, config)
    etree.SubElement(root, f"{SAMLP}NameIDPolicy", Format=config.name_id_format, AllowCreate="true")
    xml = etree.tostring(root)
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    deflated = compressor.compress(xml) + compressor.flush()
    params = {"SAMLRequest": base64.b64encode(deflated).decode(), "RelayState": relay_state}
    if login_hint:
        params["login_hint"] = login_hint
    separator = "&" if "?" in config.idp_sso_url else "?"
    return f"{config.idp_sso_url}{separator}{urlencode(params)}"


# ----------------------------------------------------------------------------- ACS


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    if "." in raw:  # trim fractional seconds beyond microseconds (ADFS/Entra emit 7 digits)
        head, _, rest = raw.partition(".")
        digits = "".join(ch for ch in rest if ch.isdigit())
        tz = rest[len(digits) :]
        raw = f"{head}.{digits[:6]}{tz}"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SsoProtocolError("invalid_time", f"Fecha SAML no válida: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _text(el: etree._Element | None) -> str | None:
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _verify(root: etree._Element, certificates: list[str], location: str) -> etree._Element:
    errors: list[str] = []
    config = SignatureConfiguration(location=location, expect_references=1)
    for pem in certificates:
        try:
            result = XMLVerifier().verify(root, x509_cert=pem, parser=_parser(), expect_config=config)
        except (SignXMLException, InvalidInput, ValueError) as exc:
            errors.append(str(exc))
            continue
        if isinstance(result, list):  # expect_references=1 never returns a list; stay defensive
            raise SsoProtocolError("invalid_signature", "Firma SAML con varias referencias")
        signed = result.signed_xml
        if not isinstance(signed, etree._Element):
            raise SsoProtocolError("invalid_signature", "La firma SAML no cubre un elemento XML")
        return signed
    raise SsoProtocolError("invalid_signature", "La firma SAML no es válida para el certificado del IdP")


def process_response(
    saml_response: str,
    config: SamlConfig,
    *,
    connection_id: str,
    expected_request_id: str | None,
    now: datetime | None = None,
) -> SamlLogin:
    """Validate a base64 SAMLResponse posted to the ACS and return the asserted identity."""
    now = now or datetime.now(UTC)
    skew = timedelta(seconds=config.clock_skew_s)
    try:
        data = base64.b64decode(saml_response.strip(), validate=False)
    except (binascii.Error, ValueError) as exc:
        raise SsoProtocolError("invalid_response", "SAMLResponse no está en base64") from exc
    if not data or len(data) > MAX_RESPONSE_BYTES:
        raise SsoProtocolError("invalid_response", "SAMLResponse vacía o demasiado grande")
    root = _parse(data)
    if root.tag != f"{SAMLP}Response":
        raise SsoProtocolError("invalid_response", "El mensaje SAML no es un Response")

    status = root.find(f"{SAMLP}Status/{SAMLP}StatusCode")
    status_value = status.get("Value") if status is not None else None
    if status_value != STATUS_SUCCESS:
        detail = _text(root.find(f"{SAMLP}Status/{SAMLP}StatusMessage")) or (status_value or "sin estado")
        raise SsoProtocolError("idp_denied", f"El proveedor de identidad rechazó el acceso: {detail}")
    if root.find(f".//{SAML}EncryptedAssertion") is not None:
        raise SsoProtocolError(
            "encrypted_assertion", "Las aserciones cifradas no están soportadas: desactiva el cifrado en el IdP"
        )
    assertions = root.findall(f".//{SAML}Assertion")
    if len(assertions) != 1:
        raise SsoProtocolError("invalid_response", "El Response debe contener exactamente una aserción")
    assertion_id = assertions[0].get("ID")
    if not assertion_id:
        raise SsoProtocolError("invalid_response", "La aserción no tiene ID")

    acs = acs_url(connection_id)
    entity_id = sp_entity_id(connection_id, config)

    # ---- signatures: trust only what the verifier returns
    signed_assertion: etree._Element | None = None
    response_signed = root.find(f"{DS}Signature") is not None
    if response_signed:
        signed_response = _verify(root, config.idp_certificates, "./")
        if signed_response.tag != f"{SAMLP}Response" or signed_response.get("ID") != root.get("ID"):
            raise SsoProtocolError("invalid_signature", "La firma no cubre el Response")
        inner = signed_response.findall(f"{SAML}Assertion")
        if len(inner) != 1 or inner[0].get("ID") != assertion_id:
            raise SsoProtocolError("invalid_signature", "La aserción firmada no coincide")
        signed_assertion = inner[0]
    if assertions[0].find(f"{DS}Signature") is not None:
        candidate = _verify(root, config.idp_certificates, f"./{SAML}Assertion/")
        if candidate.tag != f"{SAML}Assertion" or candidate.get("ID") != assertion_id:
            raise SsoProtocolError("invalid_signature", "La firma no cubre la aserción")
        signed_assertion = candidate
    elif config.require_assertion_signature:
        raise SsoProtocolError("unsigned_assertion", "La aserción SAML no está firmada")
    if signed_assertion is None:
        raise SsoProtocolError("unsigned_assertion", "El Response SAML no está firmado")

    # ---- response-level checks (destination, correlation)
    destination = root.get("Destination")
    if destination is not None and destination != acs:
        raise SsoProtocolError("destination_mismatch", "El Response va dirigido a otra URL")
    response_issuer = _text(root.find(f"{SAML}Issuer"))
    if response_issuer is not None and response_issuer != config.idp_entity_id:
        raise SsoProtocolError("issuer_mismatch", "El emisor del Response no es el IdP configurado")
    in_response_to = root.get("InResponseTo")
    _check_correlation(in_response_to, expected_request_id, config)

    # ---- assertion checks (signed subtree only)
    a = signed_assertion
    if _text(a.find(f"{SAML}Issuer")) != config.idp_entity_id:
        raise SsoProtocolError("issuer_mismatch", "El emisor de la aserción no es el IdP configurado")

    conditions = a.find(f"{SAML}Conditions")
    if conditions is None:
        raise SsoProtocolError("missing_conditions", "La aserción no tiene Conditions")
    not_before = _parse_time(conditions.get("NotBefore"))
    not_on_or_after = _parse_time(conditions.get("NotOnOrAfter"))
    if not_before is not None and now + skew < not_before:
        raise SsoProtocolError("assertion_not_yet_valid", "La aserción todavía no es válida")
    if not_on_or_after is None or now - skew >= not_on_or_after:
        raise SsoProtocolError("assertion_expired", "La aserción ha caducado")
    restrictions = conditions.findall(f"{SAML}AudienceRestriction")
    if not restrictions:
        raise SsoProtocolError("audience_mismatch", "La aserción no restringe la audiencia")
    for restriction in restrictions:
        audiences = [_text(el) for el in restriction.findall(f"{SAML}Audience")]
        if entity_id not in audiences:
            raise SsoProtocolError("audience_mismatch", "La aserción no está emitida para este proveedor de servicio")

    subject = a.find(f"{SAML}Subject")
    name_id_el = subject.find(f"{SAML}NameID") if subject is not None else None
    name_id = _text(name_id_el)
    if subject is None or not name_id:
        raise SsoProtocolError("missing_subject", "La aserción no identifica al usuario")
    confirmed_until: datetime | None = None
    for sc in subject.findall(f"{SAML}SubjectConfirmation"):
        if sc.get("Method") != CM_BEARER:
            continue
        scd = sc.find(f"{SAML}SubjectConfirmationData")
        if scd is None:
            continue
        if scd.get("Recipient") != acs:
            continue
        until = _parse_time(scd.get("NotOnOrAfter"))
        if until is None or now - skew >= until:
            continue
        scd_not_before = _parse_time(scd.get("NotBefore"))
        if scd_not_before is not None and now + skew < scd_not_before:
            continue
        try:
            _check_correlation(scd.get("InResponseTo"), expected_request_id, config)
        except SsoProtocolError:
            continue
        confirmed_until = until
        break
    if confirmed_until is None:
        raise SsoProtocolError(
            "subject_confirmation_failed", "Ninguna confirmación bearer válida (destinatario, caducidad o petición)"
        )

    authn = a.find(f"{SAML}AuthnStatement")
    if authn is None:
        raise SsoProtocolError("missing_authn_statement", "La aserción no contiene AuthnStatement")
    session_until = _parse_time(authn.get("SessionNotOnOrAfter"))
    if session_until is not None and now - skew >= session_until:
        raise SsoProtocolError("session_expired", "La sesión del IdP ha caducado")
    context_ref = _text(authn.find(f"{SAML}AuthnContext/{SAML}AuthnContextClassRef")) or ""

    attributes: dict[str, list[str]] = {}
    for attr in a.findall(f"{SAML}AttributeStatement/{SAML}Attribute"):
        values = [v for v in (_text(el) for el in attr.findall(f"{SAML}AttributeValue")) if v is not None]
        for key in (attr.get("Name"), attr.get("FriendlyName")):
            if key:
                attributes.setdefault(key, []).extend(values)

    def first(name: str | None) -> str | None:
        if not name:
            return None
        values = attributes.get(name) or []
        return values[0] if values else None

    email = first(config.email_attribute) if config.email_attribute else None
    if not email and "@" in name_id:
        email = name_id
    if not email or "@" not in email:
        raise SsoProtocolError("missing_email", "La aserción no contiene un email")
    given = first(config.first_name_attribute)
    family = first(config.last_name_attribute)
    display = first(config.display_name_attribute) or " ".join(p for p in (given, family) if p) or None
    groups = list(dict.fromkeys(attributes.get(config.groups_attribute or "", []))) if config.groups_attribute else []
    expires = min(t for t in (confirmed_until, not_on_or_after) if t is not None)
    identity = SsoIdentity(
        subject=name_id,
        email=email.strip().lower(),
        name=display,
        given_name=given,
        family_name=family,
        groups=groups,
        mfa="multifactor" in context_ref.lower() or "mfa" in context_ref.lower(),
        attributes={
            "name_id_format": name_id_el.get("Format") if name_id_el is not None else None,
            "authn_context": context_ref,
        },
    )
    return SamlLogin(
        identity=identity,
        assertion_id=assertion_id,
        expires_at=expires,
        in_response_to=in_response_to,
        attributes=attributes,
    )


def _check_correlation(in_response_to: str | None, expected: str | None, config: SamlConfig) -> None:
    if expected is not None:
        if in_response_to != expected:
            raise SsoProtocolError("in_response_to_mismatch", "El Response no corresponde a la petición de inicio")
        return
    if not config.allow_idp_initiated:
        raise SsoProtocolError("idp_initiated_disabled", "El inicio desde el IdP no está permitido en esta conexión")
    if in_response_to is not None:
        raise SsoProtocolError("in_response_to_mismatch", "Respuesta a una petición desconocida")
