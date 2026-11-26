"""Cryptographic Auth0 RS256 access-token verifier.

This is a production-oriented verifier component, not an HTTP server. The
issuer is an operator-supplied trust anchor; the JWKS URL is derived from that
issuer and cannot be supplied independently by a request or agent.
"""
from __future__ import annotations

from urllib.parse import urlsplit
from typing import Any

import jwt
from jwt import PyJWKClient


class Auth0JWTVerificationError(RuntimeError):
    """A bearer token could not be cryptographically authenticated."""


class Auth0JWTVerifier:
    """Verify Auth0 access tokens against issuer-pinned HTTPS JWKS."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_client: Any | None = None,
        leeway_seconds: int = 30,
        jwks_timeout_seconds: float = 5.0,
        jwks_cache_seconds: int = 300,
    ) -> None:
        if not isinstance(issuer, str) or not issuer.endswith("/"):
            raise ValueError("issuer must be an exact HTTPS issuer URL ending in '/'")
        parsed = urlsplit(issuer)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.path != "/"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("issuer must be a plain HTTPS origin with a trailing slash")
        if not isinstance(audience, str) or not audience.strip():
            raise ValueError("API audience is required")
        if isinstance(leeway_seconds, bool) or not isinstance(leeway_seconds, int) or not 0 <= leeway_seconds <= 60:
            raise ValueError("JWT leeway must be between 0 and 60 seconds")
        if isinstance(jwks_timeout_seconds, bool) or not isinstance(jwks_timeout_seconds, (int, float)) or not 1 <= jwks_timeout_seconds <= 10:
            raise ValueError("JWKS timeout must be between 1 and 10 seconds")
        if isinstance(jwks_cache_seconds, bool) or not isinstance(jwks_cache_seconds, int) or not 60 <= jwks_cache_seconds <= 3600:
            raise ValueError("JWKS cache lifetime must be between 60 and 3600 seconds")

        self.issuer = issuer
        self.audience = audience
        self.leeway_seconds = leeway_seconds
        self.jwks_uri = issuer + ".well-known/jwks.json"
        # Never accept a JWKS URL from a token, request, or untrusted config.
        self._jwks = jwks_client or PyJWKClient(
            self.jwks_uri,
            cache_keys=True,
            max_cached_keys=16,
            cache_jwk_set=True,
            lifespan=jwks_cache_seconds,
            timeout=float(jwks_timeout_seconds),
            max_cached_keys=16,
        )

    def __call__(self, token: str) -> dict[str, Any]:
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise Auth0JWTVerificationError("access token is missing or oversized")
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise Auth0JWTVerificationError("only RS256 access tokens are accepted")
            if str(header.get("typ", "")).lower() != "at+jwt":
                raise Auth0JWTVerificationError("RFC 9068 access-token type is required")
            kid = header.get("kid")
            if not isinstance(kid, str) or not kid or len(kid) > 256:
                raise Auth0JWTVerificationError("a bounded signing key identifier is required")
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={
                    "require": ["iss", "sub", "aud", "exp", "iat", "jti", "client_id"],
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_nbf": True,
                    "verify_iss": True,
                    "verify_aud": True,
                },
            )
            if not isinstance(claims, dict):
                raise Auth0JWTVerificationError("JWT claims must be an object")
            return claims
        except Auth0JWTVerificationError:
            raise
        except Exception as exc:
            # Do not leak token, key material, or provider details to callers.
            raise Auth0JWTVerificationError("access token verification failed") from exc
