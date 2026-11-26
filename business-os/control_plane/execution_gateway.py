"""Mock-only execution gateway for Business OS security testing.

No network, browser, email, payment, publishing, shell or repository adapter is
implemented here. The gateway deliberately accepts only MockAdapter instances.
It consumes a one-use approval grant before the simulated call. Timeouts become
UNKNOWN and must be reconciled; they are never retried automatically.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import threading
from typing import Any, Mapping

from approval_grants import ApprovalGrantAuthority, GrantError


class GatewayError(Exception):
    """Fail-closed execution gateway error."""


class ExecutionState(str, Enum):
    BLOCKED = "blocked"
    EXECUTING = "executing"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class AdapterReceipt:
    idempotency_key: str
    operation_sha256: str
    result: str


@dataclass(frozen=True)
class ExecutionRecord:
    task_id: str
    state: ExecutionState
    idempotency_key: str
    receipt: AdapterReceipt | None = None
    detail: str | None = None


@dataclass(frozen=True)
class Verification:
    outcome: ExecutionState
    evidence_sha256: str


class MockAdapter:
    """Synthetic adapter with deterministic idempotency and timeout simulation."""

    def __init__(self, *, timeout_after_commit: bool = False, fail_before_commit: bool = False):
        if timeout_after_commit and fail_before_commit:
            raise ValueError("choose one mock failure mode")
        self.timeout_after_commit = timeout_after_commit
        self.fail_before_commit = fail_before_commit
        self._receipts: dict[str, AdapterReceipt] = {}
        self._lock = threading.Lock()
        self.call_count = 0

    def execute(self, *, idempotency_key: str, operation: Mapping[str, Any]) -> AdapterReceipt:
        with self._lock:
            self.call_count += 1
            prior = self._receipts.get(idempotency_key)
            if prior:
                if prior.operation_sha256 != _digest(operation):
                    raise GatewayError("idempotency key reused for different operation")
                return prior
            if self.fail_before_commit:
                raise RuntimeError("synthetic adapter failure before commit")
            receipt = AdapterReceipt(
                idempotency_key=idempotency_key,
                operation_sha256=_digest(operation),
                result="mock-accepted",
            )
            self._receipts[idempotency_key] = receipt
            if self.timeout_after_commit:
                raise TimeoutError("synthetic timeout after destination accepted operation")
            return receipt

    def lookup(self, idempotency_key: str) -> AdapterReceipt | None:
        with self._lock:
            return self._receipts.get(idempotency_key)


class MockOutcomeVerifier:
    """Separate synthetic verifier; never executes or changes destination state."""

    def verify(self, *, receipt: AdapterReceipt | None,
               expected_operation: Mapping[str, Any]) -> Verification:
        expected_hash = _digest(expected_operation)
        if receipt is None:
            evidence = hashlib.sha256(("absent:" + expected_hash).encode()).hexdigest()
            return Verification(ExecutionState.FAILED, evidence)
        if receipt.operation_sha256 != expected_hash:
            evidence = hashlib.sha256(("mismatch:" + receipt.operation_sha256).encode()).hexdigest()
            return Verification(ExecutionState.FAILED, evidence)
        evidence = hashlib.sha256(
            (receipt.idempotency_key + ":" + receipt.operation_sha256 + ":" + receipt.result).encode()
        ).hexdigest()
        return Verification(ExecutionState.SUCCEEDED, evidence)


def _digest(value: Mapping[str, Any]) -> str:
    import json
    return hashlib.sha256(json.dumps(
        dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")).hexdigest()


class MockExecutionGateway:
    """A mock-only boundary between approval grants and a synthetic adapter."""

    def __init__(
        self,
        *,
        authority: ApprovalGrantAuthority,
        adapter: MockAdapter,
        verifier: MockOutcomeVerifier,
        kill_switch_check,
    ):
        if type(adapter) is not MockAdapter or type(verifier) is not MockOutcomeVerifier:
            raise TypeError("only the explicit mock adapter and mock verifier are supported")
        if not callable(kill_switch_check):
            raise ValueError("kill_switch_check callback is required")
        self._authority = authority
        self._adapter = adapter
        self._verifier = verifier
        self._kill_switch_check = kill_switch_check
        self._records: dict[str, ExecutionRecord] = {}
        self._operations: dict[str, Mapping[str, Any]] = {}
        self._lock = threading.RLock()

    def execute(
        self,
        token: str,
        *,
        task_id: str,
        payload: Mapping[str, Any],
        adapter_name: str,
        action: str,
        target: str,
        idempotency_key: str,
        requester_id: str,
    ) -> ExecutionRecord:
        with self._lock:
            if self._kill_switch_check() is not False:
                raise GatewayError("kill switch active or unavailable; execution denied")
            if task_id in self._records:
                raise GatewayError("task already submitted; reconcile existing state")
            if not isinstance(payload, Mapping):
                raise GatewayError("operation payload must be an object")
            try:
                self._authority.verify_and_consume(
                    token,
                    task_id=task_id,
                    payload=payload,
                    adapter=adapter_name,
                    action=action,
                    target=target,
                    idempotency_key=idempotency_key,
                    requester_id=requester_id,
                )
            except GrantError as exc:
                raise GatewayError("approval grant rejected; no adapter call made") from exc

            self._records[task_id] = ExecutionRecord(
                task_id, ExecutionState.EXECUTING, idempotency_key
            )
            self._operations[task_id] = dict(payload)
            try:
                receipt = self._adapter.execute(
                    idempotency_key=idempotency_key, operation=payload
                )
            except TimeoutError:
                record = ExecutionRecord(
                    task_id, ExecutionState.UNKNOWN, idempotency_key,
                    detail="adapter timeout; destination state must be independently reconciled",
                )
            except Exception as exc:
                record = ExecutionRecord(
                    task_id, ExecutionState.UNKNOWN, idempotency_key,
                    detail=f"adapter error; outcome requires reconciliation ({type(exc).__name__})",
                )
            else:
                record = ExecutionRecord(
                    task_id, ExecutionState.EXECUTING, idempotency_key, receipt=receipt,
                    detail="accepted by mock adapter; awaiting independent verification",
                )
            self._records[task_id] = record
            return record

    def reconcile(self, task_id: str) -> ExecutionRecord:
        with self._lock:
            prior = self._records.get(task_id)
            if prior is None or prior.state not in {
                ExecutionState.UNKNOWN, ExecutionState.EXECUTING
            }:
                raise GatewayError("task is not awaiting reconciliation")
            operation = self._operations[task_id]
            receipt = self._adapter.lookup(prior.idempotency_key)
            verification = self._verifier.verify(
                receipt=receipt, expected_operation=operation
            )
            if verification.outcome not in {ExecutionState.SUCCEEDED, ExecutionState.FAILED}:
                raise GatewayError("verifier returned a non-terminal or invalid outcome")
            if len(verification.evidence_sha256) != 64 or any(
                ch not in "0123456789abcdef" for ch in verification.evidence_sha256
            ):
                raise GatewayError("verifier evidence reference is invalid")
            record = ExecutionRecord(
                task_id, verification.outcome, prior.idempotency_key, receipt=receipt,
                detail="independently reconciled by mock verifier",
            )
            self._records[task_id] = record
            return record

    def get(self, task_id: str) -> ExecutionRecord | None:
        with self._lock:
            return self._records.get(task_id)
