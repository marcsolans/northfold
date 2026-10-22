"""Enterprise SSO over SAML 2.0: a self-signed IdP certificate and signed assertions generated in the test."""

from __future__ import annotations

import base64
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from enterprise_support import app_client, login, set_plan, verify_domain
from lxml import etree  # pyright: ignore[reportAttributeAccessIssue]
from signxml import XMLSigner
from sqlalchemy import select

from messer_api.services.sso_oidc import SsoProtocolError
from messer_api.services.sso_saml import SamlConfig, acs_url, metadata_url, parse_idp_metadata, process_response
from messer_common.db import system_session
from messer_common.db.models import Membership, User

IDP_ENTITY = "https://idp.acme-sso.eu/saml/metadata"
IDP_SSO = "https://idp.acme-sso.eu/saml/sso"
NS_SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
NS_SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
EXC_C14N = "http://www.w3.org/2001/10/xml-exc-c14n#"


def make_identity(cn: str = "idp.acme-sso.eu") -> tuple[bytes, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


IDP_KEY, IDP_CERT = make_identity()


def _t(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_response(
    *,
    connection_id: str,
    email: str,
    groups: list[str],
    in_response_to: str | None,
    audience: str | None = None,
    recipient: str | None = None,
    issuer: str = IDP_ENTITY,
    lifetime: timedelta = timedelta(minutes=5),
    sign: str = "assertion",
    key: bytes = IDP_KEY,
    cert: str = IDP_CERT,
    assertion_id: str | None = None,
) -> etree._Element:
    now = datetime.now(UTC)
    acs = recipient or acs_url(connection_id)
    aud = audience or metadata_url(connection_id)
    aid = assertion_id or f"_a{uuid.uuid4().hex}"
    irt = f' InResponseTo="{in_response_to}"' if in_response_to else ""
    attrs = "".join(f"<saml:AttributeValue>{g}</saml:AttributeValue>" for g in groups)
    placeholder = (
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"/>' if sign == "assertion" else ""
    )
    assertion_xml = f"""<saml:Assertion xmlns:saml="{NS_SAML}" ID="{aid}" Version="2.0" IssueInstant="{_t(now)}">
  <saml:Issuer>{issuer}</saml:Issuer>{placeholder}
  <saml:Subject>
    <saml:NameID Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress">{email}</saml:NameID>
    <saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">
      <saml:SubjectConfirmationData NotOnOrAfter="{_t(now + lifetime)}" Recipient="{acs}"{irt}/>
    </saml:SubjectConfirmation>
  </saml:Subject>
  <saml:Conditions NotBefore="{_t(now - timedelta(minutes=1))}" NotOnOrAfter="{_t(now + lifetime)}">
    <saml:AudienceRestriction><saml:Audience>{aud}</saml:Audience></saml:AudienceRestriction>
  </saml:Conditions>
  <saml:AuthnStatement AuthnInstant="{_t(now)}" SessionIndex="{aid}">
    <saml:AuthnContext><saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport</saml:AuthnContextClassRef></saml:AuthnContext>
  </saml:AuthnStatement>
  <saml:AttributeStatement>
    <saml:Attribute Name="email"><saml:AttributeValue>{email}</saml:AttributeValue></saml:Attribute>
    <saml:Attribute Name="firstName"><saml:AttributeValue>Lucía</saml:AttributeValue></saml:Attribute>
    <saml:Attribute Name="lastName"><saml:AttributeValue>García</saml:AttributeValue></saml:Attribute>
    <saml:Attribute Name="groups">{attrs}</saml:Attribute>
  </saml:AttributeStatement>
</saml:Assertion>"""
    signer = XMLSigner(signature_algorithm="rsa-sha256", digest_algorithm="sha256", c14n_algorithm=EXC_C14N)
    assertion = etree.fromstring(assertion_xml.encode())
    if sign == "assertion":
        assertion = signer.sign(assertion, key=key, cert=cert)
    response_placeholder = (
        '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#" Id="placeholder"/>' if sign == "response" else ""
    )
    response = etree.fromstring(
        f"""<samlp:Response xmlns:samlp="{NS_SAMLP}" xmlns:saml="{NS_SAML}" ID="_r{uuid.uuid4().hex}" Version="2.0"
  IssueInstant="{_t(now)}" Destination="{acs}"{irt}><saml:Issuer>{issuer}</saml:Issuer>{response_placeholder}
  <samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>
</samlp:Response>""".encode()
    )
    response.append(assertion)
    if sign == "response":
        response = signer.sign(response, key=key, cert=cert)
    return response


def encode(el: etree._Element) -> str:
    return base64.b64encode(etree.tostring(el)).decode()


def config(connection_id: str, **overrides: Any) -> SamlConfig:
    return SamlConfig.model_validate(
        {
            "idp_entity_id": IDP_ENTITY,
            "idp_sso_url": IDP_SSO,
            "idp_certificates": [IDP_CERT],
            "email_attribute": "email",
            "first_name_attribute": "firstName",
            "last_name_attribute": "lastName",
            "groups_attribute": "groups",
            **overrides,
        }
    )


# ----------------------------------------------------------------------------- protocol unit tests


def test_valid_assertion_signed_on_assertion_or_response() -> None:
    cid = str(uuid.uuid4())
    for mode in ("assertion", "response"):
        el = build_response(
            connection_id=cid, email="Lu@acme-sso.eu", groups=["Ops"], in_response_to="_req1", sign=mode
        )
        login = process_response(encode(el), config(cid), connection_id=cid, expected_request_id="_req1")
        assert login.identity.email == "lu@acme-sso.eu"
        assert login.identity.groups == ["Ops"] and login.identity.name == "Lucía García"
        assert login.assertion_id.startswith("_a")


@pytest.mark.parametrize(
    ("kwargs", "expected_request", "code"),
    [
        ({"audience": "https://other-sp.example.com"}, "_req", "audience_mismatch"),
        ({"recipient": "https://evil.example.com/acs"}, "_req", "destination_mismatch"),
        ({"lifetime": timedelta(minutes=-10)}, "_req", "assertion_expired"),
        ({"issuer": "https://rogue-idp.example.com"}, "_req", "issuer_mismatch"),
        ({"in_response_to": "_other"}, "_req", "in_response_to_mismatch"),
        ({"in_response_to": None}, None, "idp_initiated_disabled"),
        ({"sign": "none"}, "_req", "unsigned_assertion"),
    ],
)
def test_strict_checks(kwargs: dict[str, Any], expected_request: str | None, code: str) -> None:
    cid = str(uuid.uuid4())
    params: dict[str, Any] = {"connection_id": cid, "email": "a@acme-sso.eu", "groups": [], "in_response_to": "_req"}
    params.update(kwargs)
    el = build_response(**params)
    with pytest.raises(SsoProtocolError) as err:
        process_response(encode(el), config(cid), connection_id=cid, expected_request_id=expected_request)
    assert err.value.code == code


def test_tampering_and_wrapping_are_rejected() -> None:
    cid = str(uuid.uuid4())
    # Signed by another key with its own embedded certificate.
    rogue_key, rogue_cert = make_identity("rogue")
    el = build_response(
        connection_id=cid, email="a@acme-sso.eu", groups=[], in_response_to="_r", key=rogue_key, cert=rogue_cert
    )
    with pytest.raises(SsoProtocolError) as err:
        process_response(encode(el), config(cid), connection_id=cid, expected_request_id="_r")
    assert err.value.code == "invalid_signature"

    # Modified after signing.
    el = build_response(connection_id=cid, email="a@acme-sso.eu", groups=["viewers"], in_response_to="_r")
    name_id = el.find(f".//{{{NS_SAML}}}NameID")
    assert name_id is not None
    name_id.text = "ceo@acme-sso.eu"
    with pytest.raises(SsoProtocolError) as err:
        process_response(encode(el), config(cid), connection_id=cid, expected_request_id="_r")
    assert err.value.code == "invalid_signature"

    # Signature wrapping: a forged unsigned assertion next to the genuine signed one.
    el = build_response(connection_id=cid, email="a@acme-sso.eu", groups=[], in_response_to="_r")
    forged = build_response(
        connection_id=cid, email="ceo@acme-sso.eu", groups=["admins"], in_response_to="_r", sign="none"
    )
    el.insert(2, forged.find(f"{{{NS_SAML}}}Assertion"))
    with pytest.raises(SsoProtocolError) as err:
        process_response(encode(el), config(cid), connection_id=cid, expected_request_id="_r")
    assert err.value.code == "invalid_response"

    # XML entities are refused before parsing.
    evil = (
        b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x "y">]><samlp:Response xmlns:samlp="' + NS_SAMLP.encode() + b'"/>'
    )
    with pytest.raises(SsoProtocolError) as err:
        process_response(base64.b64encode(evil).decode(), config(cid), connection_id=cid, expected_request_id="_r")
    assert err.value.code == "invalid_xml"


def test_idp_metadata_import() -> None:
    body = "".join(IDP_CERT.strip().splitlines()[1:-1])
    xml = f"""<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{IDP_ENTITY}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing"><ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:X509Data>
      <ds:X509Certificate>{body}</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" Location="{IDP_SSO}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""
    parsed = parse_idp_metadata(xml)
    assert parsed["idp_entity_id"] == IDP_ENTITY and parsed["idp_sso_url"] == IDP_SSO
    assert parsed["idp_certificates"][0].strip() == IDP_CERT.strip()


# ----------------------------------------------------------------------------- end to end


async def _setup(client: httpx.AsyncClient, make_org: Any, **cfg: Any) -> tuple[Any, dict[str, Any]]:
    org, owner = await make_org(name="Acme SAML")
    await set_plan(org.id, "business")
    await verify_domain(org.id, "acme-sso.eu")
    await login(client, owner.email)
    res = await client.post(
        "/api/v1/sso/connections",
        json={
            "type": "saml",
            "name": "Okta SAML",
            "domain": "acme-sso.eu",
            "default_role": "viewer",
            "config": {
                "preset": "okta",
                "idp_entity_id": IDP_ENTITY,
                "idp_sso_url": IDP_SSO,
                "idp_certificates": [IDP_CERT],
                **cfg,
            },
        },
    )
    assert res.status_code == 201, res.text
    conn = res.json()
    assert conn["config"]["certificates"][0]["expired"] is False
    res = await client.post(
        f"/api/v1/sso/connections/{conn['id']}/mappings", json={"external_group": "Builders", "role": "builder"}
    )
    assert res.status_code == 201
    return org, conn


async def test_saml_sp_initiated_login_end_to_end(client, make_org) -> None:  # type: ignore[no-untyped-def]
    org, conn = await _setup(client, make_org)
    cid = conn["id"]
    async with app_client() as browser:
        metadata = await browser.get(f"/api/v1/sso/saml/{cid}/metadata")
        assert metadata.status_code == 200 and metadata.headers["content-type"].startswith(
            "application/samlmetadata+xml"
        )
        md = etree.fromstring(metadata.content)
        assert md.get("entityID") == metadata_url(cid)
        acs = md.find(".//{urn:oasis:names:tc:SAML:2.0:metadata}AssertionConsumerService")
        assert acs is not None and acs.get("Location") == acs_url(cid)

        start = (await browser.post("/api/v1/sso/discover", json={"email": "lu@acme-sso.eu"})).json()["redirect_url"]
        res = await browser.get(start)
        assert res.status_code == 302 and res.headers["location"].startswith(IDP_SSO)
        query = {k: v[0] for k, v in parse_qs(urlsplit(res.headers["location"]).query).items()}
        request_xml = zlib.decompress(base64.b64decode(query["SAMLRequest"]), -15)
        authn = etree.fromstring(request_xml)
        assert authn.get("AssertionConsumerServiceURL") == acs_url(cid)
        request_id = authn.get("ID")

        el = build_response(connection_id=cid, email="lu@acme-sso.eu", groups=["Builders"], in_response_to=request_id)
        res = await browser.post(
            f"/api/v1/sso/saml/{cid}/acs", data={"SAMLResponse": encode(el), "RelayState": query["RelayState"]}
        )
        assert res.status_code == 303, res.text
        assert res.headers["location"] == "http://localhost:3000/app"
        me = (await browser.get("/api/v1/me")).json()
        assert me["email"] == "lu@acme-sso.eu" and me["active_org"]["role"] == "builder"

        # The same RelayState cannot be used twice.
        res = await browser.post(
            f"/api/v1/sso/saml/{cid}/acs", data={"SAMLResponse": encode(el), "RelayState": query["RelayState"]}
        )
        assert res.headers["location"].endswith("/sso/error?code=state_expired")

    async with system_session() as s:
        user = (await s.execute(select(User).where(User.email == "lu@acme-sso.eu"))).scalar_one()
        membership = (
            await s.execute(select(Membership).where(Membership.org_id == org.id, Membership.user_id == user.id))
        ).scalar_one()
    assert user.name == "Lucía García" and membership.source == "sso" and membership.role == "builder"


async def test_saml_idp_initiated_replay_is_blocked(client, make_org) -> None:  # type: ignore[no-untyped-def]
    _, conn = await _setup(client, make_org, allow_idp_initiated=True)
    cid = conn["id"]
    el = build_response(connection_id=cid, email="lu@acme-sso.eu", groups=[], in_response_to=None)
    async with app_client() as browser:
        first = await browser.post(f"/api/v1/sso/saml/{cid}/acs", data={"SAMLResponse": encode(el)})
        assert first.status_code == 303 and first.headers["location"] == "http://localhost:3000/app"
    async with app_client() as attacker:
        replay = await attacker.post(f"/api/v1/sso/saml/{cid}/acs", data={"SAMLResponse": encode(el)})
        assert replay.headers["location"].endswith("/sso/error?code=assertion_replayed")
        assert "messer_at" not in attacker.cookies
