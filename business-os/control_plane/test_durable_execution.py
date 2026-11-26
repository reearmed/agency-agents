import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from durable_execution import DurableExecutionError, DurableMockExecutionGateway
from execution_gateway import MockAdapter, MockOutcomeVerifier


class DurableExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "ledger.sqlite3"
        self.ledger = SQLiteGrantLedger(self.db)
        self.authority = ApprovalGrantAuthority(
            signing_key=b"k" * 32, ledger=self.ledger,
            identity_verifier=lambda actor, context: context == "authenticated-test-session",
        )
        self.adapter = MockAdapter()
        self.verifier = MockOutcomeVerifier()
        self.enabled = False
        self.gateway = DurableMockExecutionGateway(
            authority=self.authority, ledger=self.ledger, adapter=self.adapter,
            verifier=self.verifier, kill_switch_check=lambda: self.enabled,
        )
        self.payload = {"body": "synthetic only", "amount": 0}
        self.token = self.issue()

    def tearDown(self):
        self.temp.cleanup()

    def issue(self, *, payload=None, task_id="task-1", key="idem-1"):
        return self.authority.issue(
            task_id=task_id, payload=payload or self.payload,
            adapter="mock", action="create", target="sandbox-object",
            idempotency_key=key, requester_id="agent-1", approver_id="human-1",
            auth_context="authenticated-test-session", ttl_seconds=300,
        )

    def submit(self, token=None):
        return self.gateway.submit(
            token or self.token, task_id="task-1", payload=self.payload,
            adapter_name="mock", action="create", target="sandbox-object",
            idempotency_key="idem-1", requester_id="agent-1",
        )

    def test_grant_consumption_and_intent_are_atomic_and_durable(self):
        result = self.submit()
        self.assertEqual(result["state"], "VERIFY_PENDING")
        reopened = SQLiteGrantLedger(self.db)
        intent = reopened.get_intent(result["intent_id"])
        self.assertEqual(intent["state"], "VERIFY_PENDING")
        self.assertEqual(intent["operation_json"], json.dumps(self.payload, sort_keys=True, separators=(",", ":")))

    def test_ready_intent_recovers_after_crash_before_worker_claim(self):
        grant_id = self.gateway._grant_id_from_token(self.token)
        from guardrails import canonical_json, payload_sha256
        self.authority.verify_and_consume(
            self.token, task_id="task-1", payload=self.payload, adapter="mock",
            action="create", target="sandbox-object", idempotency_key="idem-1",
            requester_id="agent-1",
            execution_intent={
                "intent_id": grant_id, "task_id": "task-1", "idempotency_key": "idem-1",
                "operation_json": canonical_json(self.payload).decode(),
                "operation_sha256": payload_sha256(self.payload), "adapter": "mock",
                "action": "create", "target": "sandbox-object",
            },
        )
        self.assertEqual(len(self.gateway.recover_ready(worker_id="recovery-worker")), 1)
        self.assertEqual(self.adapter.call_count, 1)

    def test_timeout_after_destination_commit_reconciles_to_success(self):
        self.gateway.adapter = MockAdapter(timeout_after_commit=True)
        result = self.submit()
        self.assertEqual(result["state"], "UNKNOWN")
        final = self.gateway.reconcile(result["intent_id"])
        self.assertEqual(final["state"], "SUCCEEDED")
        self.assertTrue(final["evidence_sha256"])

    def test_failure_before_destination_commit_reconciles_to_failed(self):
        self.gateway.adapter = MockAdapter(fail_before_commit=True)
        result = self.submit()
        self.assertEqual(result["state"], "UNKNOWN")
        final = self.gateway.reconcile(result["intent_id"])
        self.assertEqual(final["state"], "FAILED")

    def test_expired_dispatch_lease_becomes_unknown_and_is_not_retried(self):
        result = self.submit()
        intent_id = result["intent_id"]
        # Simulate a worker crash after claiming but before contacting destination.
        self.gateway.ledger.update_intent(
            intent_id, expected_state="VERIFY_PENDING", new_state="UNKNOWN",
            error="synthetic crash recovery setup",
        )
        conn = sqlite3.connect(self.db)
        try:
            conn.execute(
                "UPDATE execution_intents SET state='READY', lease_owner=NULL, lease_expires_at=NULL WHERE intent_id=?",
                (intent_id,),
            )
            conn.commit()
        finally:
            conn.close()
        claimed = self.ledger.claim_intent(intent_id, "worker-crashed", lease_seconds=1)
        self.assertEqual(claimed["state"], "DISPATCHING")
        conn = sqlite3.connect(self.db)
        try:
            past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            conn.execute("UPDATE execution_intents SET lease_expires_at=? WHERE intent_id=?", (past, intent_id))
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(GrantError):
            self.ledger.claim_intent(intent_id, "second-worker", lease_seconds=1)
        self.assertEqual(self.ledger.get_intent(intent_id)["state"], "UNKNOWN")
        self.assertEqual(self.adapter.call_count, 1)

    def test_duplicate_intent_idempotency_key_rejected(self):
        first = self.submit()
        second_token = self.issue(task_id="task-2", key="idem-1")
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                second_token, task_id="task-2", payload=self.payload, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="idem-1",
                requester_id="agent-1",
            )
        self.assertEqual(self.adapter.call_count, 1)

    def test_kill_switch_prevents_grant_consumption(self):
        self.enabled = True
        with self.assertRaises(DurableExecutionError):
            self.submit()
        self.assertEqual(self.ledger.list_ready_intents(), [])
        self.assertEqual(self.adapter.call_count, 0)

    def test_payload_substitution_rejected_before_intent_creation(self):
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                self.token, task_id="task-1", payload={"body": "changed"},
                adapter_name="mock", action="create", target="sandbox-object",
                idempotency_key="idem-1", requester_id="agent-1",
            )
        self.assertEqual(self.ledger.list_ready_intents(), [])
        self.assertEqual(self.adapter.call_count, 0)

    def test_execution_audit_chain_verifies_and_is_append_only(self):
        result = self.submit()
        self.assertTrue(self.ledger.verify_execution_audit_chain())
        conn = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM execution_events")
        finally:
            conn.close()
        self.assertTrue(self.ledger.verify_execution_audit_chain())

    def test_concurrent_workers_cannot_claim_the_same_ready_intent(self):
        from guardrails import canonical_json, payload_sha256
        grant_id = self.gateway._grant_id_from_token(self.token)
        self.authority.verify_and_consume(
            self.token, task_id="task-1", payload=self.payload, adapter="mock",
            action="create", target="sandbox-object", idempotency_key="idem-1",
            requester_id="agent-1",
            execution_intent={
                "intent_id": grant_id, "task_id": "task-1", "idempotency_key": "idem-1",
                "operation_json": canonical_json(self.payload).decode(),
                "operation_sha256": payload_sha256(self.payload), "adapter": "mock",
                "action": "create", "target": "sandbox-object",
            },
        )
        from concurrent.futures import ThreadPoolExecutor
        def claim(worker):
            try:
                self.ledger.claim_intent(grant_id, worker)
                return "claimed"
            except GrantError:
                return "denied"
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, ["worker-a", "worker-b"]))
        self.assertEqual(outcomes.count("claimed"), 1)
        self.assertEqual(outcomes.count("denied"), 1)

    def test_real_adapter_rejected(self):
        class FakeAdapter:
            pass
        with self.assertRaises(TypeError):
            DurableMockExecutionGateway(
                authority=self.authority, ledger=self.ledger, adapter=FakeAdapter(),
                verifier=self.verifier, kill_switch_check=lambda: False,
            )


if __name__ == "__main__":
    unittest.main()
