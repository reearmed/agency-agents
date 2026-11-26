"""Server-side route authorization helpers for the static OpenAPI contract.

The HTTP service must authenticate the bearer token first, then call this
function with the operation selected from the server-owned OpenAPI document.
Never accept operation metadata or permission lists from the request body.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from identity_boundary import (
    BUSINESS_OS_ROLES,
    BUSINESS_OS_SCOPES,
    IdentityError,
    VerifiedPrincipal,
)


def authorize_operation(
    principal: VerifiedPrincipal | None,
    operation: Mapping[str, Any],
    *,
    default_security: Any,
) -> None:
    """Enforce one OpenAPI operation's bearer, scope and role requirements.

    All listed scopes and roles are conjunctive requirements. An explicitly
    public operation (security: []) is accepted only when it declares no
    authorization extensions. Missing or malformed policy fails closed.
    """
    if not isinstance(operation, Mapping):
        raise IdentityError("server-owned API operation policy is required")

    security = operation.get("security", default_security)
    scopes = operation.get("x-required-scopes")
    roles = operation.get("x-required-roles")

    if security == []:
        if scopes not in (None, []) or roles not in (None, []):
            raise IdentityError("public operation cannot declare privileged requirements")
        return

    if not isinstance(security, list) or not security or not any(
        isinstance(item, Mapping) and "bearerAuth" in item for item in security
    ):
        raise IdentityError("protected operation must require bearer authentication")

    if (
        not isinstance(scopes, list)
        or not scopes
        or any(not isinstance(scope, str) or scope not in BUSINESS_OS_SCOPES for scope in scopes)
    ):
        raise IdentityError("protected operation has missing or unsupported scope policy")
    if (
        roles is not None
        and (
            not isinstance(roles, list)
            or any(not isinstance(role, str) or role not in BUSINESS_OS_ROLES for role in roles)
        )
    ):
        raise IdentityError("operation has malformed or unsupported role policy")

    if not isinstance(principal, VerifiedPrincipal):
        raise IdentityError("verified principal required")
    if not set(scopes).issubset(principal.scopes):
        raise IdentityError("one or more required scopes are missing")
    if roles and not set(roles).issubset(principal.roles):
        raise IdentityError("one or more required roles are missing")
