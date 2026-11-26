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
The intent includes canonical operation JSON and SHA-256. A unique task constraint
and idempotency-key constraint prevent duplicate execution intents. Immutable
proposal fields cannot be updated or deleted through ordinary SQL. The
`verify_execution_integrity()` check compares current intent fields with the
original creation event, and the audit-chain verifier detects event tampering.

The ledger also has a persistent fail-closed kill switch: it blocks new approval grants, grant+intent creation, worker claims and synthetic destination acceptance, and remains engaged if its audit write fails. The durable worker checks the caller-supplied kill-switch callback before and after claiming work. The worker claims a READY intent with a bounded lease. If a process crashes
before claiming it, another worker can recover READY work. Once claimed, a
dispatch is never automatically repeated. A timeout or exception becomes
UNKNOWN; an expired dispatch lease also becomes UNKNOWN. Bulk stale-lease
recovery exposes those records for destination lookup and separate verifier
reconciliation. Successful mock
dispatches enter VERIFY_PENDING until reconciliation. Intent transitions
are recorded in an append-only hash-chained event table.

The durable gateway accepts only the exact `SQLiteMockAdapter` and
`MockOutcomeVerifier` classes. The synthetic destination accepts a new receipt only for an existing
DISPATCHING approved intent, stores immutable receipts in SQLite, enforces
idempotency-key/payload matching, and checks the persistent kill switch at the
destination boundary. It rejects direct unapproved calls and verifies that
every receipt maps to an immutable execution intent. This supports tests across
gateway restarts, but it does not make a remote side effect exactly-once: a
real destination must provide durable idempotency and authoritative lookup
semantics. The older `execution_gateway.py` remains an in-memory test harness.

## Local transactional budget ledger

The durable outbox can reserve a per-task budget in the same SQLite transaction
that consumes the signed approval grant and creates the immutable execution
intent. The reservation is carried inside the approved payload as `_budget`
and uses integer minor currency units (for example, cents), an ISO currency
code, a monthly `YYYY-MM` period and a unique reservation ID. A period must
have an operator-configured monthly and per-task hard limit before a budgeted
intent can be accepted. Limits are immutable through the application API;
raising a limit requires a controlled offline change.

Budget reservations count against the monthly cap while RESERVED. Settlement
requires a reconciled terminal execution with evidence and cannot exceed the
approved per-task reservation. Release requires a reconciled FAILED outcome,
evidence and an explicit no-effect confirmation. Budget changes and
reservations are included in the append-only audit chain and verified during
backup. This is a local accounting prototype only: it does not meter actual
model/API invoices, provide alerts, support multiple hosts or authenticate the
operator who configures limits or confirms no-effect outcomes. No paid action
or real adapter is enabled.

## Private local backup

`SQLiteGrantLedger.backup_to(path)` uses SQLite's online backup API to create
a new private backup file. It refuses to overwrite an existing destination,
checks SQLite integrity and foreign keys, opens the backup as a new ledger,
and verifies the execution audit chain, immutable intent records, budget
reservations and destination receipts. The
backup file is created with mode 0600 in a private directory. This is a
manual local backup helper only; there is no scheduler, off-host copy,
retention policy or automated restore drill.

## Important limitations

This is not a production control plane:

- There is no authenticated network API, production identity provider, session validation, role management, key rotation, revocation service or independent verifier identity. The injected identity callback is a test seam, not proof of production authentication.
- Evidence SHA-256 values are produced by the mock verifier; no external destination evidence is fetched or independently validated.
- There is no real adapter, hosted queue, multi-host coordination, invoice metering/reconciliation/refund service, alerting, off-host backup automation or independently administered emergency control. The local budget ledger and manual backup helper are reference implementations, not production services.
- SQLite is a single-host prototype. WAL and transactional locking do not make it a distributed coordination service.
- Audit triggers and the hash chain are tamper-evident, not tamper-proof against a privileged database operator who can rewrite the file or remove triggers.
- The local persistent kill switch is stored in the same SQLite database and is not independently administered or distributed. A caller-supplied callback is also checked by the gateway; neither mechanism replaces a separately hosted emergency control.


Keep all adapters disconnected until an authenticated control-plane service, independent verifier, durable audit/backup, production-grade authorization tests and incident controls exist.
