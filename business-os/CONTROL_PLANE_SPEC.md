# Business OS control plane specification

**Status: implementation specification, not a running service.** No runtime gateway or approval API is deployed by this repository change.

## Purpose

All agents operate as untrusted planners. They may propose work and produce artifacts, but they do not receive credentials for consequential integrations. A separate control plane validates task state, permissions, budget, approvals and idempotency before any integration adapter can perform a write.

## Trust boundaries

1. **Agent runtime:** generates plans, research, code and drafts. Treat all model output, retrieved content and tool results as untrusted input.
2. **Orchestrator:** validates task envelopes and delegates only to named agents. It cannot grant approvals or expand permissions.
3. **Control plane:** authoritative policy enforcement point. Owns task transitions, approval records, integration grants, budget reservations, kill switches and audit events.
4. **Adapters:** narrow service identities for individual integrations. Accept only signed, validated execution requests from the control plane; never accept direct agent calls.
5. **Human operator:** approves exact action payloads through an authenticated interface outside the agent conversation.

## Required write path

`agent proposal -> schema validation -> policy evaluation -> budget reservation -> approval check -> adapter execution -> independent verification -> audit closeout`

Any missing, unavailable, inconsistent or timed-out check fails closed. Agents cannot invoke adapters directly.

## Minimum control-plane operations

| Operation | Purpose | Permission |
|---|---|---|
| `task.submit` | Validate and register task envelope | Orchestrator |
| `task.claim` | Atomically claim queued task with lease | Runtime worker |
| `task.transition` | Enforce legal state transition | Control plane only |
| `artifact.stage` | Store immutable draft/output | Assigned agent |
| `approval.request` | Freeze exact proposed action | Orchestrator |
| `approval.decide` | Approve/reject a frozen payload | Authenticated human |
| `execution.request` | Execute one approved payload | Control plane only |
| `execution.verify` | Record independent verification | Separate verifier |
| `budget.reserve` | Reserve worst-case cost before work | Control plane |
| `kill_switch.activate` | Pause scope and revoke active leases | Operator / incident controller |

## Security requirements

- Authenticate every human and service identity; use least-privilege scoped credentials.
- Enforce authorization server-side on every request; never rely on hidden UI controls or agent prompt instructions.
- Use short-lived execution leases and integration-specific credentials held only by adapters.
- Bind approval to SHA-256 of canonical serialized payload, action, target, environment, amount/currency and expiry.
- Canonicalization must be deterministic, versioned and tested against key ordering, Unicode normalization, whitespace, omitted/null fields and numeric representations.
- Persist an idempotency key for every side effect. Repeated requests return the original outcome and do not repeat the side effect.
- Enforce unique constraints and atomic compare-and-set transitions to prevent races and replay.
- Store append-only audit events with actor, task, policy version, payload hash, timestamps, decision and adapter result. Do not log secrets or unnecessary personal data.
- Separate the executor from the verifier. Verification must query the target system or independent evidence, not trust the executor's success message.
- Secrets are never available to agents, prompts, source control or artifacts.
- Every adapter has an explicit allowlist of actions, targets and environments. No generic arbitrary HTTP or shell execution.

## Approval validity

An approval is usable once, only before expiry, and only when all of the following match the frozen request: action, integration, account, environment, target, recipient/audience, content, payload hash, amount, currency, risk tier and rollback plan. Any mismatch requires a new approval. Approval cannot be inferred from conversation tone, prior approvals, a task description or model output.

## Failure behavior

- Control plane unavailable: no external writes.
- Approval service unavailable: no R3/R4 execution.
- Budget service unavailable: no new paid work or spend.
- Audit store unavailable: no external writes.
- Kill switch active: reject new work and cancel queued execution leases.
- Adapter timeout: mark outcome unknown; reconcile target state before retry.
- Verification inconclusive: keep task in `review` or `blocked`; do not claim success.

## Deployment gates

Do not enable external adapters until authentication, authorization, approval binding, replay protection, idempotency, audit durability, spend reservation, kill switches, sandbox isolation and failure tests pass. This specification alone does not satisfy those gates.
