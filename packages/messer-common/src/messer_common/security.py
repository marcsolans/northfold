"""Encryption at rest, hashing, password storage, tokens and JWTs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .settings import get_settings

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


class DecryptionError(Exception):
    pass


def _fernet() -> Fernet:
    return Fernet(get_settings().secrets_key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("Unable to decrypt value with MESSER_SECRETS_KEY") from exc


def encrypt_json(value: dict[str, Any]) -> str:
    return encrypt(json.dumps(value, separators=(",", ":"), sort_keys=True))


def decrypt_json(token: str | None) -> dict[str, Any]:
    if not token:
        return {}
    return json.loads(decrypt(token))


def hash_token(token: str) -> str:
    """Keyed hash for API keys, refresh tokens and one-time tokens (never stored in clear)."""
    key = get_settings().secrets_key
    return hmac.new(key, token.encode(), hashlib.sha256).hexdigest()


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_api_key() -> tuple[str, str]:
    """Return (full_key, prefix). The full key is shown once and stored only as a hash."""
    body = secrets.token_urlsafe(32)
    key = f"msr_{body}"
    return key, key[:12]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# ----------------------------------------------------------------------------- JWT


def issue_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    session_id: uuid.UUID | None = None,
    impersonated_by: uuid.UUID | None = None,
    mfa_verified: bool = False,
    ttl_s: int | None = None,
) -> str:
    """Session JWT with Supabase-compatible claims (sub, email, aud, role)."""
    settings = get_settings()
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "aud": "authenticated",
        "role": "authenticated",
        "iss": "messer",
        "iat": now,
        "exp": now + (ttl_s or settings.messer_access_token_ttl_s),
        "aal": "aal2" if mfa_verified else "aal1",
    }
    if session_id:
        payload["sid"] = str(session_id)
    if impersonated_by:
        payload["imp"] = str(impersonated_by)
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class TokenError(Exception):
    pass


def decode_access_token(token: str) -> dict[str, Any]:
    """Verify a Messer-issued or Supabase-issued access token."""
    settings = get_settings()
    candidates: list[str] = [settings.jwt_secret]
    if settings.supabase_jwt_secret:
        candidates.append(settings.supabase_jwt_secret)
    last_error: Exception | None = None
    for secret in candidates:
        try:
            return jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
        except jwt.PyJWTError as exc:
            last_error = exc
    raise TokenError(str(last_error) if last_error else "invalid token")


def sign_payload(payload: dict[str, Any], ttl_s: int) -> str:
    """Compact signed token for links that do not need DB state (e.g. unsubscribe)."""
    settings = get_settings()
    body = dict(payload)
    body["exp"] = int(time.time()) + ttl_s
    return jwt.encode(body, settings.jwt_secret, algorithm="HS256")


def verify_signed_payload(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc


def hmac_sha256_hex(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
