"""Fail-closed reference primitives for approval-bound task execution.

No network clients or external adapters are present. In-memory stores are
strictly for deterministic local tests, not multi-process/production use.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import math
import threading
from typing import Any, Mapping


class GuardrailError(Exception):
    pass


class ApprovalError(GuardrailError):
    pass


class StateError(GuardrailError):
    pass


class BudgetError(GuardrailError):
    pass


class AuditError(GuardrailError):
    pass


class TaskState(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNKNOWN = "unknown"


_ALLOWED_TRANSITIONS = {
    TaskState.PROPOSED: {TaskState.BLOCKED},
    TaskState.APPROVED: {TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.EXECUTING: {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.UNKNOWN, TaskState.BLOCKED},
    TaskState.UNKNOWN: {TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED},
    TaskState.SUCCEEDED: set(), TaskState.BLOCKED: set(), TaskState.FAILED: set(),
}


def _reject_nonfinite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numbers are not canonical JSON")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("object keys must be strings")
            _reject_nonfinite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_nonfinite(item)


def canonical_json(value: Any) -> bytes:
    _reject_nonfinite(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(dict(payload))).hexdigest()


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Approval:
    approval_id: str
    task_id: str
    payload_sha256: str
    approver_id: str
    decision: str
    approved_at: str
    expires_at: str
    adapter: str
    action: str
    target: str


class InMemoryControlPlane:
    """Test-only state machine. It never invokes an adapter or external side effect."""

    def __init__(self, monthly_budget: float, audit_available: bool = True):
        if monthly_budget < 0 or not math.isfinite(monthly_budget):
            raise ValueError("monthly_budget must be finite and non-negative")
        self.monthly_budget = monthly_budget
        self.spent = 0.0
        self.audit_available = audit_available
        self.kill_switch = False
        self.states: dict[str, TaskState] = {}
        self.used_approvals: set[str] = set()
        self.idempotency: dict[str, str] = {}
        self.audit: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def _record(self, event: str, **details: Any) -> None:
        if not self.audit_available:
            raise AuditError("audit store unavailable; fail closed")
        self.audit.append({"event": event, **details})

    def propose(self, task_id: str, payload: Mapping[str, Any]) -> str:
        with self._lock:
            if task_id in self.states:
                raise StateError("task_id already exists")
            digest = payload_sha256(payload)
            self._record("task_proposed", task_id=task_id, payload_sha256=digest)
            self.states[task_id] = TaskState.PROPOSED
            return digest

    def approve(self, *, task_id: str, payload: Mapping[str, Any], approval: Approval,
                expected_scope: Mapping[str, str], human_approver: bool = False,
                now: datetime | None = None) -> None:
        with self._lock:
            if self.kill_switch:
                raise ApprovalError("kill switch active")
            if self.states.get(task_id) is not TaskState.PROPOSED:
                raise StateError("task is not awaiting approval")
            if not human_approver:
                raise ApprovalError("authenticated human approval required")
            if approval.decision != "approved" or not approval.approver_id:
                raise ApprovalError("approval missing or rejected")
            if approval.task_id != task_id:
                raise ApprovalError("approval task mismatch")
            if approval.payload_sha256 != payload_sha256(payload):
                raise ApprovalError("approved payload hash mismatch")
            if approval.approval_id in self.used_approvals:
                raise ApprovalError("approval replay detected")
            actual_scope = {"adapter": approval.adapter, "action": approval.action,
                            "target": approval.target}
            if dict(expected_scope) != actual_scope:
                raise ApprovalError("approval scope mismatch")
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if current >= parse_time(approval.expires_at):
                raise ApprovalError("approval expired")
            if parse_time(approval.approved_at) > current:
                raise ApprovalError("approval timestamp is in the future")
            self._record("task_approved", task_id=task_id, approval_id=approval.approval_id,
                         payload_sha256=approval.payload_sha256)
            self.used_approvals.add(approval.approval_id)
            self.states[task_id] = TaskState.APPROVED

    def transition(self, task_id: str, new_state: TaskState) -> None:
        with self._lock:
            current = self.states.get(task_id)
            if current is None or new_state not in _ALLOWED_TRANSITIONS[current]:
                raise StateError(f"illegal task transition: {current} -> {new_state}")
            if self.kill_switch and new_state is TaskState.EXECUTING:
                raise StateError("kill switch active")
            self._record("task_state_changed", task_id=task_id,
                         previous=current.value, current=new_state.value)
            self.states[task_id] = new_state

    def reserve_budget(self, task_id: str, amount: float) -> None:
        with self._lock:
            if self.kill_switch:
                raise BudgetError("kill switch active")
            if not self.audit_available:
                raise AuditError("audit unavailable; paid work denied")
            if not math.isfinite(amount) or amount < 0:
                raise BudgetError("amount must be finite and non-negative")
            if self.spent + amount > self.monthly_budget:
                raise BudgetError("monthly budget cap exceeded")
            self._record("budget_reserved", task_id=task_id, amount=amount)
            self.spent += amount

    def claim_idempotency(self, key: str, task_id: str) -> bool:
        with self._lock:
            if not key:
                raise GuardrailError("idempotency key required")
            prior = self.idempotency.get(key)
            if prior is not None:
                if prior != task_id:
                    raise GuardrailError("idempotency key reused for another task")
                return False
            self._record("idempotency_claimed", task_id=task_id, key=key)
            self.idempotency[key] = task_id
            return True

    def activate_kill_switch(self) -> None:
        with self._lock:
            # Safety state must engage even when the audit sink is unavailable.
            self.kill_switch = True
            self._record("kill_switch_activated")
