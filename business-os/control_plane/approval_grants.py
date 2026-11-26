"""Short-lived, exact-scope approval grants for the local Business OS prototype.

This module signs approval grants with HMAC-SHA256 and consumes each grant once
in a private SQLite ledger. It does not authenticate humans itself: issuance
requires an injected identity verifier backed by a real IdP in any deployment.
It never calls adapters or performs external side effects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
import secrets
from typing import Any, Callable, Mapping

from guardrails import canonical_json, payload_sha256


class GrantError(Exception):
    """Approval grant rejected; callers must fail closed."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 16384:
        raise GrantError("malformed grant token")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise GrantError("malformed grant token") from exc


class SQLiteGrantLedger:
    """Single-host, transactional, one-use grant ledger; not a distributed store."""

    def __init__(self, db_path: str | Path):
        raw = str(db_path)
        path = Path(db_path)
        if raw == ":memory:" or not path.is_absolute() or path.is_symlink():
            raise ValueError("ledger path must be an absolute persistent non-symlink path")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
            raise ValueError("ledger directory must be private (0700 or stricter)")
        existed = path.exists()
        if existed and (not path.is_file() or stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise ValueError("existing ledger must be a private regular file")
        self.path = str(path)
        conn = self._connect()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS consumed_grants (
                grant_id TEXT PRIMARY KEY,
                grant_sha256 TEXT NOT NULL,
                consumed_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_intents (
                intent_id TEXT PRIMARY KEY,
                grant_id TEXT NOT NULL UNIQUE REFERENCES consumed_grants(grant_id),
                task_id TEXT NOT NULL UNIQUE,
                idempotency_key TEXT NOT NULL UNIQUE,
                operation_json TEXT NOT NULL,
                operation_sha256 TEXT NOT NULL,
                budget_reservation_json TEXT,
                adapter TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN
                    ('READY', 'DISPATCHING', 'VERIFY_PENDING', 'UNKNOWN', 'SUCCEEDED', 'FAILED')),
                lease_owner TEXT,
                lease_expires_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                receipt_json TEXT,
                evidence_sha256 TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_budget_limits (
                period TEXT PRIMARY KEY,
                monthly_limit_minor INTEGER NOT NULL CHECK(monthly_limit_minor >= 0),
                per_task_limit_minor INTEGER NOT NULL CHECK(per_task_limit_minor >= 0),
                currency TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_budget_reservations (
                reservation_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL UNIQUE REFERENCES execution_intents(task_id),
                amount_minor INTEGER NOT NULL CHECK(amount_minor >= 0),
                currency TEXT NOT NULL,
                period TEXT NOT NULL REFERENCES execution_budget_limits(period),
                state TEXT NOT NULL CHECK(state IN ('RESERVED', 'SETTLED', 'RELEASED')),
                actual_minor INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS budget_limits_no_update
                BEFORE UPDATE ON execution_budget_limits
                BEGIN SELECT RAISE(ABORT, 'budget limits require controlled offline change'); END;
                CREATE TRIGGER IF NOT EXISTS budget_limits_no_delete
                BEFORE DELETE ON execution_budget_limits
                BEGIN SELECT RAISE(ABORT, 'budget limits cannot be deleted'); END;
                CREATE TRIGGER IF NOT EXISTS budget_reservations_immutable_fields
                BEFORE UPDATE OF reservation_id, task_id, amount_minor, currency, period, created_at
                ON execution_budget_reservations
                BEGIN SELECT RAISE(ABORT, 'budget reservation scope is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS budget_reservations_no_delete
                BEFORE DELETE ON execution_budget_reservations
                BEGIN SELECT RAISE(ABORT, 'budget reservations cannot be deleted'); END;
            """)
            conn.execute("""CREATE TABLE IF NOT EXISTS mock_destination_receipts (
                idempotency_key TEXT PRIMARY KEY,
                operation_sha256 TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS mock_receipts_no_update
                BEFORE UPDATE ON mock_destination_receipts
                BEGIN SELECT RAISE(ABORT, 'mock destination receipts are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS mock_receipts_no_delete
                BEFORE DELETE ON mock_destination_receipts
                BEGIN SELECT RAISE(ABORT, 'mock destination receipts are immutable'); END;
            """)
            conn.execute("""CREATE TABLE IF NOT EXISTS control_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
            conn.execute("INSERT OR IGNORE INTO control_state(key, value) VALUES ('kill_switch', 'false')")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS execution_intents_one_per_task ON execution_intents(task_id)"
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                intent_id TEXT NOT NULL,
                event TEXT NOT NULL,
                details_json TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )""")
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS execution_intents_immutable_fields
                BEFORE UPDATE OF intent_id, grant_id, task_id, idempotency_key, operation_json,
                    operation_sha256, budget_reservation_json, adapter, action, target, created_at
                ON execution_intents
                BEGIN SELECT RAISE(ABORT, 'execution intent proposal fields are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS execution_intents_no_delete
                BEFORE DELETE ON execution_intents
                BEGIN SELECT RAISE(ABORT, 'execution intents cannot be deleted'); END;
            """)
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS execution_events_no_update
                BEFORE UPDATE ON execution_events
                BEGIN SELECT RAISE(ABORT, 'execution_events is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS execution_events_no_delete
                BEFORE DELETE ON execution_events
                BEGIN SELECT RAISE(ABORT, 'execution_events is append-only'); END;
            """)
            conn.executescript("""
                CREATE TRIGGER IF NOT EXISTS consumed_grants_no_update
                BEFORE UPDATE ON consumed_grants
                BEGIN SELECT RAISE(ABORT, 'consumed grants are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS consumed_grants_no_delete
                BEFORE DELETE ON consumed_grants
                BEGIN SELECT RAISE(ABORT, 'consumed grants are append-only'); END;
            """)
        finally:
            conn.close()
        if not existed:
            os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def _append_execution_event(self, conn: sqlite3.Connection, intent_id: str,
                                event: str, **details: Any) -> None:
        row = conn.execute(
            "SELECT event_hash FROM execution_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous = row[0] if row else "0" * 64
        created = datetime.now(timezone.utc).isoformat()
        details_json = canonical_json(details).decode("utf-8")
        event_hash = hashlib.sha256(canonical_json({
            "intent_id": intent_id, "event": event, "details": details,
            "previous_hash": previous, "created_at": created,
        })).hexdigest()
        conn.execute(
            """INSERT INTO execution_events
               (intent_id, event, details_json, previous_hash, event_hash, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (intent_id, event, details_json, previous, event_hash, created),
        )

    def configure_budget(self, *, period: str, monthly_limit_minor: int,
                        currency: str, per_task_limit_minor: int | None = None) -> None:
        """Set a local hard cap once per period; changes require controlled offline migration."""
        if not isinstance(period, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period):
            raise GrantError("budget period must be YYYY-MM")
        if isinstance(monthly_limit_minor, bool) or not isinstance(monthly_limit_minor, int) or monthly_limit_minor < 0:
            raise GrantError("monthly budget must be a non-negative integer in minor currency units")
        if per_task_limit_minor is None:
            per_task_limit_minor = monthly_limit_minor
        if isinstance(per_task_limit_minor, bool) or not isinstance(per_task_limit_minor, int) or not 0 <= per_task_limit_minor <= monthly_limit_minor:
            raise GrantError("per-task budget must be between zero and the monthly limit")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise GrantError("currency must be a three-letter uppercase code")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM execution_budget_limits WHERE period=?", (period,)
            ).fetchone()
            if existing:
                if (existing["monthly_limit_minor"], existing["per_task_limit_minor"], existing["currency"]) == (
                    monthly_limit_minor, per_task_limit_minor, currency
                ):
                    conn.commit()
                    return
                raise GrantError("budget limit already configured; changes require controlled offline migration")
            conn.execute(
                """INSERT INTO execution_budget_limits
                   (period, monthly_limit_minor, per_task_limit_minor, currency, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (period, monthly_limit_minor, per_task_limit_minor, currency, now),
            )
            self._append_execution_event(
                conn, "__system__", "budget_configured", period=period,
                monthly_limit_minor=monthly_limit_minor,
                per_task_limit_minor=per_task_limit_minor, currency=currency,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _reserve_budget_in_transaction(self, conn: sqlite3.Connection, task_id: str,
                                       budget: Mapping[str, Any], now: str) -> None:
        required = {"reservation_id", "amount_minor", "currency", "period"}
        if not isinstance(budget, Mapping) or set(budget) != required:
            raise GrantError("budget reservation schema invalid")
        amount = budget["amount_minor"]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise GrantError("budget amount must be a non-negative integer in minor units")
        if not isinstance(budget["reservation_id"], str) or not budget["reservation_id"].strip():
            raise GrantError("budget reservation ID required")
        if not re.fullmatch(r"[A-Z]{3}", str(budget["currency"])):
            raise GrantError("budget currency must be a three-letter uppercase code")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", str(budget["period"])):
            raise GrantError("budget period must be YYYY-MM")
        limit = conn.execute(
            "SELECT * FROM execution_budget_limits WHERE period=?", (budget["period"],)
        ).fetchone()
        if not limit:
            raise GrantError("budget limit is not configured; paid execution denied")
        if limit["currency"] != budget["currency"]:
            raise GrantError("budget currency mismatch")
        if amount > limit["per_task_limit_minor"]:
            raise GrantError("per-task budget hard limit exceeded")
        usage = conn.execute(
            """SELECT COALESCE(SUM(
                   CASE WHEN state='RESERVED' THEN amount_minor
                        WHEN state='SETTLED' THEN actual_minor ELSE 0 END
               ), 0) AS total
               FROM execution_budget_reservations WHERE period=?""",
            (budget["period"],),
        ).fetchone()["total"]
        if usage + amount > limit["monthly_limit_minor"]:
            raise GrantError("monthly budget hard limit exceeded")
        conn.execute(
            """INSERT INTO execution_budget_reservations
               (reservation_id, task_id, amount_minor, currency, period, state,
                actual_minor, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'RESERVED', NULL, ?, ?)""",
            (budget["reservation_id"], task_id, amount, budget["currency"],
             budget["period"], now, now),
        )
        self._append_execution_event(
            conn, task_id, "budget_reserved", reservation_id=budget["reservation_id"],
            amount_minor=amount, currency=budget["currency"], period=budget["period"],
        )

    def budget_usage(self, period: str) -> Mapping[str, Any]:
        conn = self._connect()
        try:
            limit = conn.execute(
                "SELECT * FROM execution_budget_limits WHERE period=?", (period,)
            ).fetchone()
            if not limit:
                raise GrantError("budget limit is not configured")
            rows = conn.execute(
                """SELECT
                   COALESCE(SUM(CASE WHEN state='RESERVED' THEN amount_minor ELSE 0 END),0) AS reserved,
                   COALESCE(SUM(CASE WHEN state='SETTLED' THEN actual_minor ELSE 0 END),0) AS settled
                   FROM execution_budget_reservations WHERE period=?""",
                (period,),
            ).fetchone()
            total = rows["reserved"] + rows["settled"]
            return {
                "period": period,
                "currency": limit["currency"],
                "monthly_limit_minor": limit["monthly_limit_minor"],
                "per_task_limit_minor": limit["per_task_limit_minor"],
                "reserved_minor": rows["reserved"],
                "settled_minor": rows["settled"],
                "used_minor": total,
                "remaining_minor": limit["monthly_limit_minor"] - total,
            }
        finally:
            conn.close()

    def get_budget_reservation(self, task_id: str) -> Mapping[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM execution_budget_reservations WHERE task_id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def settle_budget(self, task_id: str, actual_minor: int) -> None:
        if isinstance(actual_minor, bool) or not isinstance(actual_minor, int) or actual_minor < 0:
            raise GrantError("actual budget must be a non-negative integer in minor units")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM execution_budget_reservations WHERE task_id=?", (task_id,)
            ).fetchone()
            if not row or row["state"] != "RESERVED":
                raise GrantError("no active budget reservation to settle")
            outcome = conn.execute(
                "SELECT state, evidence_sha256 FROM execution_intents WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if not outcome or outcome["state"] not in {"SUCCEEDED", "FAILED"} or not outcome["evidence_sha256"]:
                raise GrantError("budget settlement requires independently reconciled terminal outcome")
            if actual_minor > row["amount_minor"]:
                raise GrantError("actual cost exceeds approved per-task reservation")
            usage = conn.execute(
                """SELECT COALESCE(SUM(
                       CASE WHEN state='RESERVED' THEN amount_minor
                            WHEN state='SETTLED' THEN actual_minor ELSE 0 END
                   ),0) AS total
                   FROM execution_budget_reservations WHERE period=? AND task_id<>?""",
                (row["period"], task_id),
            ).fetchone()["total"]
            limit = conn.execute(
                "SELECT monthly_limit_minor FROM execution_budget_limits WHERE period=?",
                (row["period"],),
            ).fetchone()
            if not limit or usage + actual_minor > limit["monthly_limit_minor"]:
                raise GrantError("settled spend would exceed monthly hard limit")
            conn.execute(
                """UPDATE execution_budget_reservations SET state='SETTLED',
                   actual_minor=?, updated_at=? WHERE task_id=? AND state='RESERVED'""",
                (actual_minor, now, task_id),
            )
            self._append_execution_event(
                conn, task_id, "budget_settled", actual_minor=actual_minor,
                currency=row["currency"], period=row["period"],
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def release_budget(self, task_id: str, *, verified_no_effect: bool) -> None:
        if verified_no_effect is not True:
            raise GrantError("budget release requires independently verified no-effect outcome")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM execution_budget_reservations WHERE task_id=?", (task_id,)
            ).fetchone()
            if not row or row["state"] != "RESERVED":
                raise GrantError("no active budget reservation to release")
            outcome = conn.execute(
                "SELECT state, evidence_sha256 FROM execution_intents WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if not outcome or outcome["state"] != "FAILED" or not outcome["evidence_sha256"]:
                raise GrantError("budget release requires reconciled FAILED outcome with evidence")
            conn.execute(
                """UPDATE execution_budget_reservations SET state='RELEASED',
                   updated_at=? WHERE task_id=? AND state='RESERVED'""",
                (now, task_id),
            )
            self._append_execution_event(
                conn, task_id, "budget_released", reservation_id=row["reservation_id"],
                verified_no_effect=True,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def verify_execution_audit_chain(self) -> bool:
        conn = self._connect()
        try:
            rows = conn.execute(
                """SELECT intent_id, event, details_json, previous_hash, event_hash, created_at
                   FROM execution_events ORDER BY sequence"""
            ).fetchall()
        finally:
            conn.close()
        previous = "0" * 64
        for row in rows:
            if row["previous_hash"] != previous:
                return False
            try:
                details = json.loads(row["details_json"])
            except (TypeError, json.JSONDecodeError):
                return False
            if not isinstance(details, dict):
                return False
            expected = hashlib.sha256(canonical_json({
                "intent_id": row["intent_id"], "event": row["event"],
                "details": details, "previous_hash": previous,
                "created_at": row["created_at"],
            })).hexdigest()
            if expected != row["event_hash"]:
                return False
            previous = row["event_hash"]
        return True

    def verify_budget_integrity(self) -> bool:
        """Check budget limits and immutable reservation scope against audit evidence."""
        conn = self._connect()
        try:
            limits = conn.execute("SELECT * FROM execution_budget_limits").fetchall()
            reservations = conn.execute("SELECT * FROM execution_budget_reservations").fetchall()
            intents = conn.execute("SELECT task_id, budget_reservation_json FROM execution_intents").fetchall()
            events = conn.execute(
                """SELECT intent_id, event, details_json FROM execution_events
                   WHERE event IN ('budget_configured','budget_reserved','budget_settled','budget_released')"""
            ).fetchall()
        finally:
            conn.close()
        configured, reserved, settled, released = {}, {}, {}, {}
        for event in events:
            try:
                details = json.loads(event["details_json"])
            except (TypeError, json.JSONDecodeError):
                return False
            if not isinstance(details, dict):
                return False
            if event["event"] == "budget_configured":
                key, target = details.get("period"), configured
            elif event["event"] == "budget_reserved":
                key, target = event["intent_id"], reserved
            elif event["event"] == "budget_settled":
                key, target = event["intent_id"], settled
            else:
                key, target = event["intent_id"], released
            if not key or key in target:
                return False
            target[key] = details
        if len(configured) != len(limits) or len(reserved) != len(reservations):
            return False
        limit_map = {row["period"]: row for row in limits}
        for limit in limits:
            details = configured.get(limit["period"])
            if not details or any(details.get(key) != value for key, value in {
                "monthly_limit_minor": limit["monthly_limit_minor"],
                "per_task_limit_minor": limit["per_task_limit_minor"],
                "currency": limit["currency"],
            }.items()):
                return False
        reservation_map = {row["task_id"]: row for row in reservations}
        used_by_period: dict[str, int] = {}
        for intent in intents:
            try:
                budget = json.loads(intent["budget_reservation_json"]) if intent["budget_reservation_json"] else None
            except (TypeError, json.JSONDecodeError):
                return False
            row = reservation_map.get(intent["task_id"])
            if budget is None:
                if row is not None:
                    return False
                continue
            if row is None:
                return False
            details = reserved.get(intent["task_id"])
            limit = limit_map.get(row["period"])
            if (not limit or row["currency"] != limit["currency"]
                    or row["amount_minor"] > limit["per_task_limit_minor"]):
                return False
            expected = {
                "reservation_id": row["reservation_id"],
                "amount_minor": row["amount_minor"],
                "currency": row["currency"],
                "period": row["period"],
            }
            if not isinstance(budget, dict) or any(budget.get(k) != v for k, v in expected.items()):
                return False
            if not details or any(details.get(k) != v for k, v in expected.items()):
                return False
            settled_event = settled.get(intent["task_id"])
            released_event = released.get(intent["task_id"])
            if row["state"] == "RESERVED":
                if settled_event or released_event or row["actual_minor"] is not None:
                    return False
                used_by_period[row["period"]] = used_by_period.get(row["period"], 0) + row["amount_minor"]
            elif row["state"] == "SETTLED":
                if (not settled_event or released_event
                        or settled_event.get("actual_minor") != row["actual_minor"]
                        or row["actual_minor"] is None
                        or row["actual_minor"] > row["amount_minor"]):
                    return False
                used_by_period[row["period"]] = used_by_period.get(row["period"], 0) + row["actual_minor"]
            elif row["state"] == "RELEASED":
                if not released_event or settled_event or row["actual_minor"] is not None:
                    return False
            else:
                return False
        for period, used in used_by_period.items():
            if used > limit_map[period]["monthly_limit_minor"]:
                return False
        return True

    def verify_mock_destination_integrity(self) -> bool:
        """Tie immutable synthetic destination receipts to their approved intents."""
        conn = self._connect()
        try:
            intents = conn.execute("SELECT * FROM execution_intents").fetchall()
            receipts = conn.execute("SELECT * FROM mock_destination_receipts").fetchall()
            events = conn.execute(
                """SELECT intent_id, details_json FROM execution_events
                   WHERE event='destination_accepted'"""
            ).fetchall()
        finally:
            conn.close()
        by_key = {row["idempotency_key"]: row for row in intents}
        receipt_map = {row["idempotency_key"]: row for row in receipts}
        if len(receipt_map) != len(receipts) or len(events) != len(receipts):
            return False
        acceptance_map = {}
        for event in events:
            try:
                details = json.loads(event["details_json"])
            except (TypeError, json.JSONDecodeError):
                return False
            if not isinstance(details, dict):
                return False
            key = details.get("idempotency_key")
            if not key or key in acceptance_map:
                return False
            acceptance_map[key] = (event["intent_id"], details)
        for receipt in receipts:
            intent = by_key.get(receipt["idempotency_key"])
            acceptance = acceptance_map.get(receipt["idempotency_key"])
            if (intent is None or receipt["operation_sha256"] != intent["operation_sha256"]
                    or receipt["result"] != "mock-accepted" or acceptance is None):
                return False
            event_intent, details = acceptance
            if (event_intent != intent["intent_id"]
                    or details.get("operation_sha256") != receipt["operation_sha256"]
                    or details.get("result") != receipt["result"]
                    or details.get("created_at") != receipt["created_at"]):
                return False
        for intent in intents:
            has_receipt = intent["idempotency_key"] in receipt_map
            if intent["state"] in {"READY", "FAILED"} and has_receipt:
                return False
            if intent["state"] in {"VERIFY_PENDING", "SUCCEEDED"} and not has_receipt:
                return False
        return True

    def verify_execution_integrity(self) -> bool:
        """Check current immutable intent rows against their original audit events."""
        conn = self._connect()
        try:
            intents = conn.execute("SELECT * FROM execution_intents").fetchall()
            events = conn.execute(
                "SELECT intent_id, details_json FROM execution_events WHERE event='intent_created'"
            ).fetchall()
        finally:
            conn.close()
        created = {}
        for event in events:
            if event["intent_id"] in created:
                return False
            try:
                details = json.loads(event["details_json"])
            except (TypeError, json.JSONDecodeError):
                return False
            if not isinstance(details, dict):
                return False
            created[event["intent_id"]] = details
        if len(created) != len(intents):
            return False
        for intent in intents:
            details = created.get(intent["intent_id"])
            if not details:
                return False
            try:
                actual_hash = payload_sha256(json.loads(intent["operation_json"]))
            except Exception:
                return False
            try:
                budget = json.loads(intent["budget_reservation_json"]) if intent["budget_reservation_json"] else None
            except (TypeError, json.JSONDecodeError):
                return False
            expected = {
                "grant_id": intent["grant_id"],
                "task_id": intent["task_id"],
                "idempotency_key": intent["idempotency_key"],
                "operation_sha256": intent["operation_sha256"],
                "budget_reservation": budget,
                "adapter": intent["adapter"],
                "action": intent["action"],
                "target": intent["target"],
            }
            if actual_hash != intent["operation_sha256"] or any(
                details.get(key) != value for key, value in expected.items()
            ):
                return False
        return self.verify_budget_integrity() and self.verify_mock_destination_integrity()

    def verify_all(self) -> Mapping[str, Any]:
        """Return a complete local integrity report without changing ledger state."""
        conn = self._connect()
        try:
            sqlite_result = conn.execute("PRAGMA integrity_check").fetchone()
            foreign_key_issues = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()
        checks = {
            "sqlite_integrity": bool(sqlite_result and sqlite_result[0] == "ok"),
            "foreign_keys": not foreign_key_issues,
            "execution_audit_chain": self.verify_execution_audit_chain(),
            "execution_intents": self.verify_execution_integrity(),
            "budget_ledger": self.verify_budget_integrity(),
            "mock_destination": self.verify_mock_destination_integrity(),
        }
        return {
            "ok": all(checks.values()),
            "kill_switch_active": self.kill_switch_active(),
            "checks": checks,
        }

    def consume(self, grant_id: str, grant_sha256: str) -> None:
        """Atomically claim a grant ID. Duplicate or raced claims are rejected."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            switch = conn.execute(
                "SELECT value FROM control_state WHERE key='kill_switch'"
            ).fetchone()
            if switch and switch["value"] == "true":
                raise GrantError("persistent kill switch active; grant consumption denied")
            conn.execute(
                "INSERT INTO consumed_grants(grant_id, grant_sha256, consumed_at) VALUES (?, ?, ?)",
                (grant_id, grant_sha256, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise GrantError("approval grant already consumed") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def consume_with_intent(self, grant_id: str, grant_sha256: str, intent: Mapping[str, Any]) -> None:
        """Consume a grant and persist its immutable execution intent in one transaction."""
        required = {
            "intent_id", "task_id", "idempotency_key", "operation_json",
            "operation_sha256", "adapter", "action", "target",
        }
        optional = {"budget_reservation"}
        if not isinstance(intent, Mapping) or not (set(intent) == required or set(intent) == required | optional):
            raise GrantError("execution intent schema invalid")
        budget = intent.get("budget_reservation")
        budget_json = canonical_json(dict(budget)).decode("utf-8") if budget is not None else None
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            switch = conn.execute(
                "SELECT value FROM control_state WHERE key='kill_switch'"
            ).fetchone()
            if switch and switch["value"] == "true":
                raise GrantError("persistent kill switch active; intent creation denied")
            conn.execute(
                "INSERT INTO consumed_grants(grant_id, grant_sha256, consumed_at) VALUES (?, ?, ?)",
                (grant_id, grant_sha256, now),
            )
            conn.execute(
                """INSERT INTO execution_intents
                   (intent_id, grant_id, task_id, idempotency_key, operation_json,
                    operation_sha256, budget_reservation_json, adapter, action, target,
                    state, attempt_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'READY', 0, ?, ?)""",
                (intent["intent_id"], grant_id, intent["task_id"], intent["idempotency_key"],
                 intent["operation_json"], intent["operation_sha256"], budget_json,
                 intent["adapter"], intent["action"], intent["target"], now, now),
            )
            if budget is not None:
                self._reserve_budget_in_transaction(conn, intent["task_id"], budget, now)
            self._append_execution_event(conn, intent["intent_id"], "intent_created",
                                        grant_id=grant_id, task_id=intent["task_id"],
                                        idempotency_key=intent["idempotency_key"],
                                        operation_sha256=intent["operation_sha256"],
                                        budget_reservation=dict(budget) if budget is not None else None,
                                        adapter=intent["adapter"], action=intent["action"],
                                        target=intent["target"])
            conn.commit()
        except sqlite3.IntegrityError as exc:
            conn.rollback()
            raise GrantError("grant or execution intent already consumed/reserved") from exc
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_intent(self, intent_id: str, worker_id: str, lease_seconds: int = 30) -> Mapping[str, Any]:
        """Claim READY work once; expired DISPATCHING work becomes UNKNOWN, never re-dispatched."""
        if not worker_id or not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 300:
            raise GrantError("valid worker identity and bounded lease are required")
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            switch = conn.execute(
                "SELECT value FROM control_state WHERE key='kill_switch'"
            ).fetchone()
            if switch and switch["value"] == "true":
                raise GrantError("persistent kill switch active; worker claim denied")
            row = conn.execute(
                "SELECT * FROM execution_intents WHERE intent_id = ?", (intent_id,)
            ).fetchone()
            if not row:
                raise GrantError("unknown execution intent")
            if row["state"] == "DISPATCHING" and row["lease_expires_at"]:
                old_expiry = datetime.fromisoformat(row["lease_expires_at"])
                if old_expiry <= now:
                    conn.execute(
                        """UPDATE execution_intents SET state='UNKNOWN', lease_owner=NULL,
                           lease_expires_at=NULL, last_error='worker lease expired; destination reconciliation required',
                           updated_at=? WHERE intent_id=? AND state='DISPATCHING'""",
                        (now.isoformat(), intent_id),
                    )
                    self._append_execution_event(conn, intent_id, "dispatch_lease_expired",
                                                worker_id=row["lease_owner"])
                    conn.commit()
                    raise GrantError("stale dispatch lease; intent moved to UNKNOWN for reconciliation")
            if row["state"] != "READY":
                raise GrantError("intent is not claimable; reconcile current state")
            conn.execute(
                """UPDATE execution_intents SET state='DISPATCHING', lease_owner=?,
                   lease_expires_at=?, attempt_count=attempt_count+1, updated_at=?
                   WHERE intent_id=? AND state='READY'""",
                (worker_id, expires, now.isoformat(), intent_id),
            )
            claimed = conn.execute(
                "SELECT * FROM execution_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            self._append_execution_event(conn, intent_id, "dispatch_claimed",
                                        worker_id=worker_id, attempt=claimed["attempt_count"])
            conn.commit()
            return dict(claimed)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def update_intent(self, intent_id: str, *, expected_state: str, new_state: str,
                      receipt_json: str | None = None, evidence_sha256: str | None = None,
                      error: str | None = None) -> None:
        allowed = {
            "DISPATCHING": {"VERIFY_PENDING", "UNKNOWN"},
            "VERIFY_PENDING": {"SUCCEEDED", "FAILED", "UNKNOWN"},
            "UNKNOWN": {"VERIFY_PENDING", "SUCCEEDED", "FAILED"},
        }
        if new_state not in allowed.get(expected_state, set()):
            raise GrantError("illegal execution intent transition")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                """UPDATE execution_intents SET state=?, receipt_json=COALESCE(?, receipt_json),
                   evidence_sha256=COALESCE(?, evidence_sha256), last_error=?,
                   lease_owner=NULL, lease_expires_at=NULL, updated_at=?
                   WHERE intent_id=? AND state=?""",
                (new_state, receipt_json, evidence_sha256, error, now, intent_id, expected_state),
            )
            if cur.rowcount != 1:
                raise GrantError("execution intent state changed concurrently")
            self._append_execution_event(conn, intent_id, "state_changed",
                                        previous=expected_state, current=new_state,
                                        evidence_sha256=evidence_sha256)
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def record_mock_destination_acceptance(self, idempotency_key: str,
                                           operation: Mapping[str, Any]) -> Mapping[str, Any]:
        """Persist a synthetic destination receipt with durable idempotency semantics."""
        if not idempotency_key:
            raise GrantError("mock destination idempotency key required")
        digest = payload_sha256(operation)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            switch = conn.execute(
                "SELECT value FROM control_state WHERE key='kill_switch'"
            ).fetchone()
            if switch and switch["value"] == "true":
                raise GrantError("persistent kill switch active at mock destination")
            intent = conn.execute(
                "SELECT * FROM execution_intents WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if not intent or intent["operation_sha256"] != digest:
                raise GrantError("mock destination request is not bound to an approved execution intent")
            row = conn.execute(
                "SELECT * FROM mock_destination_receipts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row:
                if row["operation_sha256"] != digest:
                    raise GrantError("mock destination idempotency key reused for different operation")
                if intent["state"] in {"READY", "FAILED"}:
                    raise GrantError("existing destination receipt conflicts with execution intent state")
                self._append_execution_event(
                    conn, intent["intent_id"], "destination_replayed",
                    idempotency_key=idempotency_key, operation_sha256=digest,
                    receipt_created_at=row["created_at"], replayed_at=now,
                )
                conn.commit()
                return dict(row)
            if intent["state"] != "DISPATCHING":
                raise GrantError("new mock destination receipt requires a claimed execution intent")
            conn.execute(
                """INSERT INTO mock_destination_receipts
                   (idempotency_key, operation_sha256, result, created_at)
                   VALUES (?, ?, 'mock-accepted', ?)""",
                (idempotency_key, digest, now),
            )
            created = conn.execute(
                "SELECT * FROM mock_destination_receipts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            self._append_execution_event(
                conn, intent["intent_id"], "destination_accepted",
                idempotency_key=idempotency_key, operation_sha256=digest,
                result="mock-accepted", created_at=now,
            )
            conn.commit()
            return dict(created)
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def lookup_mock_destination_receipt(self, idempotency_key: str) -> Mapping[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM mock_destination_receipts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def activate_kill_switch(self) -> None:
        """Persist an irreversible-by-API emergency stop; audit failure cannot clear it."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE control_state SET value='true' WHERE key='kill_switch'")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()
        audit = self._connect()
        try:
            audit.execute("BEGIN IMMEDIATE")
            self._append_execution_event(audit, "__system__", "kill_switch_activated")
            audit.commit()
        except Exception:
            if audit.in_transaction:
                audit.rollback()
            raise
        finally:
            audit.close()

    def backup_to(self, destination_path: str | Path) -> Path:
        """Create a new private SQLite-consistent backup and verify its integrity."""
        destination = Path(destination_path)
        if not destination.is_absolute() or destination.is_symlink():
            raise ValueError("backup path must be absolute and must not be a symlink")
        if destination.resolve() == Path(self.path).resolve():
            raise ValueError("backup destination must differ from the live ledger")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if stat.S_IMODE(destination.parent.stat().st_mode) & 0o077:
            raise ValueError("backup directory must be private (0700 or stricter)")
        if destination.exists():
            raise ValueError("backup destination already exists; refusing to overwrite")
        source = self._connect()
        target = sqlite3.connect(str(destination), timeout=10, isolation_level=None)
        try:
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchone()
            foreign_keys = target.execute("PRAGMA foreign_key_check").fetchall()
            if not integrity or integrity[0] != "ok" or foreign_keys:
                raise GrantError("backup integrity verification failed")
            target.commit()
        except Exception:
            target.close()
            source.close()
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        else:
            target.close()
            source.close()
        os.chmod(destination, 0o600)
        restored = SQLiteGrantLedger(destination)
        if not restored.verify_execution_audit_chain() or not restored.verify_execution_integrity():
            destination.unlink(missing_ok=True)
            raise GrantError("backup audit or intent integrity verification failed")
        return destination

    def kill_switch_active(self) -> bool:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM control_state WHERE key='kill_switch'"
            ).fetchone()
            return bool(row and row["value"] == "true")
        finally:
            conn.close()

    def recover_stale_dispatches(self, now: datetime | None = None) -> int:
        """Move expired DISPATCHING leases to UNKNOWN; never put them back in READY."""
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        conn = self._connect()
        recovered = 0
        try:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """SELECT intent_id, lease_owner, lease_expires_at FROM execution_intents
                   WHERE state='DISPATCHING' AND lease_expires_at IS NOT NULL"""
            ).fetchall()
            for row in rows:
                try:
                    expiry = datetime.fromisoformat(row["lease_expires_at"])
                except (TypeError, ValueError):
                    expiry = current - timedelta(seconds=1)
                if expiry.tzinfo is None or expiry <= current:
                    cur = conn.execute(
                        """UPDATE execution_intents SET state='UNKNOWN', lease_owner=NULL,
                           lease_expires_at=NULL,
                           last_error='worker lease expired; destination reconciliation required',
                           updated_at=? WHERE intent_id=? AND state='DISPATCHING'""",
                        (current.isoformat(), row["intent_id"]),
                    )
                    if cur.rowcount == 1:
                        self._append_execution_event(
                            conn, row["intent_id"], "dispatch_lease_expired",
                            worker_id=row["lease_owner"],
                        )
                        recovered += 1
            conn.commit()
            return recovered
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def list_ready_intents(self) -> list[Mapping[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM execution_intents WHERE state='READY' ORDER BY created_at"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def list_intents(self, *, state: str | None = None, limit: int = 100) -> list[Mapping[str, Any]]:
        """List safe operational summaries without exposing operation payloads."""
        states = {"READY", "DISPATCHING", "VERIFY_PENDING", "UNKNOWN", "SUCCEEDED", "FAILED"}
        if state is not None and state not in states:
            raise GrantError("unsupported intent state filter")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise GrantError("intent list limit must be between 1 and 500")
        columns = (
            "intent_id, grant_id, task_id, idempotency_key, adapter, action, target, "
            "state, attempt_count, created_at, updated_at, lease_owner, lease_expires_at, "
            "evidence_sha256, last_error"
        )
        conn = self._connect()
        try:
            if state is None:
                rows = conn.execute(
                    f"SELECT {columns} FROM execution_intents ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT {columns} FROM execution_intents WHERE state=? ORDER BY created_at DESC LIMIT ?",
                    (state, limit),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_intent(self, intent_id: str) -> Mapping[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM execution_intents WHERE intent_id=?", (intent_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list_reconcilable_intents(self) -> list[Mapping[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM execution_intents WHERE state IN ('UNKNOWN','VERIFY_PENDING') ORDER BY created_at"
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()


class ApprovalGrantAuthority:
    """Issue and consume cryptographically authenticated, narrowly scoped grants."""

    def __init__(
        self,
        *,
        signing_key: bytes,
        ledger: SQLiteGrantLedger,
        identity_verifier: Callable[[str, Any], bool],
        max_ttl_seconds: int = 600,
    ):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("signing_key must contain at least 32 random bytes")
        if not callable(identity_verifier):
            raise ValueError("a real identity_verifier callback is required")
        if not 1 <= max_ttl_seconds <= 900:
            raise ValueError("max_ttl_seconds must be between 1 and 900")
        self._key = signing_key
        self._ledger = ledger
        self._identity_verifier = identity_verifier
        self._max_ttl = max_ttl_seconds

    def _sign(self, payload_bytes: bytes) -> str:
        return hmac.new(self._key, payload_bytes, hashlib.sha256).hexdigest()

    def issue(
        self,
        *,
        task_id: str,
        payload: Mapping[str, Any],
        adapter: str,
        action: str,
        target: str,
        idempotency_key: str,
        requester_id: str,
        approver_id: str,
        auth_context: Any,
        ttl_seconds: int = 300,
        now: datetime | None = None,
    ) -> str:
        if not all(isinstance(v, str) and v.strip() for v in (
            task_id, adapter, action, target, idempotency_key, requester_id, approver_id
        )):
            raise GrantError("task, scope, idempotency and actor fields are required")
        if self._ledger.kill_switch_active():
            raise GrantError("persistent kill switch active; new approvals are paused")
        if requester_id == approver_id:
            raise GrantError("self-approval is prohibited")
        if not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= self._max_ttl:
            raise GrantError("grant lifetime exceeds the configured limit")
        try:
            authenticated = self._identity_verifier(approver_id, auth_context)
        except Exception as exc:
            raise GrantError("human identity verification failed") from exc
        if authenticated is not True:
            raise GrantError("authenticated human approver required")

        issued = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        grant = {
            "version": 1,
            "grant_id": secrets.token_urlsafe(24),
            "task_id": task_id,
            "payload_sha256": payload_sha256(payload),
            "adapter": adapter,
            "action": action,
            "target": target,
            "idempotency_key": idempotency_key,
            "requester_id": requester_id,
            "approver_id": approver_id,
            "issued_at": issued.isoformat(),
            "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        encoded = _b64encode(canonical_json(grant))
        signature = self._sign(encoded.encode("ascii"))
        return encoded + "." + signature

    def verify_and_consume(
        self,
        token: str,
        *,
        task_id: str,
        payload: Mapping[str, Any],
        adapter: str,
        action: str,
        target: str,
        idempotency_key: str,
        requester_id: str,
        now: datetime | None = None,
        execution_intent: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        if not isinstance(token, str) or token.count(".") != 1:
            raise GrantError("malformed approval grant")
        encoded, supplied_signature = token.split(".", 1)
        try:
            signed_bytes = encoded.encode("ascii", errors="strict")
        except UnicodeEncodeError as exc:
            raise GrantError("malformed approval grant") from exc
        expected_signature = self._sign(signed_bytes)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            raise GrantError("approval grant signature invalid")
        raw = _b64decode(encoded)
        try:
            grant = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GrantError("approval grant payload invalid") from exc
        required = {
            "version", "grant_id", "task_id", "payload_sha256", "adapter", "action",
            "target", "idempotency_key", "requester_id", "approver_id", "issued_at",
            "expires_at",
        }
        if not isinstance(grant, dict) or set(grant) != required or grant["version"] != 1:
            raise GrantError("approval grant schema invalid")
        if grant["requester_id"] == grant["approver_id"]:
            raise GrantError("self-approved grant rejected")
        expected = {
            "task_id": task_id,
            "payload_sha256": payload_sha256(payload),
            "adapter": adapter,
            "action": action,
            "target": target,
            "idempotency_key": idempotency_key,
            "requester_id": requester_id,
        }
        if any(grant.get(key) != value for key, value in expected.items()):
            raise GrantError("approval grant does not match exact task, payload or scope")
        current_value = now or datetime.now(timezone.utc)
        if current_value.tzinfo is None or current_value.utcoffset() is None:
            raise GrantError("verification time must include a timezone")
        current = current_value.astimezone(timezone.utc)
        if not isinstance(grant["expires_at"], str) or not isinstance(grant["issued_at"], str):
            raise GrantError("approval grant timestamps invalid")
        try:
            expires = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
            issued = datetime.fromisoformat(grant["issued_at"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise GrantError("approval grant timestamps invalid") from exc
        if expires.tzinfo is None or issued.tzinfo is None or issued > current or current >= expires:
            raise GrantError("approval grant is expired or not yet valid")
        grant_digest = hashlib.sha256(raw).hexdigest()
        if execution_intent is None:
            self._ledger.consume(grant["grant_id"], grant_digest)
        else:
            expected_intent = {
                "intent_id": grant["grant_id"],
                "task_id": task_id,
                "idempotency_key": idempotency_key,
                "operation_json": canonical_json(dict(payload)).decode("utf-8"),
                "operation_sha256": payload_sha256(payload),
                "adapter": adapter,
                "action": action,
                "target": target,
            }
            if "_budget" in payload:
                expected_intent["budget_reservation"] = payload["_budget"]
            if dict(execution_intent) != expected_intent:
                raise GrantError("execution intent does not match verified approval scope")
            self._ledger.consume_with_intent(grant["grant_id"], grant_digest, expected_intent)
        return grant
