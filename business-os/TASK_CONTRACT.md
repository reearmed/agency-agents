# Task and approval contract

## Task envelope

```json
{
  "task_id": "uuid",
  "business_unit": "norevyo | automation_services | digital_products | shared",
  "objective": "one measurable outcome",
  "requester": "authenticated operator or approved system workflow",
  "risk_tier": "R0 | R1 | R2 | R3 | R4",
  "data_classification": "public | internal | confidential | restricted",
  "context_refs": [],
  "allowed_sources": [],
  "allowed_tools": [],
  "forbidden_actions": [],
  "assigned_agents": [],
  "budget": {"currency": "USD", "max_amount": 0},
  "deadline": "ISO-8601 timestamp",
  "acceptance_criteria": [],
  "output_schema": {},
  "approval_id": null
}
```

## State machine

`queued -> triaged -> planned -> running -> review -> staged -> awaiting_approval -> approved -> executed -> verified -> closed`

Alternative terminal states: `rejected`, `cancelled`, `failed`, `expired`, `blocked`.

No transition to `executed` is permitted for R3/R4 without a valid approval object. R4 additionally requires independent verification. A retry reuses the same idempotency key for the same intended side effect.

## Approval envelope

```json
{
  "approval_id": "uuid",
  "task_id": "uuid",
  "action": "email.send | social.publish | purchase.create | other",
  "target": "specific account, recipient, environment or resource",
  "payload_sha256": "hash of exact immutable payload",
  "amount": null,
  "currency": null,
  "risk_tier": "R3",
  "rollback_plan": "specific compensating action or not reversible",
  "expires_at": "ISO-8601 timestamp",
  "decision": "pending | approved | rejected | expired",
  "approver": null
}
```

Approval is invalid if any payload field changes. Approval is not transferable to a similar action.
