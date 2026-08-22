from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any, Protocol

import httpx
import jwt
from jwt import PyJWK


class InvalidAccessToken(Exception):
    """Raised when a bearer token cannot establish a verified Supabase identity."""


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str


class JwtVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...


class HttpJwksLoader:
    def __init__(
        self,
        url: str,
        *,
        cache_seconds: float = 600,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = url
        self._cache_seconds = cache_seconds
        self._client = client
        self._cached_at = 0.0
        self._cached_value: dict[str, Any] | None = None
        self._lock = Lock()

    def __call__(self) -> dict[str, Any]:
        with self._lock:
            now = monotonic()
            if self._cached_value is not None and now - self._cached_at < self._cache_seconds:
                return self._cached_value

            if self._client is None:
                response = httpx.get(self._url, timeout=5)
            else:
                response = self._client.get(self._url, timeout=5)
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict) or not isinstance(value.get("keys"), list):
                raise ValueError("Invalid JWKS response")
            self._cached_value = value
            self._cached_at = now
            return value


class JwksJwtVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        load_jwks: Callable[[], dict[str, Any]],
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._load_jwks = load_jwks

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header["alg"]
            key_id = header["kid"]
            if algorithm not in {"ES256", "RS256"}:
                raise InvalidAccessToken

            signing_key = next(
                PyJWK.from_dict(key)
                for key in self._load_jwks()["keys"]
                if key.get("kid") == key_id and key.get("alg") == algorithm
            )
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iss", "sub", "email", "role"]},
            )
            subject = claims["sub"]
            email = claims["email"]
            if not isinstance(subject, str) or not subject:
                raise InvalidAccessToken
            if not isinstance(email, str) or not email:
                raise InvalidAccessToken
            if claims["role"] != "authenticated":
                raise InvalidAccessToken
            return VerifiedIdentity(subject=subject, email=email)
        except (KeyError, StopIteration, TypeError, ValueError, jwt.PyJWTError) as error:
            raise InvalidAccessToken from error
