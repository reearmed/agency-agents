"""Integration tests connecting verified identity to exact-scope approval grants."""
import tempfile
import unittest
from pathlib import Path

from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from identity_boundary import (
    IdentityBoundary,
    human_approver_identity_verifier,
)


NOW = 1_800_000_000.0


class IdentityApprovalIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = SQLiteGrantLedger(Path(self.temp.name) / "approval-ledger.sqlite3")
        self.claims = {
            "iss": "https://identity.example.test/",
            "sub": "operator-1",
            "aud": "business-os-api",
            "jti": "identity-token-1",
            "iat": NOW - 30,
            "exp": NOW + 300,
            "scope": "business-os:approval:decide",
            "roles": ["business-os:human-approver"],
        }
        self.boundary = IdentityBoundary(
            token_verifier=lambda token: self.claims,
            expected_issuer="https://identity.example.test/",
            expected_audience="business-os-api",
            clock=lambda: NOW,
        )
        self.authority = ApprovalGrantAuthority(
            signing_key=b"i" * 32,
            ledger=self.ledger,
            identity_verifier=human_approver_identity_verifier,
        )
        self.payload = {"operation": "create synthetic draft"}

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_human_can_issue_and_consume_exact_scope_grant(self):
        principal = self.boundary.authenticate("Bearer synthetic-oidc-token")
        token = self.authority.issue(
            task_id="task-identity-1",
            payload=self.payload,
            adapter="mock",
            action="create",
            target="synthetic-destination",
            idempotency_key="identity-idem-1",
            requester_id="agent-1",
            approver_id="operator-1",
            auth_context=principal,
            ttl_seconds=120,
        )
        grant = self.authority.verify_and_consume(
            token,
            task_id="task-identity-1",
            payload=self.payload,
            adapter="mock",
            action="create",
            target="synthetic-destination",
            idempotency_key="identity-idem-1",
            requester_id="agent-1",
        )
        self.assertEqual(grant["approver_id"], "operator-1")

    def test_agent_or_wrong_subject_cannot_issue_human_approval(self):
        principal = self.boundary.authenticate("Bearer synthetic-oidc-token")
        with self.assertRaises(GrantError):
            self.authority.issue(
                task_id="task-identity-2",
                payload=self.payload,
                adapter="mock",
                action="create",
                target="synthetic-destination",
                idempotency_key="identity-idem-2",
                requester_id="agent-1",
                approver_id="agent-1",
                auth_context=principal,
            )

    def test_verified_principal_without_human_role_or_scope_is_denied(self):
        self.claims = {
            **self.claims,
            "scope": "business-os:read",
            "roles": ["business-os:agent"],
        }
        principal = self.boundary.authenticate("Bearer synthetic-agent-token")
        with self.assertRaises(GrantError):
            self.authority.issue(
                task_id="task-identity-3",
                payload=self.payload,
                adapter="mock",
                action="create",
                target="synthetic-destination",
                idempotency_key="identity-idem-3",
                requester_id="agent-1",
                approver_id="operator-1",
                auth_context=principal,
            )


if __name__ == "__main__":
    unittest.main()
