import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone

from identity_boundary import IdentityBoundary
from independent_verifier import IndependentEvidenceVerifier, VerificationError


NOW = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
DISPATCHED = NOW - timedelta(minutes=2)


class IndependentEvidenceVerifierTests(unittest.TestCase):
    def setUp(self):
        self.claims = {
            "iss": "https://identity.example.test/",
            "sub": "verifier-1",
            "aud": "business-os-api",
            "jti": "verifier-token-1",
            "iat": NOW.timestamp() - 60,
            "exp": NOW.timestamp() + 600,
            "scope": "business-os:verification:record",
            "roles": ["business-os:independent-verifier"],
        }
        boundary = IdentityBoundary(
            token_verifier=lambda token: self.claims,
            expected_issuer="https://identity.example.test/",
            expected_audience="business-os-api",
            clock=lambda: NOW.timestamp(),
        )
        self.principal = boundary.authenticate("Bearer synthetic-verifier-token")
        self.expected = {
            "task_id": "task-1",
            "requester_id": "agent-1",
            "executor_subject": "executor-1",
            "adapter": "mock-adapter",
            "action": "create",
            "target": "sandbox-object",
            "environment": "sandbox",
            "idempotency_key": "idem-1",
            "payload_sha256": "a" * 64,
            "dispatched_at": DISPATCHED.isoformat(),
        }
        self.evidence = {
            "task_id": "task-1",
            "idempotency_key": "idem-1",
            "adapter": "mock-adapter",
            "action": "create",
            "target": "sandbox-object",
            "environment": "sandbox",
            "payload_sha256": "a" * 64,
            "outcome": "succeeded",
            "destination_record_id": "destination-123",
            "observed_at": (NOW - timedelta(seconds=10)).isoformat(),
            "source_id": "trusted-synthetic-destination",
            "raw_evidence_sha256": "b" * 64,
        }
        self.reader_calls = []
        self.verifier = IndependentEvidenceVerifier(
            evidence_reader=lambda adapter, target, key: self._read(adapter, target, key),
            evidence_authenticator=lambda evidence: True,
            trusted_source_id="trusted-synthetic-destination",
            clock=lambda: NOW,
        )

    def _read(self, adapter, target, key):
        self.reader_calls.append((adapter, target, key))
        return self.evidence

    def test_authenticated_independent_verifier_returns_bound_evidence_digest(self):
        result = self.verifier.verify(principal=self.principal, expected=self.expected)
        self.assertEqual(result.outcome, "succeeded")
        self.assertEqual(result.destination_record_id, "destination-123")
        self.assertEqual(result.verifier_subject, "verifier-1")
        self.assertEqual(result.evidence_sha256, hashlib.sha256(
            json.dumps(self.evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest())
        self.assertEqual(self.reader_calls, [("mock-adapter", "sandbox-object", "idem-1")])

    def test_rejects_non_verifier_role_or_scope(self):
        for changes in (
            {"scope": "business-os:read", "roles": ["business-os:independent-verifier"]},
            {"scope": "business-os:verification:record", "roles": ["business-os:operator"]},
        ):
            self.claims = {**self.claims, **changes}
            boundary = IdentityBoundary(
                token_verifier=lambda token: self.claims,
                expected_issuer="https://identity.example.test/",
                expected_audience="business-os-api",
                clock=lambda: NOW.timestamp(),
            )
            principal = boundary.authenticate("Bearer synthetic-token")
            with self.subTest(changes=changes), self.assertRaises(VerificationError):
                self.verifier.verify(principal=principal, expected=self.expected)

    def test_rejects_verifier_who_is_requester_or_executor(self):
        for field in ("requester_id", "executor_subject"):
            expected = {**self.expected, field: "verifier-1"}
            with self.subTest(field=field), self.assertRaises(VerificationError):
                self.verifier.verify(principal=self.principal, expected=expected)

    def test_rejects_payload_target_or_idempotency_mismatch(self):
        for field, value in (("payload_sha256", "c" * 64), ("target", "other-target"), ("idempotency_key", "other-key")):
            with self.subTest(field=field):
                self.evidence = {**self.evidence, field: value}
                with self.assertRaises(VerificationError):
                    self.verifier.verify(principal=self.principal, expected=self.expected)
                self.evidence = {
                    **self.evidence,
                    "payload_sha256": "a" * 64,
                    "target": "sandbox-object",
                    "idempotency_key": "idem-1",
                }

    def test_rejects_untrusted_source_and_unauthenticated_evidence(self):
        self.evidence = {**self.evidence, "source_id": "unknown-source"}
        with self.assertRaises(VerificationError):
            self.verifier.verify(principal=self.principal, expected=self.expected)
        self.evidence = {**self.evidence, "source_id": "trusted-synthetic-destination"}
        self.verifier = IndependentEvidenceVerifier(
            evidence_reader=lambda adapter, target, key: self.evidence,
            evidence_authenticator=lambda evidence: False,
            trusted_source_id="trusted-synthetic-destination",
            clock=lambda: NOW,
        )
        with self.assertRaises(VerificationError):
            self.verifier.verify(principal=self.principal, expected=self.expected)

    def test_rejects_missing_unknown_and_malformed_evidence(self):
        for evidence in (None, {**self.evidence, "unexpected": True}, {**self.evidence, "outcome": "unknown"}, {**self.evidence, "outcome": []}):
            self.verifier = IndependentEvidenceVerifier(
                evidence_reader=lambda adapter, target, key, evidence=evidence: evidence,
                evidence_authenticator=lambda value: True,
                trusted_source_id="trusted-synthetic-destination",
                clock=lambda: NOW,
            )
            with self.subTest(evidence=evidence), self.assertRaises(VerificationError):
                self.verifier.verify(principal=self.principal, expected=self.expected)

    def test_rejects_invalid_or_stale_evidence_timestamps(self):
        for observed_at in ("not-a-date", "2026-11-26T20:00:00", (NOW + timedelta(hours=1)).isoformat(), (NOW - timedelta(days=2)).isoformat(), (DISPATCHED - timedelta(minutes=2)).isoformat()):
            self.evidence = {**self.evidence, "observed_at": observed_at}
            with self.subTest(observed_at=observed_at), self.assertRaises(VerificationError):
                self.verifier.verify(principal=self.principal, expected=self.expected)
        self.evidence = {**self.evidence, "observed_at": (NOW - timedelta(seconds=10)).isoformat()}

    def test_rejects_reader_and_authenticator_failures(self):
        self.verifier = IndependentEvidenceVerifier(
            evidence_reader=lambda adapter, target, key: (_ for _ in ()).throw(RuntimeError("offline")),
            evidence_authenticator=lambda evidence: True,
            trusted_source_id="trusted-synthetic-destination",
            clock=lambda: NOW,
        )
        with self.assertRaises(VerificationError):
            self.verifier.verify(principal=self.principal, expected=self.expected)


if __name__ == "__main__":
    unittest.main()
