# Local control-plane prototypes

This directory contains two local-only reference implementations:

- `guardrails.py`: a small in-memory state machine used for deterministic unit tests.
- `sqlite_store.py`: a single-host SQLite reference store with transactional task/approval/idempotency/budget operations, append-only audit triggers, an event hash chain, restrictive database file permissions and a persistent kill switch.

## Run the tests

From this directory:

```bash
python3 -m unittest -v
```

The test suite uses temporary databases and synthetic data. It does not connect to NOREVYO, Supabase, Stripe, Resend, OpenClaw, or any external adapter.

## SQLite example

The database path must be an absolute path in a private directory. New database files are created with mode 0600; an existing database file or parent directory with broader permissions is rejected.

```python
from sqlite_store import SQLiteControlPlane

control = SQLiteControlPlane(
    "/absolute/private/business-os.sqlite3",
    monthly_budget=25.00,
)
```

Do not point this example at any production database. Use a new, isolated Business OS path only.

## Signed one-use approval grant prototype

`approval_grants.py` adds HMAC-SHA256 signed grants bound to the exact task
payload hash, requester, adapter, action, target and idempotency key. Grants
expire quickly (maximum 15 minutes by default) and are consumed atomically in
a private, single-host SQLite ledger. Replays and scope/payload substitutions
are rejected. Self-approval is prohibited.

Issuance requires an injected `identity_verifier` callback. This module does
not provide an identity provider, session validation, role management, key
rotation, revocation service, network API or adapter. A caller-supplied
callback is only a seam for future integration; do not wire it to an agent
claim or a boolean request field. The signing key must be generated and
managed outside Git using a secrets manager. The local ledger is not a
distributed one-use grant service; privileged database operators can still alter the file or remove triggers.

## Durable mock-only execution outbox

`durable_execution.py` adds a mock-only worker backed by the same
`SQLiteGrantLedger` used by `ApprovalGrantAuthority`. The grant's signature,
expiry, requester, payload hash and exact adapter/action/target/idempotency
scope are validated before the ledger atomically inserts both the consumed
grant and immutable execution intent in one `BEGIN IMMEDIATE` transaction.
The intent includes canonical operation JSON and SHA-256.

The worker claims a READY intent with a bounded lease. If a process crashes
before claiming it, another worker can recover READY work. Once claimed, a
dispatch is never automatically repeated. A timeout or exception becomes
UNKNOWN; an expired dispatch lease also becomes UNKNOWN. Both require
destination lookup and separate verifier reconciliation. Successful mock
dispatches enter VERIFY_PENDING until reconciliation. Intent transitions
are recorded in an append-only hash-chained event table.

The gateway accepts only the exact `MockAdapter` and
`MockOutcomeVerifier` classes. No real adapter is supported. This closes
the earlier crash gap between consuming a grant and persisting the intent,
but it does not make a remote side effect exactly-once: a real destination
must provide durable idempotency and authoritative lookup semantics.

## Important limitations

This is not a production control plane:

- There is no authenticated network API, production identity provider, session validation, role management, key rotation, revocation service or independent verifier identity. The injected identity callback is a test seam, not proof of production authentication.
- Evidence SHA-256 values are produced by the mock verifier; no external destination evidence is fetched or independently validated.
- There is no real adapter, hosted queue, multi-host coordination, budget reconciliation/refund service, alerting, backup/restore automation or independently administered emergency control.
- SQLite is a single-host prototype. WAL and transactional locking do not make it a distributed coordination service.
- Audit triggers and the hash chain are tamper-evident, not tamper-proof against a privileged database operator who can rewrite the file or remove triggers.
- The kill switch callback is supplied by the caller; this prototype does not provide a separately administered persistent global kill switch for the outbox.


Keep all adapters disconnected until an authenticated control-plane service, independent verifier, durable audit/backup, production-grade authorization tests and incident controls exist.
