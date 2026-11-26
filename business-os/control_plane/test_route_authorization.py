"""Tests for fail-closed server-side OpenAPI route authorization."""
from pathlib import Path
import unittest

import yaml

from identity_boundary import (
    IdentityBoundary,
    IdentityError,
    BUSINESS_OS_SCOPES,
    BUSINESS_OS_ROLES,
)
from route_authorization import authorize_operation


ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "api" / "openapi.yaml").read_text(encoding="utf-8"))


def principal(scopes=None, roles=None):
    values = {
        "iss": "https://identity.example.test/",
        "sub": "operator-1",
        "aud": "business-os-api",
        "jti": "route-token-1",
        "iat": 1_800_000_000,
        "exp": 1_800_000_300,
        "scope": " ".join(scopes if scopes is not None else ["business-os:read"]),
        "roles": roles if roles is not None else [],
    }
    boundary = IdentityBoundary(
        token_verifier=lambda token: values,
        expected_issuer="https://identity.example.test/",
        expected_audience="business-os-api",
        clock=lambda: 1_800_000_000,
    )
    return boundary.authenticate("Bearer route-test-token")


class RouteAuthorizationTests(unittest.TestCase):
    def test_every_protected_openapi_operation_has_valid_server_side_policy(self):
        for path, methods in SPEC["paths"].items():
            for method, operation in methods.items():
                with self.subTest(path=path, method=method):
                    if operation.get("security", SPEC.get("security")) == []:
                        authorize_operation(None, operation, default_security=SPEC.get("security"))
                    else:
                        required = operation["x-required-scopes"]
                        roles = operation.get("x-required-roles", [])
                        p = principal(scopes=required, roles=roles)
                        authorize_operation(p, operation, default_security=SPEC.get("security"))

    def test_protected_route_requires_verified_principal(self):
        operation = SPEC["paths"]["/tasks"]["post"]
        with self.assertRaises(IdentityError):
            authorize_operation(None, operation, default_security=SPEC.get("security"))

    def test_missing_scope_and_missing_sensitive_role_are_denied(self):
        approval = SPEC["paths"]["/approvals/{approval_id}/decision"]["post"]
        with self.assertRaises(IdentityError):
            authorize_operation(
                principal(scopes=["business-os:read"], roles=["business-os:human-approver"]),
                approval,
                default_security=SPEC.get("security"),
            )
        with self.assertRaises(IdentityError):
            authorize_operation(
                principal(
                    scopes=["business-os:approval:decide"],
                    roles=["business-os:operator"],
                ),
                approval,
                default_security=SPEC.get("security"),
            )

    def test_public_health_route_does_not_require_principal(self):
        health = SPEC["paths"]["/healthz"]["get"]
        authorize_operation(None, health, default_security=SPEC.get("security"))

    def test_public_route_cannot_smuggle_privileged_scope(self):
        malicious = {"security": [], "x-required-scopes": ["business-os:budget:configure"]}
        with self.assertRaises(IdentityError):
            authorize_operation(None, malicious, default_security=SPEC.get("security"))

    def test_missing_or_unrecognized_scope_policy_fails_closed(self):
        for operation in (
            {"security": [{"bearerAuth": []}]},
            {"security": [{"bearerAuth": []}], "x-required-scopes": ["billing:admin"]},
            {"security": [{"basicAuth": []}], "x-required-scopes": ["business-os:read"]},
        ):
            with self.subTest(operation=operation), self.assertRaises(IdentityError):
                authorize_operation(principal(), operation, default_security=SPEC.get("security"))

    def test_unknown_roles_are_never_authorized(self):
        operation = {
            "security": [{"bearerAuth": []}],
            "x-required-scopes": ["business-os:read"],
            "x-required-roles": ["system-admin"],
        }
        with self.assertRaises(IdentityError):
            authorize_operation(principal(), operation, default_security=SPEC.get("security"))

    def test_allowlists_used_by_route_authorizer_are_explicit(self):
        self.assertIn("business-os:read", BUSINESS_OS_SCOPES)
        self.assertIn("business-os:human-approver", BUSINESS_OS_ROLES)


if __name__ == "__main__":
    unittest.main()
