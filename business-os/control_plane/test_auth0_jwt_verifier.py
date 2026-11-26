"""Offline cryptographic tests for the issuer-pinned Auth0 JWT verifier."""
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from auth0_jwt_verifier import Auth0JWTVerificationError, Auth0JWTVerifier


ISSUER = "https://tenant.ca.auth0.com/"
AUDIENCE = "https://business-os-api.example/"
NOW = int(time.time())


class FakeJwksClient:
    def __init__(self, key):
        self.key = key
        self.calls = 0

    def get_signing_key_from_jwt(self, token):
        self.calls += 1
        return SimpleNamespace(key=self.key)


class Auth0JWTVerifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()

    def setUp(self):
        self.jwks = FakeJwksClient(self.public_key)
        self.verifier = Auth0JWTVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            jwks_client=self.jwks,
        )

    def make_token(self, **overrides):
        claims = {
            "iss": ISSUER,
            "sub": "operator-1",
            "aud": AUDIENCE,
            "jti": "access-token-123",
            "iat": NOW - 5,
            "exp": NOW + 300,
            "scope": "business-os:read",
            "https://norevyo.com/claims/roles": ["business-os:operator"],
        }
        claims.update(overrides)
        return jwt.encode(
            claims,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "test-key-1", "typ": "JWT"},
        )

    def test_valid_rsa_signature_and_required_claims_are_verified(self):
        claims = self.verifier(self.make_token())
        self.assertEqual(claims["sub"], "operator-1")
        self.assertEqual(claims["iss"], ISSUER)
        self.assertEqual(self.jwks.calls, 1)

    def test_rejects_invalid_signature(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = jwt.encode(
            {"iss": ISSUER, "sub": "attacker", "aud": AUDIENCE, "jti": "x", "iat": NOW, "exp": NOW + 60},
            other,
            algorithm="RS256",
            headers={"kid": "test-key-1"},
        )
        with self.assertRaises(Auth0JWTVerificationError):
            self.verifier(token)

    def test_rejects_wrong_audience_and_issuer(self):
        for changed in ({"aud": "other-api"}, {"iss": "https://attacker.example/"}):
            with self.subTest(changed=changed), self.assertRaises(Auth0JWTVerificationError):
                self.verifier(self.make_token(**changed))

    def test_rejects_expired_future_and_missing_required_claims(self):
        cases = (
            {"exp": NOW - 1},
            {"iat": NOW + 600},
            {"jti": None},
            {"sub": None},
            {"aud": None},
        )
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(Auth0JWTVerificationError):
                self.verifier(self.make_token(**changed))

    def test_rejects_algorithm_confusion_and_unsigned_tokens_before_jwks_lookup(self):
        unsigned = jwt.encode(
            {"iss": ISSUER, "sub": "x", "aud": AUDIENCE, "jti": "x", "iat": NOW, "exp": NOW + 60},
            key=None,
            algorithm="none",
            headers={"kid": "test-key-1"},
        )
        with self.assertRaises(Auth0JWTVerificationError):
            self.verifier(unsigned)
        self.assertEqual(self.jwks.calls, 0)

    def test_rejects_missing_or_oversized_tokens(self):
        for token in ("", "x" * 16385, None):
            with self.subTest(token=type(token).__name__), self.assertRaises(Auth0JWTVerificationError):
                self.verifier(token)

    def test_rejects_malformed_or_untrusted_issuer_urls(self):
        for issuer in (
            "http://tenant.auth0.com/",
            "https://tenant.auth0.com",
            "https://user:pass@tenant.auth0.com/",
            "https://tenant.auth0.com:8443/",
            "https://tenant.auth0.com/path/",
            "https://tenant.auth0.com/?redirect=attacker",
        ):
            with self.subTest(issuer=issuer), self.assertRaises(ValueError):
                Auth0JWTVerifier(issuer=issuer, audience=AUDIENCE, jwks_client=self.jwks)

    def test_jwks_url_is_derived_from_pinned_issuer_and_cache_is_bounded(self):
        self.assertEqual(self.verifier.jwks_uri, ISSUER + ".well-known/jwks.json")
        with patch("auth0_jwt_verifier.PyJWKClient") as client:
            Auth0JWTVerifier(issuer=ISSUER, audience=AUDIENCE)
            client.assert_called_once_with(
                ISSUER + ".well-known/jwks.json",
                cache_jwk_set=True,
                lifespan=300,
                timeout=5.0,
                max_cached_keys=16,
            )

    def test_rejects_invalid_verifier_policy_parameters(self):
        with self.assertRaises(ValueError):
            Auth0JWTVerifier(issuer=ISSUER, audience=AUDIENCE, leeway_seconds=61)
        with self.assertRaises(ValueError):
            Auth0JWTVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_timeout_seconds=30)
        with self.assertRaises(ValueError):
            Auth0JWTVerifier(issuer=ISSUER, audience=AUDIENCE, jwks_cache_seconds=10)


if __name__ == "__main__":
    unittest.main()
