import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from guardrails import (Approval, ApprovalError, AuditError, BudgetError,
                        InMemoryControlPlane, StateError, TaskState, canonical_json,
                        payload_sha256)


def approval_for(task_id, digest, **overrides):
    values = dict(approval_id="approval-000001", task_id=task_id,
                  payload_sha256=digest, approver_id="human-operator",
                  decision="approved", approved_at="2026-11-26T12:00:00Z",
                  expires_at="2026-11-26T12:10:00Z", adapter="email",
                  action="send", target="recipient@example.invalid")
    values.update(overrides)
    return Approval(**values)


class CanonicalizationTests(unittest.TestCase):
    def test_object_key_order_does_not_change_hash(self):
        self.assertEqual(payload_sha256({"a": 1, "b": 2}), payload_sha256({"b": 2, "a": 1}))

    def test_unicode_is_stable(self):
        self.assertEqual(canonical_json({"word": "café"}), '{"word":"café"}'.encode())

    def test_non_finite_numbers_rejected(self):
        with self.assertRaises(ValueError):
            canonical_json({"amount": float("nan")})


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.cp = InMemoryControlPlane(25)
        self.task = "task-000001"
        self.payload = {"body": "Exact approved body", "recipient": "recipient@example.invalid"}
        self.digest = self.cp.propose(self.task, self.payload)
        self.scope = {"adapter": "email", "action": "send", "target": "recipient@example.invalid"}
        self.now = datetime(2026, 11, 26, 12, 5, tzinfo=timezone.utc)

    def approve(self, approval=None, payload=None, scope=None, human=True, task=None, now=None):
        return self.cp.approve(task_id=task or self.task, payload=payload or self.payload,
            approval=approval or approval_for(self.task, self.digest),
            expected_scope=scope or self.scope, human_approver=human, now=now or self.now)

    def test_exact_human_approval_succeeds(self):
        self.approve()
        self.assertEqual(self.cp.states[self.task], TaskState.APPROVED)

    def test_agent_cannot_self_approve(self):
        with self.assertRaises(ApprovalError):
            self.approve(human=False)

    def test_payload_mutation_is_rejected(self):
        with self.assertRaises(ApprovalError):
            self.approve(payload={**self.payload, "body": "Changed after approval"})

    def test_forged_approval_for_replacement_payload_is_rejected(self):
        replacement = {**self.payload, "body": "Replacement payload"}
        forged = approval_for(self.task, payload_sha256(replacement))
        with self.assertRaises(ApprovalError):
            self.approve(approval=forged, payload=replacement)

    def test_recipient_swap_is_rejected(self):
        with self.assertRaises(ApprovalError):
            self.approve(scope={**self.scope, "target": "attacker@example.invalid"})

    def test_expired_approval_is_rejected(self):
        with self.assertRaises(ApprovalError):
            self.approve(now=datetime(2026, 11, 26, 12, 11, tzinfo=timezone.utc))

    def test_replayed_approval_is_rejected(self):
        approval = approval_for(self.task, self.digest)
        self.approve(approval=approval)
        self.cp.transition(self.task, TaskState.BLOCKED)
        other = "task-000002"
        self.cp.propose(other, self.payload)
        with self.assertRaises(ApprovalError):
            self.approve(approval=approval, task=other)

    def test_future_approval_timestamp_is_rejected(self):
        with self.assertRaises(ApprovalError):
            self.approve(approval=approval_for(self.task, self.digest,
                approved_at="2026-11-26T12:06:00Z"))


class OperationalGuardTests(unittest.TestCase):
    def test_illegal_transition_rejected(self):
        cp = InMemoryControlPlane(10)
        cp.propose("task-000001", {})
        with self.assertRaises(StateError):
            cp.transition("task-000001", TaskState.SUCCEEDED)

    def test_direct_transition_cannot_bypass_approval(self):
        cp = InMemoryControlPlane(10)
        cp.propose("task-000001", {})
        with self.assertRaises(StateError):
            cp.transition("task-000001", TaskState.APPROVED)

    def test_terminal_success_requires_independent_verification(self):
        cp = InMemoryControlPlane(10)
        cp.propose("task-000001", {})
        with self.assertRaises(StateError):
            cp.transition("task-000001", TaskState.SUCCEEDED)

    def test_unknown_adapter_outcome_can_be_reconciled_only_with_evidence(self):
        cp = InMemoryControlPlane(10)
        payload = {"operation": "synthetic"}
        digest = cp.propose("task-000001", payload)
        approval = approval_for("task-000001", digest)
        cp.approve(task_id="task-000001", payload=payload, approval=approval,
                   expected_scope={"adapter": "email", "action": "send",
                                   "target": "recipient@example.invalid"},
                   human_approver=True,
                   now=datetime(2026, 11, 26, 12, 5, tzinfo=timezone.utc))
        cp.transition("task-000001", TaskState.EXECUTING)
        cp.transition("task-000001", TaskState.UNKNOWN)
        with self.assertRaises(StateError):
            cp.record_verified_outcome("task-000001", TaskState.SUCCEEDED,
                                       verifier_id="verifier-1", evidence_sha256="invalid")
        cp.record_verified_outcome("task-000001", TaskState.SUCCEEDED,
                                   verifier_id="independent-verifier",
                                   evidence_sha256="b" * 64)
        self.assertEqual(cp.states["task-000001"], TaskState.SUCCEEDED)

    def test_kill_switch_blocks_budget_and_approval(self):
        cp = InMemoryControlPlane(10)
        cp.propose("task-000001", {})
        cp.activate_kill_switch()
        with self.assertRaises(BudgetError):
            cp.reserve_budget("task-000001", 1)

    def test_budget_cap_is_hard(self):
        cp = InMemoryControlPlane(5)
        cp.reserve_budget("task-000001", 4)
        with self.assertRaises(BudgetError):
            cp.reserve_budget("task-000002", 2)

    def test_audit_failure_fails_closed(self):
        cp = InMemoryControlPlane(5, audit_available=False)
        with self.assertRaises(AuditError):
            cp.propose("task-000001", {})
        with self.assertRaises(AuditError):
            cp.reserve_budget("task-000001", 1)

    def test_kill_switch_engages_even_if_audit_is_unavailable(self):
        cp = InMemoryControlPlane(5, audit_available=False)
        with self.assertRaises(AuditError):
            cp.activate_kill_switch()
        self.assertTrue(cp.kill_switch)
        with self.assertRaises(BudgetError):
            cp.reserve_budget("task-000001", 1)

    def test_idempotency_claim_is_atomic_under_race(self):
        cp = InMemoryControlPlane(5)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: cp.claim_idempotency("same-key-123456", "task-000001"), range(50)))
        self.assertEqual(sum(results), 1)

    def test_idempotency_key_cannot_be_reassigned(self):
        cp = InMemoryControlPlane(5)
        cp.claim_idempotency("same-key-123456", "task-000001")
        with self.assertRaises(Exception):
            cp.claim_idempotency("same-key-123456", "task-000002")


if __name__ == "__main__":
    unittest.main()
