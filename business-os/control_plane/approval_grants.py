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
import json
import os
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
        conn.execute("PRAGMA busy_timeout = 10000")
        conn.execute("PRAGMA synchronous = FULL")
        return conn

    def consume(self, grant_id: str, grant_sha256: str) -> None:
        """Atomically claim a grant ID. Duplicate or raced claims are rejected."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
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
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        try:
            expires = datetime.fromisoformat(grant["expires_at"].replace("Z", "+00:00"))
            issued = datetime.fromisoformat(grant["issued_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or issued.tzinfo is None or issued > current or current >= expires:
                raise GrantError("approval grant is expired or not yet valid")
        except (TypeError, ValueError) as exc:
            if isinstance(exc, GrantError):
                raise
            raise GrantError("approval grant timestamps invalid") from exc
        grant_digest = hashlib.sha256(raw).hexdigest()
        self._ledger.consume(grant["grant_id"], grant_digest)
        return grant
