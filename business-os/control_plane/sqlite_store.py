"""Durable local-only SQLite reference store for Business OS.

This is a single-host prototype, not a production control plane. It has no
network listeners, external adapters, authenticated identity provider, or
secret management. Approval/verifier identity values are caller-supplied test
inputs. Use a dedicated non-production database and proper authorization before
any real-world action is connected.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterator, Mapping

from guardrails import (
    Approval, ApprovalError, AuditError, BudgetError, GuardrailError,
    StateError, TaskState, canonical_json, parse_time, payload_sha256,
)


_ALLOWED_TRANSITIONS = {
    TaskState.PROPOSED: {TaskState.BLOCKED},
    TaskState.APPROVED: {TaskState.EXECUTING, TaskState.BLOCKED},
    TaskState.EXECUTING: {TaskState.UNKNOWN, TaskState.BLOCKED},
    TaskState.UNKNOWN: {TaskState.BLOCKED},
    TaskState.SUCCEEDED: set(),
    TaskState.BLOCKED: set(),
    TaskState.FAILED: set(),
}


class SQLiteControlPlane:
    """Transactional local reference implementation with an append-only audit chain."""

    def __init__(self, db_path: str | Path, monthly_budget: float):
        if not math.isfinite(monthly_budget) or monthly_budget < 0:
            raise ValueError("monthly_budget must be finite and non-negative")
        self.db_path = str(db_path)
        self.monthly_budget = float(monthly_budget)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize(self) -> None:
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    payload_sha256 TEXT NOT NULL,
                    approver_id TEXT NOT NULL,
                    approved_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    adapter TEXT NOT NULL,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS budget_reservations (
                    reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(task_id),
                    amount REAL NOT NULL CHECK(amount >= 0),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO control_state(key, value) VALUES ('kill_switch', 'false');
                CREATE TABLE IF NOT EXISTS audit_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS audit_events_no_update
                BEFORE UPDATE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
                BEFORE DELETE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
            """)
        finally:
            conn.close()

    def _append_audit(self, conn: sqlite3.Connection, event: str, **details: Any) -> None:
        row = conn.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = row["event_hash"] if row else "0" * 64
        created_at = datetime.now(timezone.utc).isoformat()
        details_json = canonical_json(details).decode("utf-8")
        hash_input = canonical_json({
            "event": event,
            "details": details,
            "previous_hash": previous_hash,
            "created_at": created_at,
        })
        event_hash = hashlib.sha256(hash_input).hexdigest()
        conn.execute(
            """INSERT INTO audit_events
               (event, details_json, previous_hash, event_hash, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event, details_json, previous_hash, event_hash, created_at),
        )

    def propose(self, task_id: str, payload: Mapping[str, Any]) -> str:
        if not task_id:
            raise StateError("task_id is required")
        digest = payload_sha256(payload)
        now = datetime.now(timezone.utc).isoformat()
        with self._transaction() as conn:
            conn.execute(
                "INSERT INTO tasks(task_id, payload_sha256, state, created_at) VALUES (?, ?, ?, ?)",
                (task_id, digest, TaskState.PROPOSED.value, now),
            )
            self._append_audit(conn, "task_proposed", task_id=task_id, payload_sha256=digest)
        return digest

    def _kill_switch_active(self, conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT value FROM control_state WHERE key = 'kill_switch'"
        ).fetchone()
        return bool(row and row["value"] == "true")

    def approve(
        self, *, task_id: str, payload: Mapping[str, Any], approval: Approval,
        expected_scope: Mapping[str, str], human_approver: bool = False,
        now: datetime | None = None,
    ) -> None:
        with self._transaction() as conn:
            if self._kill_switch_active(conn):
                raise ApprovalError("kill switch active")
            task = conn.execute(
                "SELECT payload_sha256, state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not task or task["state"] != TaskState.PROPOSED.value:
                raise StateError("task is not awaiting approval")
            if not human_approver:
                raise ApprovalError("authenticated human approval required")
            if approval.decision != "approved" or not approval.approver_id or not approval.approval_id:
                raise ApprovalError("approval missing or rejected")
            if approval.task_id != task_id:
                raise ApprovalError("approval task mismatch")
            proposed_hash = task["payload_sha256"]
            if payload_sha256(payload) != proposed_hash:
                raise ApprovalError("payload differs from originally proposed task")
            if approval.payload_sha256 != proposed_hash:
                raise ApprovalError("approval is not bound to originally proposed payload")
            if approval.approval_id in {
                row["approval_id"] for row in conn.execute("SELECT approval_id FROM approvals")
            }:
                raise ApprovalError("approval replay detected")
            actual_scope = {
                "adapter": approval.adapter, "action": approval.action, "target": approval.target
            }
            if dict(expected_scope) != actual_scope:
                raise ApprovalError("approval scope mismatch")
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            if current >= parse_time(approval.expires_at):
                raise ApprovalError("approval expired")
            if parse_time(approval.approved_at) > current:
                raise ApprovalError("approval timestamp is in the future")
            conn.execute(
                """INSERT INTO approvals
                   (approval_id, task_id, payload_sha256, approver_id, approved_at,
                    expires_at, adapter, action, target)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (approval.approval_id, task_id, proposed_hash, approval.approver_id,
                 approval.approved_at, approval.expires_at, approval.adapter,
                 approval.action, approval.target),
            )
            conn.execute(
                "UPDATE tasks SET state = ? WHERE task_id = ?",
                (TaskState.APPROVED.value, task_id),
            )
            self._append_audit(
                conn, "task_approved", task_id=task_id,
                approval_id=approval.approval_id, payload_sha256=proposed_hash,
            )

    def transition(self, task_id: str, new_state: TaskState) -> None:
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise StateError("unknown task")
            current = TaskState(row["state"])
            if new_state not in _ALLOWED_TRANSITIONS[current]:
                raise StateError(f"illegal task transition: {current} -> {new_state}")
            if self._kill_switch_active(conn) and new_state is TaskState.EXECUTING:
                raise StateError("kill switch active")
            conn.execute(
                "UPDATE tasks SET state = ? WHERE task_id = ?",
                (new_state.value, task_id),
            )
            self._append_audit(
                conn, "task_state_changed", task_id=task_id,
                previous=current.value, current=new_state.value,
            )

    def record_verified_outcome(
        self, task_id: str, outcome: TaskState, *, verifier_id: str, evidence_sha256: str
    ) -> None:
        if outcome not in {TaskState.SUCCEEDED, TaskState.FAILED}:
            raise StateError("verifier outcome must be succeeded or failed")
        if not verifier_id or not re.fullmatch(r"[a-f0-9]{64}", evidence_sha256):
            raise StateError("verifier identity and evidence SHA-256 are required")
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row or row["state"] not in {
                TaskState.EXECUTING.value, TaskState.UNKNOWN.value
            }:
                raise StateError("task is not awaiting outcome verification")
            previous = row["state"]
            conn.execute(
                "UPDATE tasks SET state = ? WHERE task_id = ?", (outcome.value, task_id)
            )
            self._append_audit(
                conn, "task_outcome_verified", task_id=task_id, previous=previous,
                outcome=outcome.value, verifier_id=verifier_id,
                evidence_sha256=evidence_sha256,
            )

    def claim_idempotency(self, key: str, task_id: str) -> bool:
        if not key:
            raise GuardrailError("idempotency key required")
        with self._transaction() as conn:
            if not conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                raise StateError("unknown task")
            row = conn.execute(
                "SELECT task_id FROM idempotency WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if row:
                if row["task_id"] != task_id:
                    raise GuardrailError("idempotency key reused for another task")
                return False
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO idempotency(idempotency_key, task_id, created_at) VALUES (?, ?, ?)",
                (key, task_id, now),
            )
            self._append_audit(conn, "idempotency_claimed", task_id=task_id, key=key)
            return True

    def reserve_budget(self, task_id: str, amount: float) -> None:
        if not math.isfinite(amount) or amount < 0:
            raise BudgetError("amount must be finite and non-negative")
        with self._transaction() as conn:
            if self._kill_switch_active(conn):
                raise BudgetError("kill switch active")
            if not conn.execute("SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)).fetchone():
                raise StateError("unknown task")
            spent = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM budget_reservations"
            ).fetchone()["total"]
            if spent + amount > self.monthly_budget:
                raise BudgetError("monthly budget cap exceeded")
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO budget_reservations(task_id, amount, created_at) VALUES (?, ?, ?)",
                (task_id, amount, now),
            )
            self._append_audit(conn, "budget_reserved", task_id=task_id, amount=amount)

    def activate_kill_switch(self) -> None:
        # Commit the safety state first. If the audit sink fails afterward, the
        # kill switch remains engaged rather than rolling back with the audit.
        with self._transaction() as conn:
            conn.execute(
                "UPDATE control_state SET value = 'true' WHERE key = 'kill_switch'"
            )
        with self._transaction() as conn:
            self._append_audit(conn, "kill_switch_activated")

    def kill_switch_active(self) -> bool:
        with self._connect() as conn:
            return self._kill_switch_active(conn)

    def task_state(self, task_id: str) -> TaskState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT state FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                raise StateError("unknown task")
            return TaskState(row["state"])

    def verify_audit_chain(self) -> bool:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT event, details_json, previous_hash, event_hash, created_at
                   FROM audit_events ORDER BY sequence"""
            ).fetchall()
        previous_hash = "0" * 64
        for row in rows:
            if row["previous_hash"] != previous_hash:
                return False
            details = json.loads(row["details_json"])
            hash_input = canonical_json({
                "event": row["event"], "details": details,
                "previous_hash": previous_hash, "created_at": row["created_at"],
            })
            expected = hashlib.sha256(hash_input).hexdigest()
            if expected != row["event_hash"]:
                return False
            previous_hash = row["event_hash"]
        return True
