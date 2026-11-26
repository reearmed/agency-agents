import json
import sqlite3
import stat
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

    def test_persistent_kill_switch_blocks_grant_consumption_without_outbox(self):
        self.ledger.activate_kill_switch()
        with self.assertRaises(GrantError):
            self.authority.verify_and_consume(
                self.token, task_id="task-1", payload=self.payload, adapter="mock",
                action="create", target="sandbox-object", idempotency_key="idem-1",
                requester_id="agent-1",
            )

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

    def test_private_backup_restores_outbox_destination_and_kill_switch(self):
        result = self.submit()
        self.ledger.activate_kill_switch()
        backup = Path(self.temp.name) / "backup.sqlite3"
        created = self.ledger.backup_to(backup)
        restored = SQLiteGrantLedger(created)
        intent = restored.get_intent(result["intent_id"])
        self.assertEqual(intent["state"], "VERIFY_PENDING")
        self.assertTrue(restored.kill_switch_active())
        self.assertIsNotNone(restored.lookup_mock_destination_receipt("idem-1"))
        self.assertTrue(restored.verify_execution_audit_chain())
        self.assertTrue(restored.verify_execution_integrity())
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)

    def test_budget_reservation_is_atomic_with_intent_and_settlement(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=800, currency="USD",
        )
        payload = {
            **self.payload,
            "_budget": {
                "reservation_id": "budget-res-1",
                "amount_minor": 700,
                "currency": "USD",
                "period": "2026-11",
            },
        }
        token = self.issue(payload=payload, task_id="budget-task-1", key="budget-idem-1")
        result = self.gateway.submit(
            token, task_id="budget-task-1", payload=payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-idem-1",
            requester_id="agent-1",
        )
        with self.assertRaises(GrantError):
            self.ledger.settle_budget("budget-task-1", 650)
        self.assertEqual(self.gateway.reconcile(result["intent_id"])["state"], "SUCCEEDED")
        usage = self.ledger.budget_usage("2026-11")
        self.assertEqual(usage["reserved_minor"], 700)
        self.assertEqual(usage["remaining_minor"], 300)
        self.assertEqual(result["state"], "VERIFY_PENDING")
        self.ledger.settle_budget("budget-task-1", 650)
        usage = self.ledger.budget_usage("2026-11")
        self.assertEqual(usage["reserved_minor"], 0)
        self.assertEqual(usage["settled_minor"], 650)
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_concurrent_budget_reservations_cannot_exceed_monthly_cap(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=700, currency="USD",
        )
        cases = []
        for index in (1, 2):
            payload = {
                **self.payload,
                "_budget": {
                    "reservation_id": f"concurrent-res-{index}",
                    "amount_minor": 600,
                    "currency": "USD",
                    "period": "2026-11",
                },
            }
            token = self.issue(payload=payload, task_id=f"concurrent-task-{index}", key=f"concurrent-key-{index}")
            cases.append((token, payload, index))
        def submit(case):
            token, payload, index = case
            try:
                return self.gateway.submit(
                    token, task_id=f"concurrent-task-{index}", payload=payload,
                    adapter_name="mock", action="create", target="sandbox-object",
                    idempotency_key=f"concurrent-key-{index}", requester_id="agent-1",
                )["state"]
            except DurableExecutionError:
                return "DENIED"
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, cases))
        self.assertEqual(results.count("VERIFY_PENDING"), 1)
        self.assertEqual(results.count("DENIED"), 1)
        self.assertEqual(self.ledger.budget_usage("2026-11")["used_minor"], 600)
        self.assertEqual(self.adapter.call_count, 1)
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_monthly_budget_hard_stop_rolls_back_grant_and_intent(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=800, currency="USD",
        )
        first_payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-1", "amount_minor": 700, "currency": "USD", "period": "2026-11"},
        }
        first_token = self.issue(payload=first_payload, task_id="budget-task-1", key="budget-idem-1")
        self.gateway.submit(
            first_token, task_id="budget-task-1", payload=first_payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-idem-1",
            requester_id="agent-1",
        )
        second_payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-2", "amount_minor": 400, "currency": "USD", "period": "2026-11"},
        }
        second_token = self.issue(payload=second_payload, task_id="budget-task-2", key="budget-idem-2")
        second_grant_id = self.gateway._grant_id_from_token(second_token)
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                second_token, task_id="budget-task-2", payload=second_payload, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="budget-idem-2",
                requester_id="agent-1",
            )
        self.assertIsNone(self.ledger.get_intent(second_grant_id))
        conn = sqlite3.connect(self.db)
        try:
            consumed = conn.execute(
                "SELECT 1 FROM consumed_grants WHERE grant_id=?", (second_grant_id,)
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(consumed)
        self.assertEqual(self.ledger.budget_usage("2026-11")["used_minor"], 700)
        self.assertEqual(self.adapter.call_count, 1)

    def test_budget_reservation_amount_is_bound_to_signed_payload(self):
        original = {
            **self.payload,
            "_budget": {"reservation_id": "res-bound", "amount_minor": 300, "currency": "USD", "period": "2026-11"},
        }
        changed = {
            **self.payload,
            "_budget": {"reservation_id": "res-bound", "amount_minor": 301, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=original, task_id="budget-bound", key="budget-bound-key")
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                token, task_id="budget-bound", payload=changed, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="budget-bound-key",
                requester_id="agent-1",
            )
        self.assertEqual(self.adapter.call_count, 0)
        self.assertIsNone(self.ledger.get_intent(self.gateway._grant_id_from_token(token)))

    def test_missing_budget_configuration_and_per_task_overage_fail_closed(self):
        payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-missing", "amount_minor": 100, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=payload, task_id="budget-missing", key="budget-missing-key")
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                token, task_id="budget-missing", payload=payload, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="budget-missing-key",
                requester_id="agent-1",
            )
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        over = {
            **self.payload,
            "_budget": {"reservation_id": "res-over", "amount_minor": 600, "currency": "USD", "period": "2026-11"},
        }
        over_token = self.issue(payload=over, task_id="budget-over", key="budget-over-key")
        with self.assertRaises(DurableExecutionError):
            self.gateway.submit(
                over_token, task_id="budget-over", payload=over, adapter_name="mock",
                action="create", target="sandbox-object", idempotency_key="budget-over-key",
                requester_id="agent-1",
            )
        self.assertEqual(self.ledger.budget_usage("2026-11")["used_minor"], 0)
        self.assertEqual(self.adapter.call_count, 0)

    def test_budget_configuration_and_reservation_scope_are_immutable(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-immutable", "amount_minor": 300, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=payload, task_id="budget-immutable", key="budget-immutable-key")
        self.gateway.submit(
            token, task_id="budget-immutable", payload=payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-immutable-key",
            requester_id="agent-1",
        )
        conn = sqlite3.connect(self.db)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE execution_budget_limits SET monthly_limit_minor=9999 WHERE period='2026-11'"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "UPDATE execution_budget_reservations SET amount_minor=9999 WHERE task_id='budget-immutable'"
                )
        finally:
            conn.close()
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_privileged_budget_limit_tampering_is_detected(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER budget_limits_no_update")
            conn.execute(
                "UPDATE execution_budget_limits SET monthly_limit_minor=9999 WHERE period='2026-11'"
            )
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_integrity())

    def test_privileged_budget_reservation_tampering_is_detected(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-tamper", "amount_minor": 300, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=payload, task_id="budget-tamper", key="budget-tamper-key")
        self.gateway.submit(
            token, task_id="budget-tamper", payload=payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-tamper-key",
            requester_id="agent-1",
        )
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER budget_reservations_immutable_fields")
            conn.execute(
                "UPDATE execution_budget_reservations SET amount_minor=999 WHERE task_id='budget-tamper'"
            )
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_integrity())

    def test_budget_release_requires_verified_no_effect(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-release", "amount_minor": 300, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=payload, task_id="budget-release", key="budget-release-key")
        self.gateway.adapter = SQLiteMockAdapter(self.ledger, fail_before_commit=True)
        result = self.gateway.submit(
            token, task_id="budget-release", payload=payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-release-key",
            requester_id="agent-1",
        )
        self.assertEqual(result["state"], "UNKNOWN")
        self.assertEqual(self.gateway.reconcile(result["intent_id"])["state"], "FAILED")
        with self.assertRaises(GrantError):
            self.ledger.release_budget("budget-release", verified_no_effect=False)
        self.ledger.release_budget("budget-release", verified_no_effect=True)
        self.assertEqual(self.ledger.budget_usage("2026-11")["used_minor"], 0)
        self.assertEqual(self.ledger.get_budget_reservation("budget-release")["state"], "RELEASED")
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_budget_settlement_cannot_exceed_reserved_amount(self):
        self.ledger.configure_budget(
            period="2026-11", monthly_limit_minor=1000,
            per_task_limit_minor=500, currency="USD",
        )
        payload = {
            **self.payload,
            "_budget": {"reservation_id": "res-settle", "amount_minor": 300, "currency": "USD", "period": "2026-11"},
        }
        token = self.issue(payload=payload, task_id="budget-settle", key="budget-settle-key")
        result = self.gateway.submit(
            token, task_id="budget-settle", payload=payload, adapter_name="mock",
            action="create", target="sandbox-object", idempotency_key="budget-settle-key",
            requester_id="agent-1",
        )
        self.gateway.reconcile(result["intent_id"])
        with self.assertRaises(GrantError):
            self.ledger.settle_budget("budget-settle", 301)
        self.assertEqual(self.ledger.get_budget_reservation("budget-settle")["state"], "RESERVED")
        self.assertTrue(self.ledger.verify_execution_integrity())

    def test_backup_refuses_to_overwrite_existing_file(self):
        backup = Path(self.temp.name) / "existing-backup.sqlite3"
        backup.write_text("do not overwrite")
        with self.assertRaises(ValueError):
            self.ledger.backup_to(backup)
        self.assertEqual(backup.read_text(), "do not overwrite")

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

    def test_privileged_mock_destination_receipt_tampering_is_detected(self):
        self.submit()
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER mock_receipts_no_update")
            conn.execute(
                "UPDATE mock_destination_receipts SET operation_sha256=? WHERE idempotency_key=?",
                ("0" * 64, "idem-1"),
            )
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_integrity())

    def test_successful_intent_requires_persistent_destination_receipt(self):
        result = self.submit()
        self.assertEqual(self.gateway.reconcile(result["intent_id"])["state"], "SUCCEEDED")
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER mock_receipts_no_delete")
            conn.execute("DELETE FROM mock_destination_receipts WHERE idempotency_key='idem-1'")
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_integrity())

    def test_privileged_execution_audit_tampering_is_detected(self):
        self.submit()
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TRIGGER execution_events_no_update")
            conn.execute(
                "UPDATE execution_events SET details_json='{}' WHERE sequence=1"
            )
            conn.commit()
        finally:
            conn.close()
        self.assertFalse(self.ledger.verify_execution_audit_chain())

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

    def test_concurrent_worker_recovery_dispatches_ready_intent_once(self):
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
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda worker: self.gateway.recover_ready(worker_id=worker),
                ["recovery-a", "recovery-b"],
            ))
        self.assertEqual(sum(len(result) for result in results), 1)
        self.assertEqual(self.adapter.call_count, 1)

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
