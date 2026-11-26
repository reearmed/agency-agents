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

## Important limitations

This is not a production control plane:

- There is no authenticated operator identity, authorization API, or cryptographic approval signature. The human-approver and verifier identifiers are caller-supplied test inputs.
- Evidence SHA-256 values are syntax-checked, not fetched or independently verified.
- There is no network service, queue, adapter gateway, external side effect, budget reconciliation/refund path, alerting, backup/restore automation, or multi-host coordination.
- SQLite is a single-host prototype. WAL and transactional locking do not make it a distributed coordination service.
- Audit triggers prevent ordinary updates/deletes, and the hash chain detects tampering, but a privileged database operator can still remove triggers or rewrite the file. It is tamper-evident, not tamper-proof.
- The kill switch is persistent within this database. It is not a distributed or independently administered emergency control.

Keep all adapters disconnected until an authenticated control-plane service, independent verifier, durable audit/backup, production-grade authorization tests and incident controls exist.
