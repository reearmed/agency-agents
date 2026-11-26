"""Durable, mock-only execution worker built on the approval-grant SQLite ledger.

The approval grant and immutable execution intent are committed atomically.
A claimed dispatch is never automatically retried after a crash or timeout;
stale dispatches become UNKNOWN and require destination reconciliation.
No real adapters are supported.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Mapping
from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from execution_gateway import AdapterReceipt, MockOutcomeVerifier
from guardrails import canonical_json, payload_sha256


class DurableExecutionError(RuntimeError):
    """Fail-closed durable execution error."""


class SQLiteMockAdapter:
    """Synthetic destination whose receipts survive gateway/worker restarts."""

    def __init__(self, ledger: SQLiteGrantLedger, *, timeout_after_commit: bool = False,
                 fail_before_commit: bool = False):
        if timeout_after_commit and fail_before_commit:
            raise ValueError("choose one mock failure mode")
        self.ledger = ledger
        self.timeout_after_commit = timeout_after_commit
        self.fail_before_commit = fail_before_commit
        self.call_count = 0

    def execute(self, *, idempotency_key: str, operation: Mapping[str, Any]) -> AdapterReceipt:
        self.call_count += 1
        if self.fail_before_commit:
            raise RuntimeError("synthetic destination failure before commit")
        receipt = self.ledger.record_mock_destination_acceptance(idempotency_key, operation)
        result = AdapterReceipt(
            idempotency_key=receipt["idempotency_key"],
            operation_sha256=receipt["operation_sha256"],
            result=receipt["result"],
        )
        if self.timeout_after_commit:
            raise TimeoutError("synthetic timeout after durable destination acceptance")
        return result

    def lookup(self, idempotency_key: str) -> AdapterReceipt | None:
        receipt = self.ledger.lookup_mock_destination_receipt(idempotency_key)
        if receipt is None:
            return None
        return AdapterReceipt(
            idempotency_key=receipt["idempotency_key"],
            operation_sha256=receipt["operation_sha256"],
            result=receipt["result"],
        )


class DurableMockExecutionGateway:
    def __init__(self, *, authority: ApprovalGrantAuthority, ledger: SQLiteGrantLedger,
                 adapter: SQLiteMockAdapter, verifier: MockOutcomeVerifier, kill_switch_check):
        if type(adapter) is not SQLiteMockAdapter or type(verifier) is not MockOutcomeVerifier:
            raise TypeError("the durable gateway requires the explicit SQLite mock destination and mock verifier")
        if not callable(kill_switch_check):
            raise ValueError("kill_switch_check callback is required")
        if authority._ledger is not ledger:
            raise ValueError("authority and execution gateway must share the same SQLite ledger")
        self.authority = authority
        self.ledger = ledger
        self.adapter = adapter
        self.verifier = verifier
        self.kill_switch_check = kill_switch_check

    def submit(self, token: str, *, task_id: str, payload: Mapping[str, Any],
               adapter_name: str, action: str, target: str, idempotency_key: str,
               requester_id: str) -> Mapping[str, Any]:
        if self.kill_switch_check() is not False:
            raise DurableExecutionError("kill switch active or unavailable; execution denied")
        grant_id = self._grant_id_from_token(token)
        intent = {
            "intent_id": grant_id,
            "task_id": task_id,
            "idempotency_key": idempotency_key,
            "operation_json": canonical_json(dict(payload)).decode("utf-8"),
            "operation_sha256": payload_sha256(payload),
            "adapter": adapter_name,
            "action": action,
            "target": target,
        }
        if "_budget" in payload:
            intent["budget_reservation"] = payload["_budget"]
        try:
            self.authority.verify_and_consume(
                token, task_id=task_id, payload=payload, adapter=adapter_name,
                action=action, target=target, idempotency_key=idempotency_key,
                requester_id=requester_id, execution_intent=intent,
            )
        except GrantError as exc:
            # The authority validates the intent against the signed grant and
            # commits grant consumption + durable intent in one transaction.
            raise DurableExecutionError("approval or durable intent rejected") from exc
        return self.dispatch_ready(grant_id, worker_id="submitter")

    @staticmethod
    def _grant_id_from_token(token: str) -> str:
        """Extract a bounded routing hint; cryptographic validation happens separately.

        The returned ID is untrusted until ApprovalGrantAuthority verifies the
        HMAC, schema, expiry and exact request scope. Strict bounds and decoding
        here prevent malformed input from escaping as parser exceptions or
        causing unbounded work before that verification.
        """
        if not isinstance(token, str) or len(token) > 16449 or token.count(".") != 1:
            raise DurableExecutionError("malformed approval grant")
        encoded, signature = token.split(".", 1)
        if not encoded or len(encoded) > 16384 or len(signature) != 64:
            raise DurableExecutionError("malformed approval grant")
        if any(char not in "0123456789abcdef" for char in signature):
            raise DurableExecutionError("malformed approval grant")
        try:
            raw = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4),
                altchars=b"-_",
                validate=True,
            )
            grant = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DurableExecutionError("malformed approval grant") from exc
        if not isinstance(grant, dict) or grant.get("version") != 1:
            raise DurableExecutionError("malformed approval grant")
        grant_id = grant.get("grant_id")
        if (
            not isinstance(grant_id, str)
            or not 16 <= len(grant_id) <= 128
            or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in grant_id)
        ):
            raise DurableExecutionError("malformed approval grant")
        return grant_id

    def dispatch_ready(self, intent_id: str, *, worker_id: str) -> Mapping[str, Any]:
        if self.kill_switch_check() is not False:
            raise DurableExecutionError("kill switch active or unavailable; worker dispatch denied")
        try:
            intent = self.ledger.claim_intent(intent_id, worker_id)
        except GrantError as exc:
            raise DurableExecutionError(str(exc)) from exc
        operation = json.loads(intent["operation_json"])
        if self.kill_switch_check() is not False or self.ledger.kill_switch_active():
            self.ledger.update_intent(
                intent_id, expected_state="DISPATCHING", new_state="UNKNOWN",
                error="persistent kill switch activated after claim; reconcile destination before any further action",
            )
            result = self.ledger.get_intent(intent_id)
            if result is None:
                raise DurableExecutionError("execution intent disappeared")
            return result
        try:
            receipt = self.adapter.execute(
                idempotency_key=intent["idempotency_key"], operation=operation
            )
        except Exception as exc:
            self.ledger.update_intent(
                intent_id, expected_state="DISPATCHING", new_state="UNKNOWN",
                error=f"adapter outcome ambiguous ({type(exc).__name__}); reconcile before retry",
            )
        else:
            receipt_json = json.dumps({
                "idempotency_key": receipt.idempotency_key,
                "operation_sha256": receipt.operation_sha256,
                "result": receipt.result,
            }, sort_keys=True, separators=(",", ":"))
            self.ledger.update_intent(
                intent_id, expected_state="DISPATCHING", new_state="VERIFY_PENDING",
                receipt_json=receipt_json,
            )
        result = self.ledger.get_intent(intent_id)
        if result is None:
            raise DurableExecutionError("execution intent disappeared")
        return result

    def recover_expired_dispatches(self) -> list[Mapping[str, Any]]:
        """Convert expired worker claims to UNKNOWN and return work requiring reconciliation."""
        self.ledger.recover_stale_dispatches()
        return self.ledger.list_reconcilable_intents()

    def recover_ready(self, *, worker_id: str) -> list[Mapping[str, Any]]:
        recovered = []
        for intent in self.ledger.list_ready_intents():
            try:
                recovered.append(self.dispatch_ready(intent["intent_id"], worker_id=worker_id))
            except DurableExecutionError:
                current = self.ledger.get_intent(intent["intent_id"])
                # Another worker may have won the atomic claim. Skip only when
                # the intent is no longer READY; otherwise preserve fail-closed
                # behavior for kill-switch or infrastructure failures.
                if current is not None and current["state"] != "READY":
                    continue
                raise
        return recovered

    def reconcile(self, intent_id: str) -> Mapping[str, Any]:
        intent = self.ledger.get_intent(intent_id)
        if intent is None or intent["state"] not in {"UNKNOWN", "VERIFY_PENDING"}:
            raise DurableExecutionError("intent is not awaiting reconciliation")
        operation = json.loads(intent["operation_json"])
        receipt = self.adapter.lookup(intent["idempotency_key"])
        verification = self.verifier.verify(receipt=receipt, expected_operation=operation)
        if verification.outcome.value not in {"succeeded", "failed"}:
            raise DurableExecutionError("verifier returned a non-terminal outcome")
        state = "SUCCEEDED" if verification.outcome.value == "succeeded" else "FAILED"
        receipt_json = None
        if receipt is not None:
            receipt_json = json.dumps({
                "idempotency_key": receipt.idempotency_key,
                "operation_sha256": receipt.operation_sha256,
                "result": receipt.result,
            }, sort_keys=True, separators=(",", ":"))
        self.ledger.update_intent(
            intent_id, expected_state=intent["state"], new_state=state,
            receipt_json=receipt_json, evidence_sha256=verification.evidence_sha256,
            error=None,
        )
        final = self.ledger.get_intent(intent_id)
        if final is None:
            raise DurableExecutionError("execution intent disappeared after verification")
        return final
