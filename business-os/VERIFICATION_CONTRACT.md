# Independent verification contract

**Status: local verification boundary and synthetic tests only. No destination connector, verifier service, or production evidence source is deployed.**

## Trust separation

The executor's success response is not proof of success. The independent verifier must authenticate as a separate service principal, query the authoritative destination using the exact idempotency key, and validate destination-origin evidence before any task can become terminal or any budget can settle.

The local `control_plane/independent_verifier.py` contract enforces:
- a verified principal with `business-os:verification:record` scope and `business-os:independent-verifier` role;
- verifier subject distinct from both requester and executor identities;
- exact expected execution fields: task, adapter, action, target, environment, idempotency key, payload hash and dispatch timestamp;
- a separately injected destination evidence reader;
- a configured trusted source identifier;
- exact evidence-field schema and match against the approved execution;
- terminal `succeeded` or `failed` outcome only; missing or inconclusive evidence is rejected;
- timezone-aware observation timestamps, bounded age and no pre-dispatch/future evidence;
- a separate evidence authenticator that must return exactly `True`;
- a SHA-256 digest of canonical evidence metadata for audit reference.

The verifier does not accept a receipt returned by the executor as its evidence source. The evidence reader must use a distinct destination read credential or API path. The authenticator must validate the destination's signed receipt, authenticated API response or other authoritative proof; a test callback returning `True` is not production authentication.

## Evidence record contract

The destination evidence reader must return exactly these fields:

| Field | Meaning |
|---|---|
| `task_id` | Original Business OS task |
| `idempotency_key` | Exact one-use destination idempotency key |
| `adapter`, `action`, `target`, `environment` | Approved integration scope |
| `payload_sha256` | Hash of the frozen approved payload |
| `outcome` | `succeeded` or `failed`; other states remain inconclusive |
| `destination_record_id` | Stable record/transaction ID from the destination |
| `observed_at` | Timezone-aware destination observation timestamp |
| `source_id` | Configured trusted destination source |
| `raw_evidence_sha256` | SHA-256 of the raw evidence material held/verified by the authenticator |

The returned audit digest covers the canonical evidence record, including the raw evidence hash. Raw evidence itself should be stored in a protected evidence store with access controls and retention policy; do not place secrets or unnecessary personal data in audit events.

## Production integration gates

- Authenticate the verifier service through the selected IdP and assign only the internal verifier scope/role.
- Keep verifier credentials and evidence-store access separate from executor credentials.
- Implement destination-specific authoritative lookup and cryptographic/authenticated response validation.
- Bind each evidence record to the original payload hash, action, target, environment, idempotency key and destination record.
- Define source-specific semantics for success, failure, pending, partial completion, refunds, cancellation and eventual consistency.
- Keep ambiguous, stale, unavailable or mismatched evidence in UNKNOWN/review; never infer success.
- Make the verifier write its own audit event under its authenticated principal.
- Test replay, evidence substitution, wrong tenant/account, wrong environment, delayed visibility, partial effects and provider outages.

The current module is a reusable contract only. It is not wired into `durable_execution.py`, because the current gateway and verifier are intentionally mock-only. Do not connect real adapters until the independent verifier, authenticated API, multi-host state store, operator controls and recovery drills have been implemented and reviewed.
