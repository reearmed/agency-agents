"""Tests for the mock-only execution gateway. No external side effects occur."""
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from approval_grants import ApprovalGrantAuthority, SQLiteGrantLedger
from execution_gateway import (
    ExecutionState, GatewayError, MockAdapter, MockExecutionGateway, MockOutcomeVerifier,
)


class ExecutionGatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        ledger = SQLiteGrantLedger(Path(self.tmp.name) / "grants.sqlite3")
        self.authority = ApprovalGrantAuthority(
            signing_key=b"g" * 32,
            ledger=ledger,
            identity_verifier=lambda actor, context: actor == "human" and context == "ok",
        )
        self.operation = {"kind": "draft_only", "content": "synthetic test"}
        self.now = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)
        self.adapter = MockAdapter()
        self.verifier = MockOutcomeVerifier()
        self.kill_switch = False
        self.gateway = MockExecutionGateway(
            authority=self.authority,
            adapter=self.adapter,
            verifier=self.verifier,
            kill_switch_check=lambda: self.kill_switch,
        )

    def grant(self, *, task="task-1", operation=None, key="idem-1"):
        operation = self.operation if operation is None else operation
        return self.authority.issue(
            task_id=task, payload=operation, adapter="mock", action="simulate",
            target="synthetic://sandbox", idempotency_key=key,
            requester_id="agent", approver_id="human", auth_context="ok",
            ttl_seconds=300, now=self.now,
        )

    def submit(self, token, *, task="task-1", operation=None, key="idem-1"):
        operation = self.operation if operation is None else operation
        return self.gateway.execute(
            token, task_id=task, payload=operation, adapter_name="mock",
            action="simulate", target="synthetic://sandbox",
            idempotency_key=key, requester_id="agent",
        )

    def test_success_requires_separate_reconciliation(self):
        record = self.submit(self.grant())
        self.assertEqual(record.state, ExecutionState.EXECUTING)
        self.assertEqual(self.adapter.call_count, 1)
        final = self.gateway.reconcile("task-1")
        self.assertEqual(final.state, ExecutionState.SUCCEEDED)
        self.assertEqual(final.detail, "independently reconciled by mock verifier")

    def test_timeout_after_mock_commit_is_unknown_not_retry(self):
        self.adapter.timeout_after_commit = True
        record = self.submit(self.grant())
        self.assertEqual(record.state, ExecutionState.UNKNOWN)
        self.assertEqual(self.adapter.call_count, 1)
        final = self.gateway.reconcile("task-1")
        self.assertEqual(final.state, ExecutionState.SUCCEEDED)
        self.assertEqual(self.adapter.call_count, 1)

    def test_failure_before_commit_is_unknown_then_reconciled_failed(self):
        self.adapter.fail_before_commit = True
        record = self.submit(self.grant())
        self.assertEqual(record.state, ExecutionState.UNKNOWN)
        final = self.gateway.reconcile("task-1")
        self.assertEqual(final.state, ExecutionState.FAILED)

    def test_kill_switch_denies_before_grant_consumption_or_adapter(self):
        token = self.grant()
        self.kill_switch = True
        with self.assertRaises(GatewayError):
            self.submit(token)
        self.kill_switch = False
        self.assertEqual(self.submit(token).state, ExecutionState.EXECUTING)
        self.assertEqual(self.adapter.call_count, 1)

    def test_unavailable_kill_switch_fails_closed(self):
        gateway = MockExecutionGateway(
            authority=self.authority, adapter=self.adapter, verifier=self.verifier,
            kill_switch_check=lambda: None,
        )
        with self.assertRaises(GatewayError):
            gateway.execute(
                self.grant(), task_id="task-1", payload=self.operation,
                adapter_name="mock", action="simulate", target="synthetic://sandbox",
                idempotency_key="idem-1", requester_id="agent",
            )
        self.assertEqual(self.adapter.call_count, 0)

    def test_invalid_grant_never_calls_adapter(self):
        with self.assertRaises(GatewayError):
            self.submit("forged.token")
        self.assertEqual(self.adapter.call_count, 0)

    def test_payload_substitution_never_calls_adapter(self):
        token = self.grant()
        with self.assertRaises(GatewayError):
            self.submit(token, operation={"kind": "different"})
        self.assertEqual(self.adapter.call_count, 0)

    def test_duplicate_task_submission_is_blocked(self):
        token = self.grant()
        self.submit(token)
        with self.assertRaises(GatewayError):
            self.submit(token)
        self.assertEqual(self.adapter.call_count, 1)

    def test_reconcile_only_accepts_pending_task(self):
        with self.assertRaises(GatewayError):
            self.gateway.reconcile("missing")

    def test_only_explicit_mock_components_are_accepted(self):
        class FakeAdapter:
            pass
        with self.assertRaises(TypeError):
            MockExecutionGateway(
                authority=self.authority, adapter=FakeAdapter(),
                verifier=self.verifier, kill_switch_check=lambda: False,
            )


if __name__ == "__main__":
    unittest.main()
