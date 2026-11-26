# Approval and execution protocol

This document defines how a proposed action becomes an authorized side effect.

## 1. Proposal

The assigned agent creates an immutable proposal containing:
- task ID and business unit;
- exact action and integration;
- target account, environment and resource;
- exact content/body or structured operation;
- recipient/audience where relevant;
- amount and currency where relevant;
- expected effect, risk tier and rollback/compensation plan;
- evidence references and policy version.

The agent may not execute the proposal.

## 2. Validation

The control plane rejects proposals with unknown fields, missing required fields, disallowed actions, unapproved targets, invalid data classification, expired task leases, budget overruns or active kill switches. Validate with strict schemas; do not silently coerce malformed values.

## 3. Freeze and approval

Canonicalize the complete proposal and calculate SHA-256. Persist the frozen payload and hash. Show the human approver the actual content, recipient, account, environment, amount, fees, schedule and irreversible effects. The approval decision references that exact hash and expires after a short configured interval.

A human must approve each R3/R4 action. Batch approval is prohibited unless every individual payload is displayed and separately addressable. R4 requires explicit approval plus independent verification and a documented rollback or compensation plan.

## 4. Execute once

The control plane issues a one-use execution grant bound to the approved hash, adapter, action, target and idempotency key. The adapter verifies the grant and its own narrow permissions. It rejects expired, reused, mismatched or revoked grants.

If the adapter times out, do not blindly retry. Query the destination to determine whether the action already occurred. Retry only with the same idempotency key when the destination's semantics guarantee deduplication.

## 5. Verify and close

A separate verifier checks destination state or authoritative evidence against expected outcome. Store evidence references and result. If verification fails or is ambiguous, mark `blocked` or `failed`, activate the relevant pause if necessary, and notify the operator through an approved internal channel.

## 6. Examples

- Draft a prospect email: R1, automatic, private artifact only.
- Send that exact email: R3, exact recipient and body approval required.
- Draft a social post: R1.
- Publish the post: R3, exact account, content and schedule approval required.
- Create a test branch: R2 only when repository scope explicitly allows it.
- Merge to main or deploy production: R4, prohibited by default and never automated under this blueprint.
- Research hosting options: R0/R1.
- Create a paid hosting account or incur charges: R3/R4 depending on amount and terms; explicit approval required.

## 7. Required audit record

Record proposal ID, task ID, actor, approver, action, target, environment, payload hash, policy version, decision time, expiry, execution grant ID, idempotency key, adapter response reference, verification evidence and final state. Redact secrets and minimize personal data.
