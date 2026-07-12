"""Small injectable authentication boundary for authenticated web routes.

Supabase access tokens from projects using the legacy shared JWT secret are
HS256 JWTs.  Verification lives here rather than in the geometry or storage
layers so tests and non-web callers can provide a tiny authenticator double.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import time
from typing import Any, Protocol


_JWT_PART_RE = re.compile(r"[A-Za-z0-9_-]+")
_USER_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class AuthenticationError(ValueError):
    """A missing, malformed, expired, or unverifiable user credential."""


class Authenticator(Protocol):
    """Resolve one verified bearer token to its private user id."""

    def authenticate(self, token: str) -> str:
        ...


class RejectingAuthenticator:
    """Default when authenticated routes have no configured JWT verifier."""

    def __init__(self, detail: str = "Bearer authentication is not configured") -> None:
        self.detail = detail

    def authenticate(self, token: str) -> str:
        del token
        raise AuthenticationError(self.detail)


class SupabaseJWTAuthenticator:
    """Verify Supabase HS256 access tokens with the project's JWT secret."""

    def __init__(
        self,
        secret: str,
        *,
        issuer: str | None = None,
        audience: str | None = "authenticated",
        leeway_seconds: float = 30.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(secret, str) or not secret:
            raise ValueError("SUPABASE_JWT_SECRET must be a non-empty string")
        if issuer is not None and (not isinstance(issuer, str) or not issuer.strip()):
            raise ValueError("issuer must be a non-empty string or None")
        if audience is not None and (
            not isinstance(audience, str) or not audience.strip()
        ):
            raise ValueError("audience must be a non-empty string or None")
        if not math.isfinite(leeway_seconds) or leeway_seconds < 0.0:
            raise ValueError("leeway_seconds must be finite and non-negative")
        self._secret = secret.encode("utf-8")
        self._issuer = issuer.strip().rstrip("/") if issuer is not None else None
        self._audience = audience.strip() if audience is not None else None
        self._leeway = float(leeway_seconds)
        self._clock = clock

    def authenticate(self, token: str) -> str:
        if not isinstance(token, str) or not token or len(token) > 16_384:
            raise AuthenticationError("Invalid bearer token")
        parts = token.split(".")
        if len(parts) != 3 or any(_JWT_PART_RE.fullmatch(part) is None for part in parts):
            raise AuthenticationError("Invalid bearer token")
        encoded_header, encoded_payload, encoded_signature = parts
        header = _jwt_json(encoded_header, "header")
        payload = _jwt_json(encoded_payload, "payload")
        if header.get("alg") != "HS256":
            raise AuthenticationError("Unsupported JWT signing algorithm")
        supplied_signature = _base64url_decode(encoded_signature, "signature")
        expected_signature = hmac.new(
            self._secret,
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise AuthenticationError("Invalid bearer token signature")

        now = float(self._clock())
        if not math.isfinite(now):  # pragma: no cover - injected clock guard
            raise RuntimeError("authentication clock returned a non-finite value")
        expires = _numeric_claim(payload, "exp", required=True)
        assert expires is not None
        if expires <= now - self._leeway:
            raise AuthenticationError("Bearer token has expired")
        not_before = _numeric_claim(payload, "nbf", required=False)
        if not_before is not None and not_before > now + self._leeway:
            raise AuthenticationError("Bearer token is not active yet")
        issued_at = _numeric_claim(payload, "iat", required=False)
        if issued_at is not None and issued_at > now + self._leeway:
            raise AuthenticationError("Bearer token was issued in the future")

        if self._issuer is not None:
            issuer = payload.get("iss")
            if not isinstance(issuer, str) or issuer.rstrip("/") != self._issuer:
                raise AuthenticationError("Bearer token issuer is not trusted")
        if self._audience is not None and not _audience_contains(
            payload.get("aud"), self._audience
        ):
            raise AuthenticationError("Bearer token audience is not accepted")
        if payload.get("role") != "authenticated":
            raise AuthenticationError("Bearer token role is not accepted")
        return normalize_user_id(payload.get("sub"))


def authenticator_from_env() -> Authenticator:
    """Build the process authenticator from Supabase environment variables."""

    raw_secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    raw_supabase_url = os.environ.get("SUPABASE_URL", "")
    if not raw_secret and not raw_supabase_url:
        return RejectingAuthenticator()
    secret = raw_secret.strip()
    supabase_url = raw_supabase_url.strip().rstrip("/")
    if not secret or not supabase_url:
        raise ValueError(
            "Supabase JWT auth requires both SUPABASE_URL and SUPABASE_JWT_SECRET"
        )
    issuer = f"{supabase_url}/auth/v1"
    raw_audience = os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated").strip()
    return SupabaseJWTAuthenticator(
        secret,
        issuer=issuer,
        audience=raw_audience or None,
    )


def normalize_user_id(value: Any) -> str:
    """Validate a JWT subject or explicitly enabled development user id."""

    if not isinstance(value, str):
        raise AuthenticationError("Bearer token has no usable subject")
    user_id = value.strip()
    if _USER_ID_RE.fullmatch(user_id) is None:
        raise AuthenticationError("Bearer token has no usable subject")
    return user_id


def _jwt_json(segment: str, name: str) -> Mapping[str, Any]:
    raw = _base64url_decode(segment, name)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthenticationError(f"Invalid JWT {name}") from exc
    if not isinstance(value, Mapping):
        raise AuthenticationError(f"Invalid JWT {name}")
    return value


def _base64url_decode(segment: str, name: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.b64decode(
            segment + padding,
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise AuthenticationError(f"Invalid JWT {name}") from exc


def _numeric_claim(
    payload: Mapping[str, Any],
    name: str,
    *,
    required: bool,
) -> float | None:
    value = payload.get(name)
    if value is None:
        if required:
            raise AuthenticationError(f"Bearer token is missing {name}")
        return None
    if isinstance(value, bool):
        raise AuthenticationError(f"Bearer token has invalid {name}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise AuthenticationError(f"Bearer token has invalid {name}") from exc
    if not math.isfinite(result):
        raise AuthenticationError(f"Bearer token has invalid {name}")
    return result


def _audience_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return any(isinstance(item, str) and item == expected for item in value)
    return False


__all__ = [
    "AuthenticationError",
    "Authenticator",
    "RejectingAuthenticator",
    "SupabaseJWTAuthenticator",
    "authenticator_from_env",
    "normalize_user_id",
]
