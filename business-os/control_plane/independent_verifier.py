"""Independent destination-evidence verification contract.

This module is a local reference boundary. Production must inject a separately
authenticated destination evidence reader and an authenticator for the target's
signed/authoritative evidence. It does not trust executor success messages and
does not connect to any real service.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Callable, Mapping

if __package__:
    from .guardrails import canonical_json
    from .identity_boundary import VerifiedPrincipal, require_scope
else:
    from guardrails import canonical_json
    from identity_boundary import VerifiedPrincipal, require_scope


class VerificationError(RuntimeError):
    """Evidence is missing, unauthenticated, inconsistent or inconclusive."""


@dataclass(frozen=True)
class VerifiedOutcome:
    outcome: str
    evidence_sha256: str
    destination_record_id: str
    source_id: str
    observed_at: str
    verifier_subject: str


class IndependentEvidenceVerifier:
    """Fetch and authenticate destination evidence under a separate identity."""

    EXPECTED_FIELDS = frozenset({
        "task_id", "requester_id", "executor_subject", "adapter", "action",
        "target", "environment", "idempotency_key", "payload_sha256",
        "dispatched_at",
    })
    EVIDENCE_FIELDS = frozenset({
        "task_id", "idempotency_key", "adapter", "action", "target",
        "environment", "payload_sha256", "outcome", "destination_record_id",
        "observed_at", "source_id", "raw_evidence_sha256",
    })
    MATCH_FIELDS = (
        "task_id", "idempotency_key", "adapter", "action", "target",
        "environment", "payload_sha256",
    )

    def __init__(
        self,
        *,
        evidence_reader: Callable[[str, str, str], Mapping[str, Any] | None],
        evidence_authenticator: Callable[[Mapping[str, Any]], bool],
        trusted_source_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_evidence_age_seconds: int = 86400,
        clock_skew_seconds: int = 30,
    ):
        if not callable(evidence_reader) or not callable(evidence_authenticator) or not callable(clock):
            raise ValueError("independent evidence reader, authenticator and clock are required")
        if not isinstance(trusted_source_id, str) or not trusted_source_id.strip():
            raise ValueError("trusted evidence source ID is required")
        if isinstance(max_evidence_age_seconds, bool) or not isinstance(max_evidence_age_seconds, int) or not 1 <= max_evidence_age_seconds <= 604800:
            raise ValueError("evidence age limit must be between 1 second and 7 days")
        if isinstance(clock_skew_seconds, bool) or not isinstance(clock_skew_seconds, int) or not 0 <= clock_skew_seconds <= 300:
            raise ValueError("clock skew must be between 0 and 300 seconds")
        self._reader = evidence_reader
        self._authenticator = evidence_authenticator
        self._source_id = trusted_source_id
        self._clock = clock
        self._max_age = max_evidence_age_seconds
        self._skew = clock_skew_seconds

    @staticmethod
    def _parse_time(value: Any, label: str) -> datetime:
        if not isinstance(value, str):
            raise VerificationError(f"{label} timestamp is required")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise VerificationError(f"{label} timestamp is invalid") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise VerificationError(f"{label} timestamp must include a timezone")
        return parsed.astimezone(timezone.utc)

    def verify(
        self,
        *,
        principal: VerifiedPrincipal,
        expected: Mapping[str, Any],
    ) -> VerifiedOutcome:
        if not isinstance(principal, VerifiedPrincipal):
            raise VerificationError("verified independent principal required")
        try:
            require_scope(principal, "business-os:verification:record")
        except Exception as exc:
            raise VerificationError("independent verifier scope is missing") from exc
        if "business-os:independent-verifier" not in principal.roles:
            raise VerificationError("independent verifier role is missing")
        if not isinstance(expected, Mapping) or set(expected) != self.EXPECTED_FIELDS:
            raise VerificationError("expected execution scope schema invalid")
        for key in self.EXPECTED_FIELDS - {"payload_sha256", "dispatched_at"}:
            if not isinstance(expected[key], str) or not expected[key].strip():
                raise VerificationError(f"expected {key} is required")
        if principal.subject in {expected["requester_id"], expected["executor_subject"]}:
            raise VerificationError("verifier must be independent of requester and executor")
        payload_hash = expected["payload_sha256"]
        if not isinstance(payload_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", payload_hash):
            raise VerificationError("expected payload hash is invalid")
        dispatched_at = self._parse_time(expected["dispatched_at"], "dispatch")
        try:
            evidence = self._reader(expected["adapter"], expected["target"], expected["idempotency_key"])
        except Exception as exc:
            raise VerificationError("authoritative destination lookup failed") from exc
        if not isinstance(evidence, Mapping) or set(evidence) != self.EVIDENCE_FIELDS:
            raise VerificationError("authoritative destination evidence is missing or malformed")
        if any(evidence.get(key) != expected[key] for key in self.MATCH_FIELDS):
            raise VerificationError("destination evidence does not match the approved execution")
        if evidence.get("source_id") != self._source_id:
            raise VerificationError("destination evidence source is not trusted")
        outcome = evidence.get("outcome")
        if not isinstance(outcome, str) or outcome not in {"succeeded", "failed"}:
            raise VerificationError("destination outcome is inconclusive")
        if not isinstance(evidence.get("destination_record_id"), str) or not evidence["destination_record_id"].strip():
            raise VerificationError("destination record identifier is required")
        raw_hash = evidence.get("raw_evidence_sha256")
        if not isinstance(raw_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", raw_hash):
            raise VerificationError("raw destination evidence hash is invalid")
        observed_at = self._parse_time(evidence.get("observed_at"), "evidence")
        try:
            now = self._clock()
        except Exception as exc:
            raise VerificationError("trusted verifier clock is unavailable") from exc
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise VerificationError("trusted verifier clock must return a timezone-aware datetime")
        now = now.astimezone(timezone.utc)
        if observed_at < dispatched_at - timedelta(seconds=self._skew):
            raise VerificationError("destination evidence predates the approved dispatch")
        if observed_at > now + timedelta(seconds=self._skew):
            raise VerificationError("destination evidence timestamp is in the future")
        if (now - observed_at).total_seconds() > self._max_age:
            raise VerificationError("destination evidence is too old")
        try:
            authenticated = self._authenticator(evidence)
        except Exception as exc:
            raise VerificationError("destination evidence authentication failed") from exc
        if authenticated is not True:
            raise VerificationError("destination evidence is not authenticated")
        evidence_digest = hashlib.sha256(canonical_json(dict(evidence))).hexdigest()
        return VerifiedOutcome(
            outcome=outcome,
            evidence_sha256=evidence_digest,
            destination_record_id=evidence["destination_record_id"],
            source_id=self._source_id,
            observed_at=observed_at.isoformat(),
            verifier_subject=principal.subject,
        )
