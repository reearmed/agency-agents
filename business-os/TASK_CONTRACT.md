# Task and approval contract

## Task envelope

The task envelope is validated by `contracts/task-envelope.schema.json`.
A budget reservation is part of the immutable `payload` under `_budget`,
so the approval payload hash binds the operation and the reservation together.

```json
{
  "task_id": "task-2026-000001",
  "business_unit": "norevyo",
  "task_type": "synthetic_or_internal_task",
  "risk_tier": "R1",
  "payload": {
    "operation": "example",
    "_budget": {
      "reservation_id": "budget-res-0001",
      "amount_minor": 1250,
      "currency": "USD",
      "period": "2026-11"
    }
  },
  "created_at": "2026-11-26T12:00:00Z",
  "expires_at": "2026-11-26T13:00:00Z",
  "idempotency_key": "task-idempotency-000001",
  "evidence_refs": []
}
```

`amount_minor` is an integer in the smallest currency unit (for USD/CAD,
cents); floating-point budget amounts are prohibited. The reservation ID,
amount, currency and `YYYY-MM` period are included in the signed payload hash.
The local ledger requires an operator-configured monthly and per-task hard
limit before it accepts a budgeted intent. Limits are configured once per
period and cannot be raised through the application API.


## State machine

`queued -> triaged -> planned -> running -> review -> staged -> awaiting_approval -> approved -> executed -> verified -> closed`

Alternative terminal states: `rejected`, `cancelled`, `failed`, `expired`, `blocked`.

No transition to `executed` is permitted for R3/R4 without a valid approval object. R4 additionally requires independent verification. A retry reuses the same idempotency key for the same intended side effect.

## Approval envelope

```json
{
  "approval_id": "approval-2026-000001",
  "task_id": "task-2026-000001",
  "payload_sha256": "64-character SHA-256 of canonical payload, including _budget",
  "approver_id": "authenticated-human-subject",
  "decision": "approved",
  "approved_at": "2026-11-26T12:05:00Z",
  "expires_at": "2026-11-26T12:15:00Z",
  "scope": {
    "adapter": "mock",
    "action": "create",
    "target": "isolated-synthetic-destination"
  }
}
```


Approval is invalid if any payload field, including budget reservation metadata, changes. Approval is not transferable to a similar action.
