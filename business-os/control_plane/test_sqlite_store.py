import sqlite3
import stat
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from guardrails import (
    Approval, ApprovalError, AuditError, BudgetError, GuardrailError,
    StateError, TaskState, payload_sha256,
)
from sqlite_store import SQLiteControlPlane


def approval_for(task_id, digest, **overrides):
    values = dict(
        approval_id="approval-sqlite-0001", task_id=task_id,
        payload_sha256=digest, approver_id="operator-test",
        decision="approved", approved_at="2026-11-26T12:00:00Z",
        expires_at="2026-11-26T12:10:00Z", adapter="email",
        action="send", target="recipient@example.invalid",
    )
    values.update(overrides)
    return Approval(**values)


class SQLiteControlPlaneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "business-os.sqlite3"
        self.cp = SQLiteControlPlane(self.db_path, monthly_budget=5.0)
        self.now = datetime(2026, 11, 26, 12, 5, tzinfo=timezone.utc)
        self.scope = {
            "adapter": "email", "action": "send",
            "target": "recipient@example.invalid",
        }

    def tearDown(self):
        self.temp.cleanup()

    def propose(self, task_id="task-sqlite-0001", payload=None):
        payload = payload if payload is not None else {"body": "synthetic draft"}
        return payload, self.cp.propose(task_id, payload)

    def approve(self, task_id, payload, digest, approval=None):
        self.cp.approve(
            task_id=task_id, payload=payload,
            approval=approval or approval_for(task_id, digest),
            expected_scope=self.scope, human_approver=True, now=self.now,
        )

    def test_task_state_persists_across_store_instances(self):
        self.propose()
        reopened = SQLiteControlPlane(self.db_path, monthly_budget=5.0)
        self.assertEqual(reopened.task_state("task-sqlite-0001"), TaskState.PROPOSED)

    def test_approval_must_match_original_proposed_payload(self):
        payload, digest = self.propose()
        replacement = {"body": "changed after proposal"}
        forged = approval_for("task-sqlite-0001", payload_sha256(replacement))
        with self.assertRaises(ApprovalError):
            self.approve("task-sqlite-0001", replacement, digest, forged)

    def test_exact_approval_transitions_to_approved(self):
        payload, digest = self.propose()
        self.approve("task-sqlite-0001", payload, digest)
        self.assertEqual(self.cp.task_state("task-sqlite-0001"), TaskState.APPROVED)

    def test_replayed_approval_id_is_rejected(self):
        payload, digest = self.propose()
        approval = approval_for("task-sqlite-0001", digest)
        self.approve("task-sqlite-0001", payload, digest, approval)
        other_payload = {"body": "another synthetic draft"}
        other_digest = self.cp.propose("task-sqlite-0002", other_payload)
        replay = approval_for("task-sqlite-0002", other_digest,
                              approval_id=approval.approval_id)
        with self.assertRaises(ApprovalError):
            self.approve("task-sqlite-0002", other_payload, other_digest, replay)

    def test_expired_approval_is_rejected(self):
        payload, digest = self.propose()
        expired = approval_for("task-sqlite-0001", digest,
                               expires_at="2026-11-26T12:04:00Z")
        with self.assertRaises(ApprovalError):
            self.approve("task-sqlite-0001", payload, digest, expired)

    def test_generic_transition_cannot_mark_success(self):
        self.propose()
        with self.assertRaises(StateError):
            self.cp.transition("task-sqlite-0001", TaskState.SUCCEEDED)

    def test_terminal_outcome_requires_verifier_evidence(self):
        payload, digest = self.propose()
        self.approve("task-sqlite-0001", payload, digest)
        self.cp.transition("task-sqlite-0001", TaskState.EXECUTING)
        self.cp.transition("task-sqlite-0001", TaskState.UNKNOWN)
        with self.assertRaises(StateError):
            self.cp.record_verified_outcome(
                "task-sqlite-0001", TaskState.SUCCEEDED,
                verifier_id="independent-reviewer", evidence_sha256="bad",
            )
        self.cp.record_verified_outcome(
            "task-sqlite-0001", TaskState.SUCCEEDED,
            verifier_id="independent-reviewer", evidence_sha256="a" * 64,
        )
        self.assertEqual(self.cp.task_state("task-sqlite-0001"), TaskState.SUCCEEDED)

    def test_idempotency_claim_is_persistent_and_replay_safe(self):
        self.propose()
        self.assertTrue(self.cp.claim_idempotency("sqlite-key-000001", "task-sqlite-0001"))
        reopened = SQLiteControlPlane(self.db_path, monthly_budget=5.0)
        self.assertFalse(reopened.claim_idempotency("sqlite-key-000001", "task-sqlite-0001"))
        self.propose("task-sqlite-0002", {"body": "other"})
        with self.assertRaises(GuardrailError):
            reopened.claim_idempotency("sqlite-key-000001", "task-sqlite-0002")

    def test_budget_cap_is_transactional_under_concurrency(self):
        for index in range(20):
            self.propose(f"task-budget-{index:03d}", {"index": index})
        def reserve(index):
            try:
                self.cp.reserve_budget(f"task-budget-{index:03d}", 1.0)
                return True
            except BudgetError:
                return False
        with ThreadPoolExecutor(max_workers=20) as pool:
            outcomes = list(pool.map(reserve, range(20)))
        self.assertEqual(sum(outcomes), 5)
        self.assertTrue(self.cp.verify_audit_chain())

    def test_kill_switch_blocks_approval_budget_and_execution(self):
        payload, digest = self.propose()
        self.approve("task-sqlite-0001", payload, digest)
        self.cp.activate_kill_switch()
        self.assertTrue(self.cp.kill_switch_active())
        with self.assertRaises(BudgetError):
            self.cp.reserve_budget("task-sqlite-0001", 1)
        with self.assertRaises(StateError):
            self.cp.transition("task-sqlite-0001", TaskState.EXECUTING)

    def test_kill_switch_remains_active_if_audit_write_fails(self):
        original = self.cp._append_audit
        def fail_audit(*args, **kwargs):
            raise AuditError("synthetic audit outage")
        self.cp._append_audit = fail_audit
        with self.assertRaises(AuditError):
            self.cp.activate_kill_switch()
        self.cp._append_audit = original
        self.assertTrue(self.cp.kill_switch_active())

    def test_audit_chain_verifies_and_append_only_triggers_block_mutation(self):
        self.propose()
        self.assertTrue(self.cp.verify_audit_chain())
        conn = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE audit_events SET event = 'tampered' WHERE sequence = 1")
        finally:
            conn.close()

    def test_audit_chain_detects_privileged_tampering(self):
        self.propose()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DROP TRIGGER audit_events_no_update")
            conn.execute("UPDATE audit_events SET details_json = '{}' WHERE sequence = 1")
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.cp.verify_audit_chain())

    def test_database_path_must_be_persistent_and_absolute(self):
        with self.assertRaises(ValueError):
            SQLiteControlPlane(":memory:", monthly_budget=1)
        with self.assertRaises(ValueError):
            SQLiteControlPlane("relative.sqlite3", monthly_budget=1)

    def test_database_file_is_created_with_private_permissions(self):
        self.assertEqual(stat.S_IMODE(self.db_path.stat().st_mode), 0o600)

    def test_existing_database_with_broad_permissions_is_rejected(self):
        unsafe_path = Path(self.temp.name) / "unsafe.sqlite3"
        unsafe_path.write_bytes(b"not a real database")
        unsafe_path.chmod(0o644)
        with self.assertRaises(ValueError):
            SQLiteControlPlane(unsafe_path, monthly_budget=1)

    def test_database_directory_with_broad_permissions_is_rejected(self):
        unsafe_dir = Path(self.temp.name) / "public-dir"
        unsafe_dir.mkdir(mode=0o755)
        unsafe_dir.chmod(0o755)
        with self.assertRaises(ValueError):
            SQLiteControlPlane(unsafe_dir / "store.sqlite3", monthly_budget=1)


if __name__ == "__main__":
    unittest.main()
