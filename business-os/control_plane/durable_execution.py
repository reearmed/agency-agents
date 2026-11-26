"""Durable, mock-only execution worker built on the approval-grant SQLite ledger.

The approval grant and immutable execution intent are committed atomically.
A claimed dispatch is never automatically retried after a crash or timeout;
stale dispatches become UNKNOWN and require destination reconciliation.
No real adapters are supported.
"""
from __future__ import annotations

import json
from typing import Any, Mapping
from approval_grants import ApprovalGrantAuthority, GrantError, SQLiteGrantLedger
from execution_gateway import MockAdapter, MockOutcomeVerifier


class DurableExecutionError(RuntimeError):
    """Fail-closed durable execution error."""


class DurableMockExecutionGateway:
    def __init__(self, *, authority: ApprovalGrantAuthority, ledger: SQLiteGrantLedger,
                 adapter: MockAdapter, verifier: MockOutcomeVerifier, kill_switch_check):
        if type(adapter) is not MockAdapter or type(verifier) is not MockOutcomeVerifier:
            raise TypeError("only the explicit mock adapter and mock verifier are supported")
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
        try:
            self.authority.verify_and_consume(
                token, task_id=task_id, payload=payload, adapter=adapter_name,
                action=action, target=target, idempotency_key=idempotency_key,
                requester_id=requester_id,
                execution_intent={"intent_id": "", "task_id": task_id,
                    "idempotency_key": idempotency_key, "operation_json": "",
                    "operation_sha256": "", "adapter": adapter_name,
                    "action": action, "target": target},
            )
        except GrantError as exc:
            # The authority validates the intent against the signed grant and
            # commits grant consumption + durable intent in one transaction.
            raise DurableExecutionError("approval or durable intent rejected") from exc
        grant = self._grant_id_from_token(token)
        return self.dispatch_ready(grant, worker_id="submitter")

    @staticmethod
    def _grant_id_from_token(token: str) -> str:
        import base64
        encoded = token.split(".", 1)[0]
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        return json.loads(raw.decode("utf-8"))["grant_id"]

    def dispatch_ready(self, intent_id: str, *, worker_id: str) -> Mapping[str, Any]:
        try:
            intent = self.ledger.claim_intent(intent_id, worker_id)
        except GrantError as exc:
            raise DurableExecutionError(str(exc)) from exc
        operation = json.loads(intent["operation_json"])
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

    def recover_ready(self, *, worker_id: str) -> list[Mapping[str, Any]]:
        recovered = []
        for intent in self.ledger.list_ready_intents():
            recovered.append(self.dispatch_ready(intent["intent_id"], worker_id=worker_id))
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
