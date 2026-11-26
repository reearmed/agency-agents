"""End-to-end synthetic smoke test for the local durable control-plane prototype."""
from __future__ import annotations

import tempfile
from pathlib import Path

from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from durable_execution import DurableMockExecutionGateway, SQLiteMockAdapter
from execution_gateway import MockOutcomeVerifier


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="business-os-e2e-") as temp:
        root = Path(temp)
        db_path = root / "ledger.sqlite3"
        ledger = SQLiteGrantLedger(db_path)
        authority = ApprovalGrantAuthority(
            signing_key=b"synthetic-e2e-key-material-32bytes!!",
            ledger=ledger,
            identity_verifier=lambda actor, context: context == "synthetic-authenticated-session",
        )
        gateway = DurableMockExecutionGateway(
            authority=authority,
            ledger=ledger,
            adapter=SQLiteMockAdapter(ledger),
            verifier=MockOutcomeVerifier(),
            kill_switch_check=lambda: False,
        )
        payload = {"operation": "synthetic-e2e", "amount": 0}
        token = authority.issue(
            task_id="synthetic-e2e-task",
            payload=payload,
            adapter="mock",
            action="create",
            target="isolated-synthetic-destination",
            idempotency_key="synthetic-e2e-idempotency",
            requester_id="synthetic-agent",
            approver_id="synthetic-human",
            auth_context="synthetic-authenticated-session",
            ttl_seconds=300,
        )
        pending = gateway.submit(
            token,
            task_id="synthetic-e2e-task",
            payload=payload,
            adapter_name="mock",
            action="create",
            target="isolated-synthetic-destination",
            idempotency_key="synthetic-e2e-idempotency",
            requester_id="synthetic-agent",
        )
        assert pending["state"] == "VERIFY_PENDING"

        # Recreate the ledger, authority and worker to prove destination receipts
        # and outbox state survive a process-style restart.
        restarted_ledger = SQLiteGrantLedger(db_path)
        restarted_authority = ApprovalGrantAuthority(
            signing_key=b"synthetic-e2e-key-material-32bytes!!",
            ledger=restarted_ledger,
            identity_verifier=lambda actor, context: context == "synthetic-authenticated-session",
        )
        restarted_gateway = DurableMockExecutionGateway(
            authority=restarted_authority,
            ledger=restarted_ledger,
            adapter=SQLiteMockAdapter(restarted_ledger),
            verifier=MockOutcomeVerifier(),
            kill_switch_check=lambda: False,
        )
        completed = restarted_gateway.reconcile(pending["intent_id"])
        assert completed["state"] == "SUCCEEDED"
        assert completed["evidence_sha256"]
        assert restarted_ledger.verify_execution_audit_chain()
        assert restarted_ledger.verify_execution_integrity()

        backup = root / "verified-backup.sqlite3"
        backup_path = restarted_ledger.backup_to(backup)
        restored = SQLiteGrantLedger(backup_path)
        assert restored.get_intent(pending["intent_id"])["state"] == "SUCCEEDED"
        assert restored.verify_execution_audit_chain()
        assert restored.verify_execution_integrity()

        restored.activate_kill_switch()
        try:
            restarted_authority.issue(
                task_id="paused-task",
                payload=payload,
                adapter="mock",
                action="create",
                target="isolated-synthetic-destination",
                idempotency_key="paused-idempotency",
                requester_id="synthetic-agent",
                approver_id="synthetic-human",
                auth_context="synthetic-authenticated-session",
            )
        except GrantError:
            pass
        else:
            raise AssertionError("persistent kill switch failed to block approval issuance")

    print("PASS synthetic durable execution, restart, reconciliation, backup and kill switch")


if __name__ == "__main__":
    main()
