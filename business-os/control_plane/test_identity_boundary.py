import unittest

from identity_boundary import (
    IdentityBoundary,
    IdentityError,
    VerifiedPrincipal,
    human_approver_identity_verifier,
    require_scope,
)


NOW = 1_800_000_000.0


def claims(**overrides):
    result = {
        "iss": "https://identity.example.test/",
        "sub": "operator-1",
        "aud": ["business-os-api"],
        "jti": "token-123",
        "iat": NOW - 60,
        "nbf": NOW - 60,
        "exp": NOW + 600,
        "scope": "business-os:read business-os:approval:decide",
        "roles": ["business-os:human-approver"],
    }
    result.update(overrides)
    return result


class IdentityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.token_claims = claims()
        self.boundary = IdentityBoundary(
            token_verifier=lambda token: self.token_claims if token == "signed-test-token" else (_ for _ in ()).throw(ValueError("bad signature")),
            expected_issuer="https://identity.example.test/",
            expected_audience="business-os-api",
            clock=lambda: NOW,
        )

    def authenticate(self):
        return self.boundary.authenticate("Bearer signed-test-token")

    def test_valid_token_yields_minimal_principal_without_bearer_secret(self):
        principal = self.authenticate()
        self.assertEqual(principal.subject, "operator-1")
        self.assertEqual(principal.audience, "business-os-api")
        self.assertNotIn("signed-test-token", repr(principal))
        self.assertIsInstance(principal, VerifiedPrincipal)

    def test_rejects_missing_or_malformed_bearer_header(self):
        for header in ("", "signed-test-token", "Basic signed-test-token", "Bearer a b", "Bearer  token", "Bearer\ttoken", None):
            with self.subTest(header=header):
                with self.assertRaises(IdentityError):
                    self.boundary.authenticate(header)

    def test_rejects_bad_signature_verifier_result(self):
        with self.assertRaises(IdentityError):
            self.boundary.authenticate("Bearer wrong-token")

    def test_rejects_wrong_issuer_and_audience(self):
        for changed in ({"iss": "https://attacker.invalid/"}, {"aud": ["other-api"]}):
            self.token_claims = claims(**changed)
            with self.subTest(changed=changed), self.assertRaises(IdentityError):
                self.authenticate()

    def test_rejects_expired_future_and_excessive_lifetime_tokens(self):
        invalid = (
            {"exp": NOW},
            {"iat": NOW + 100},
            {"nbf": NOW + 100},
            {"exp": NOW + 7200},
            {"exp": True},
            {"exp": 10 ** 10000},
        )
        for changed in invalid:
            self.token_claims = claims(**changed)
            with self.subTest(changed=changed), self.assertRaises(IdentityError):
                self.authenticate()

    def test_rejects_missing_subject_or_token_identifier(self):
        for changed in ({"sub": ""}, {"jti": None}):
            self.token_claims = claims(**changed)
            with self.subTest(changed=changed), self.assertRaises(IdentityError):
                self.authenticate()

    def test_rejects_invalid_scope_or_role_claims(self):
        for changed in ({"scope": ["business-os:read"]}, {"roles": "human"}, {"roles": [""]}):
            self.token_claims = claims(**changed)
            with self.subTest(changed=changed), self.assertRaises(IdentityError):
                self.authenticate()

    def test_scope_authorization_fails_closed(self):
        principal = self.authenticate()
        require_scope(principal, "business-os:read")
        with self.assertRaises(IdentityError):
            require_scope(principal, "business-os:execution:write")
        with self.assertRaises(IdentityError):
            require_scope({"subject": "operator-1"}, "business-os:read")

    def test_human_approval_callback_requires_subject_scope_and_role(self):
        principal = self.authenticate()
        self.assertTrue(human_approver_identity_verifier("operator-1", principal))
        self.assertFalse(human_approver_identity_verifier("agent-1", principal))
        self.assertFalse(human_approver_identity_verifier("operator-1", object()))
        self.token_claims = claims(roles=[])
        no_role = self.authenticate()
        self.assertFalse(human_approver_identity_verifier("operator-1", no_role))
        self.token_claims = claims(scope="business-os:read")
        no_scope = self.authenticate()
        self.assertFalse(human_approver_identity_verifier("operator-1", no_scope))


if __name__ == "__main__":
    unittest.main()
