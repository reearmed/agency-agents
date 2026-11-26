"""Security tests for signed approval grants; all data and keys are synthetic."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
import sqlite3
import stat
import unittest

from approval_grants import (
    ApprovalGrantAuthority, GrantError, SQLiteGrantLedger,
)


class ApprovalGrantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = SQLiteGrantLedger(Path(self.tmp.name) / "grants.sqlite3")
        self.now = datetime(2026, 11, 26, 15, 0, tzinfo=timezone.utc)
        self.authority = ApprovalGrantAuthority(
            signing_key=b"x" * 32,
            ledger=self.ledger,
            identity_verifier=lambda actor, context: context == "valid-session" and actor == "human-1",
        )
        self.payload = {"action": "send_email", "recipient": "test@example.invalid", "body": "draft"}
        self.scope = {
            "task_id": "task-1",
            "payload": self.payload,
            "adapter": "email",
            "action": "send",
            "target": "test@example.invalid",
            "idempotency_key": "idem-1",
            "requester_id": "agent-1",
            "now": self.now,
        }

    def issue(self, **overrides):
        args = {
            "task_id": "task-1",
            "payload": self.payload,
            "adapter": "email",
            "action": "send",
            "target": "test@example.invalid",
            "idempotency_key": "idem-1",
            "requester_id": "agent-1",
            "approver_id": "human-1",
            "auth_context": "valid-session",
            "ttl_seconds": 120,
            "now": self.now,
        }
        args.update(overrides)
        return self.authority.issue(**args)

    def consume(self, token, **overrides):
        args = dict(self.scope)
        args.update(overrides)
        return self.authority.verify_and_consume(token, **args)

    def test_valid_grant_consumed_once(self):
        token = self.issue()
        grant = self.consume(token)
        self.assertEqual(grant["approver_id"], "human-1")
        with self.assertRaises(GrantError):
            self.consume(token)

    def test_tampered_signature_rejected(self):
        token = self.issue()
        with self.assertRaises(GrantError):
            self.consume(token[:-1] + ("0" if token[-1] != "0" else "1"))

    def test_payload_mutation_rejected(self):
        token = self.issue()
        changed = dict(self.payload, body="different")
        with self.assertRaises(GrantError):
            self.consume(token, payload=changed)

    def test_target_swap_rejected(self):
        token = self.issue()
        with self.assertRaises(GrantError):
            self.consume(token, target="other@example.invalid")

    def test_action_swap_rejected(self):
        token = self.issue()
        with self.assertRaises(GrantError):
            self.consume(token, action="delete")

    def test_requester_swap_rejected(self):
        token = self.issue()
        with self.assertRaises(GrantError):
            self.consume(token, requester_id="different-agent")

    def test_expired_grant_rejected(self):
        token = self.issue(ttl_seconds=30)
        with self.assertRaises(GrantError):
            self.consume(token, now=self.now + timedelta(seconds=30))

    def test_naive_verification_clock_rejected(self):
        token = self.issue()
        with self.assertRaises(GrantError):
            self.consume(token, now=datetime(2026, 11, 26, 15, 1))

    def test_ledger_database_file_is_private(self):
        mode = stat.S_IMODE(Path(self.ledger.path).stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_future_issued_grant_rejected(self):
        token = self.issue(now=self.now + timedelta(seconds=1))
        with self.assertRaises(GrantError):
            self.consume(token)

    def test_self_approval_rejected(self):
        with self.assertRaises(GrantError):
            self.issue(requester_id="human-1")

    def test_unauthenticated_approver_rejected(self):
        with self.assertRaises(GrantError):
            self.issue(auth_context="forged")

    def test_identity_verifier_exception_fails_closed(self):
        authority = ApprovalGrantAuthority(
            signing_key=b"y" * 32, ledger=self.ledger,
            identity_verifier=lambda actor, context: (_ for _ in ()).throw(RuntimeError("IdP down")),
        )
        args = {
            "task_id": "task-2", "payload": self.payload, "adapter": "email",
            "action": "send", "target": "test@example.invalid", "idempotency_key": "idem-2",
            "requester_id": "agent-1", "approver_id": "human-1",
            "auth_context": "valid-session", "now": self.now,
        }
        with self.assertRaises(GrantError):
            authority.issue(**args)

    def test_short_signing_key_rejected(self):
        with self.assertRaises(ValueError):
            ApprovalGrantAuthority(
                signing_key=b"short", ledger=self.ledger,
                identity_verifier=lambda actor, context: True,
            )

    def test_ttl_above_policy_rejected(self):
        with self.assertRaises(GrantError):
            self.issue(ttl_seconds=901)

    def test_consumption_ledger_rejects_ordinary_delete(self):
        token = self.issue()
        self.consume(token)
        conn = sqlite3.connect(self.ledger.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM consumed_grants")
        finally:
            conn.close()

    def test_concurrent_replay_only_one_consumer_wins(self):
        token = self.issue()
        def attempt(_):
            try:
                self.consume(token)
                return "ok"
            except GrantError:
                return "rejected"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("rejected"), 1)


if __name__ == "__main__":
    unittest.main()
