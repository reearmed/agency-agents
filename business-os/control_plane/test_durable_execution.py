import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from durable_execution import DurableExecutionError, DurableMockExecutionGateway, SQLiteMockAdapter
from execution_gateway import MockOutcomeVerifier


class DurableExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "ledger.sqlite3"
        self.ledger = SQLiteGrantLedger(self.db)
        self.authority = ApprovalGrantAuthority(
            signing_key=b"k" * 32, ledger=self.ledger,
            identity_verifier=lambda actor, context: context == "authenticated-test-session",
        )
        self.adapter = SQLiteMockAdapter(self.ledger)
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
        self.gateway.adapter = SQLiteMockAdapter(self.ledger, timeout_after_commit=True)
        result = self.submit()
        self.assertEqual(result["state"], "UNKNOWN")
        final = self.gateway.reconcile(result["intent_id"])
        self.assertEqual(final["state"], "SUCCEEDED")
        self.assertTrue(final["evidence_sha256"])

    def test_failure_before_destination_commit_reconciles_to_failed(self):
        self.gateway.adapter = SQLiteMockAdapter(self.ledger, fail_before_commit=True)
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
        reconcilable = self.gateway.recover_expired_dispatches()
        self.assertEqual(len(reconcilable), 1)
        self.assertEqual(self.ledger.get_intent(intent_id)["state"], "UNKNOWN")
        self.assertEqual(self.adapter.call_count, 1)

    def test_one_task_cannot_create_two_distinct_execution_intents(self):
        self.submit()
        second_token = self.issue(task_id="task-1", key="idem-2")
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                second_token, task_id="task-1", payload=self.payload, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="idem-2",
                requester_id="agent-1",
            )
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

    def test_persistent_kill_switch_blocks_new_approval_grants(self):
        self.ledger.activate_kill_switch()
        with self.assertRaises(GrantError):
            self.issue(task_id="task-paused", key="idem-paused")

    def test_persistent_kill_switch_blocks_intent_creation(self):
        self.ledger.activate_kill_switch()
        self.assertTrue(self.ledger.kill_switch_active())
        with self.assertRaises(DurableExecutionError):
            self.submit()
        self.assertEqual(self.ledger.list_ready_intents(), [])
        self.assertTrue(self.ledger.verify_execution_audit_chain())
        self.assertEqual(self.adapter.call_count, 0)

    def test_durable_destination_receipt_survives_gateway_restart(self):
        from approval_grants import ApprovalGrantAuthority, SQLiteGrantLedger
        from durable_execution import SQLiteMockAdapter
        self.gateway.adapter = SQLiteMockAdapter(self.ledger, timeout_after_commit=True)
        result = self.submit()
        self.assertEqual(result["state"], "UNKNOWN")
        restarted_ledger = SQLiteGrantLedger(self.db)
        restarted_authority = ApprovalGrantAuthority(
            signing_key=b"k" * 32, ledger=restarted_ledger,
            identity_verifier=lambda actor, context: context == "authenticated-test-session",
        )
        restarted_adapter = SQLiteMockAdapter(restarted_ledger)
        restarted_gateway = DurableMockExecutionGateway(
            authority=restarted_authority, ledger=restarted_ledger,
            adapter=restarted_adapter, verifier=MockOutcomeVerifier(),
            kill_switch_check=lambda: False,
        )
        final = restarted_gateway.reconcile(result["intent_id"])
        self.assertEqual(final["state"], "SUCCEEDED")
        self.assertEqual(restarted_adapter.call_count, 0)

    def test_persistent_kill_switch_blocks_destination_acceptance(self):
        from durable_execution import SQLiteMockAdapter
        adapter = SQLiteMockAdapter(self.ledger)
        self.ledger.activate_kill_switch()
        with self.assertRaises(GrantError):
            adapter.execute(idempotency_key="blocked-key", operation={"amount": 1})
        self.assertIsNone(self.ledger.lookup_mock_destination_receipt("blocked-key"))

    def test_durable_destination_idempotent_replay_returns_original_receipt(self):
        from durable_execution import SQLiteMockAdapter
        adapter = SQLiteMockAdapter(self.ledger)
        first = adapter.execute(idempotency_key="stable-key", operation={"amount": 1})
        second = adapter.execute(idempotency_key="stable-key", operation={"amount": 1})
        self.assertEqual(first, second)
        self.assertEqual(
            self.ledger.lookup_mock_destination_receipt("stable-key")["operation_sha256"],
            first.operation_sha256,
        )

    def test_persistent_destination_rejects_idempotency_key_payload_swap(self):
        from durable_execution import SQLiteMockAdapter
        adapter = SQLiteMockAdapter(self.ledger)
        adapter.execute(idempotency_key="dest-key", operation={"amount": 1})
        with self.assertRaises(GrantError):
            adapter.execute(idempotency_key="dest-key", operation={"amount": 2})

    def test_unavailable_external_kill_switch_blocks_dispatch_before_claim(self):
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
        self.gateway.kill_switch_check = lambda: None
        with self.assertRaises(DurableExecutionError):
            self.gateway.dispatch_ready(grant_id, worker_id="worker")
        self.assertEqual(self.ledger.get_intent(grant_id)["state"], "READY")
        self.assertEqual(self.adapter.call_count, 0)

    def test_kill_switch_activated_after_claim_prevents_destination_call(self):
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
        original_claim = self.ledger.claim_intent
        def claim_then_stop(*args, **kwargs):
            claimed = original_claim(*args, **kwargs)
            self.ledger.activate_kill_switch()
            return claimed
        self.ledger.claim_intent = claim_then_stop
        result = self.gateway.dispatch_ready(grant_id, worker_id="worker")
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(self.adapter.call_count, 0)

    def test_persistent_kill_switch_blocks_worker_claim(self):
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
        self.ledger.activate_kill_switch()
        with self.assertRaises(GrantError):
            self.ledger.claim_intent(grant_id, "worker")
        self.assertEqual(self.adapter.call_count, 0)

    def test_kill_switch_stays_active_if_its_audit_write_fails(self):
        original = self.ledger._append_execution_event
        def fail(*args, **kwargs):
            raise RuntimeError("synthetic audit outage")
        self.ledger._append_execution_event = fail
        with self.assertRaises(RuntimeError):
            self.ledger.activate_kill_switch()
        self.ledger._append_execution_event = original
        self.assertTrue(self.ledger.kill_switch_active())

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
        self.assertTrue(self.ledger.verify_execution_integrity())
        conn = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM execution_events")
        finally:
            conn.close()
        self.assertTrue(self.ledger.verify_execution_audit_chain())

    def test_intent_proposal_fields_are_immutable_and_undeletable(self):
        result = self.submit()
        conn = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE execution_intents SET operation_json='{}' WHERE intent_id=?",
                    (result["intent_id"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM execution_intents WHERE intent_id=?", (result["intent_id"],))
        finally:
            conn.close()
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_privileged_intent_payload_tampering_is_detected(self):
        result = self.submit()
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER execution_intents_immutable_fields")
            conn.execute(
                "UPDATE execution_intents SET operation_json=? WHERE intent_id=?",
                ('{"body":"tampered"}', result["intent_id"]),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_integrity())

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
