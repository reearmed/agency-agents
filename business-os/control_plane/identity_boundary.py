"""Fail-closed identity boundary for the local Business OS control-plane prototype.

The injected token verifier MUST perform cryptographic JWT validation (signature,
algorithm allowlist, trusted JWKS/key rotation and revocation policy). This module
validates claims and authorization after that step; it is not an HTTP server or
a JWT implementation and does not establish production authentication by itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Any, Callable, Mapping


class IdentityError(RuntimeError):
    """Authentication or authorization failed; callers must fail closed."""


BUSINESS_OS_SCOPES = frozenset({
    "business-os:read",
    "business-os:task:submit",
    "business-os:artifact:write",
    "business-os:approval:request",
    "business-os:approval:decide",
    "business-os:budget:configure",
    "business-os:kill-switch:activate",
})
BUSINESS_OS_ROLES = frozenset({
    "business-os:human-approver",
    "business-os:budget-operator",
    "business-os:operator",
})


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Minimal verified identity; never contains the bearer token."""

    issuer: str
    subject: str
    audience: str
    token_id: str
    issued_at: float
    expires_at: float
    scopes: frozenset[str]
    roles: frozenset[str]


class IdentityBoundary:
    """Validate bearer tokens using an injected cryptographic token verifier."""

    def __init__(
        self,
        *,
        token_verifier: Callable[[str], Mapping[str, Any]],
        expected_issuer: str,
        expected_audience: str,
        clock: Callable[[], float] = time.time,
        clock_skew_seconds: int = 30,
        max_lifetime_seconds: int = 3600,
    ):
        if not callable(token_verifier) or not callable(clock):
            raise ValueError("token_verifier and clock callbacks are required")
        if not isinstance(expected_issuer, str) or not expected_issuer.strip():
            raise ValueError("expected issuer is required")
        if not isinstance(expected_audience, str) or not expected_audience.strip():
            raise ValueError("expected audience is required")
        if isinstance(clock_skew_seconds, bool) or not isinstance(clock_skew_seconds, int) or not 0 <= clock_skew_seconds <= 300:
            raise ValueError("clock skew must be between 0 and 300 seconds")
        if isinstance(max_lifetime_seconds, bool) or not isinstance(max_lifetime_seconds, int) or not 1 <= max_lifetime_seconds <= 86400:
            raise ValueError("maximum token lifetime must be between 1 and 86400 seconds")
        self._token_verifier = token_verifier
        self._issuer = expected_issuer
        self._audience = expected_audience
        self._clock = clock
        self._skew = clock_skew_seconds
        self._max_lifetime = max_lifetime_seconds

    @staticmethod
    def _timestamp(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise IdentityError(f"token {name} claim is invalid")
        try:
            numeric = float(value)
        except (OverflowError, ValueError) as exc:
            raise IdentityError(f"token {name} claim is invalid") from exc
        if not math.isfinite(numeric):
            raise IdentityError(f"token {name} claim is invalid")
        return numeric

    def authenticate(self, authorization_header: str) -> VerifiedPrincipal:
        if not isinstance(authorization_header, str) or len(authorization_header) > 16400:
            raise IdentityError("bearer authorization header is missing or too large")
        scheme, separator, token = authorization_header.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not token
            or any(char.isspace() for char in token)
            or len(token) > 16384
        ):
            raise IdentityError("a single bounded bearer token is required")
        try:
            claims = self._token_verifier(token)
        except Exception as exc:
            raise IdentityError("token signature or issuer verification failed") from exc
        if not isinstance(claims, Mapping):
            raise IdentityError("verified token claims must be an object")

        issuer = claims.get("iss")
        subject = claims.get("sub")
        token_id = claims.get("jti")
        if issuer != self._issuer:
            raise IdentityError("token issuer mismatch")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 256:
            raise IdentityError("token subject is invalid")
        if not isinstance(token_id, str) or not token_id.strip() or len(token_id) > 256:
            raise IdentityError("token identifier is required")

        raw_audience = claims.get("aud")
        audiences = [raw_audience] if isinstance(raw_audience, str) else raw_audience
        if (
            not isinstance(audiences, (list, tuple))
            or not audiences
            or any(not isinstance(item, str) or not item for item in audiences)
            or self._audience not in audiences
        ):
            raise IdentityError("token audience mismatch")

        try:
            now = self._timestamp(self._clock(), "clock")
        except IdentityError:
            raise
        except Exception as exc:
            raise IdentityError("trusted clock is unavailable") from exc
        issued_at = self._timestamp(claims.get("iat"), "issued-at")
        expires_at = self._timestamp(claims.get("exp"), "expiry")
        not_before = self._timestamp(claims.get("nbf", issued_at), "not-before")
        if issued_at > now + self._skew or not_before > now + self._skew:
            raise IdentityError("token is not yet valid")
        if expires_at <= now or expires_at <= issued_at:
            raise IdentityError("token is expired or has invalid lifetime")
        if expires_at - issued_at > self._max_lifetime:
            raise IdentityError("token lifetime exceeds policy")

        raw_scopes = claims.get("scope", "")
        if not isinstance(raw_scopes, str):
            raise IdentityError("token scope claim must be a space-delimited string")
        scopes = frozenset(scope for scope in raw_scopes.split() if scope in BUSINESS_OS_SCOPES)
        raw_roles = claims.get("roles", [])
        if (
            not isinstance(raw_roles, (list, tuple))
            or any(not isinstance(role, str) or not role.strip() for role in raw_roles)
        ):
            raise IdentityError("token roles claim is invalid")
        roles = frozenset(role for role in raw_roles if role in BUSINESS_OS_ROLES)
        return VerifiedPrincipal(
            issuer=issuer,
            subject=subject,
            audience=self._audience,
            token_id=token_id,
            issued_at=issued_at,
            expires_at=expires_at,
            scopes=scopes,
            roles=roles,
        )


def require_scope(principal: VerifiedPrincipal, scope: str) -> None:
    """Authorize a previously authenticated principal for one exact scope."""
    if not isinstance(principal, VerifiedPrincipal):
        raise IdentityError("verified principal required")
    if (
        not isinstance(scope, str)
        or scope not in BUSINESS_OS_SCOPES
        or scope not in principal.scopes
    ):
        raise IdentityError("required or unsupported scope is missing")


def human_approver_identity_verifier(actor_id: str, context: Any) -> bool:
    """Callback for ApprovalGrantAuthority; requires a verified human principal."""
    if not isinstance(context, VerifiedPrincipal):
        return False
    return (
        isinstance(actor_id, str)
        and bool(actor_id.strip())
        and context.subject == actor_id
        and "business-os:approval:decide" in context.scopes
        and "business-os:human-approver" in context.roles
    )
