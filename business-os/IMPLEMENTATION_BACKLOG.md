# Implementation backlog

Status: **local safety prototype added; production-grade control plane and runtime remain unimplemented**. A prototype or passing unit test does not complete an infrastructure-dependent backlog item.

## Release 0 — safe foundation (P0)

| ID | Deliverable | Current status | Remaining acceptance evidence |
|---|---|---|---|
| OS-001 | Pin OpenClaw version and runtime image by immutable digest | Not started | Reproducible build and software inventory |
| OS-002 | Provision isolated non-production host and private network | Approval required | Host inventory, firewall review, backup test |
| OS-003 | Implement control-plane API and authenticated operator identity | Not started | AuthN/AuthZ tests; no agent can call privileged routes |
| OS-004 | Implement task state machine with atomic transitions and leases | In-memory state prototype plus local transactional SQLite reference; hosted multi-process state service still not implemented | Durable transactional state, leases, concurrency and invalid-transition tests |
| OS-005 | Implement approval service with canonical payload hash, expiry and single-use grants | Local in-memory and SQLite approval prototypes bind to original proposed task hash and reject replay; authenticated identity/approval service still not implemented | Authenticated human identity, durable single-use grant, expiry/replay/mutation tests |
| OS-006 | Implement idempotent adapter contract and independent verifier | Durable local mock-only outbox atomically couples one-use grant consumption to immutable intent; READY recovery, single-use leases, UNKNOWN handling and mock reconciliation added; no real adapter or independent verifier service | External destination idempotency, authoritative lookup, authenticated verifier and production adapter boundary |
| OS-007 | Implement budget reservation, reconciliation and hard-stop | In-memory cap plus transactional SQLite reservation prototype; no hosted reservation, reconciliation or billing service | Durable reservation/reconciliation and service-unavailable tests |
| OS-008 | Implement append-only audit, alerting and global/scoped kill switches | In-memory fail-closed audit and SQLite append-only/hash-chain audit plus durable local kill-switch prototype; no hosted alerting or scoped kill-switch service | Durable tamper-resistant audit, alerting, scoped switches and pause drills |
| OS-009 | Provision separate Business OS database and durable queue | Approval required | RLS/grant review, restore test, queue retry test |
| OS-010 | Run isolated synthetic end-to-end test suite | Not started | All critical tests pass; evidence attached |

## Local prototype added

- Strict task and approval JSON Schemas with valid and invalid fixtures.
- Standard-library-only reference code for canonical payload SHA-256, immutable proposed-task binding, approval scope/hash/expiry/replay checks, guarded state transitions, idempotency claims, budget cap and fail-closed audit behavior.
- A transactional SQLite reference store with persistent task/approval/idempotency/budget records, BEGIN IMMEDIATE write transactions, append-only audit triggers, a verifiable event hash chain, restrictive file permissions and a kill switch that remains active if audit writing fails.
- Signed HMAC-SHA256 approval grants with exact payload/scope/requester binding, short expiry, two-person approval, injected fail-closed identity verification, constant-time signature comparison and transactional one-use consumption.
- A durable mock-only execution outbox. Consumed-grant insertion and immutable intent creation are atomic in one SQLite transaction. The worker supports READY recovery, bounded single-use claims, stale-lease-to-UNKNOWN handling, no automatic retry, separate mock reconciliation and append-only hash-chained execution events. It rejects non-mock adapters. This is single-host local persistence, not a hosted queue or exactly-once remote execution guarantee.
- The earlier in-memory mock gateway remains as a simple reference. The durable gateway has dedicated tests for atomic grant+intent persistence, READY recovery, timeout-after-commit reconciliation, fail-before-commit reconciliation, stale lease recovery, duplicate idempotency, kill-switch denial, payload substitution, audit integrity and concurrent claims. The expanded suite's hosted CI result must be checked before claiming it passes.
- Terminal success/failure requires a verifier identity and evidence hash; adapter timeouts can remain `unknown` pending reconciliation. These are test-only trust parameters, not authenticated identity or evidence verification.
- Feature-branch CI validates JSON schemas/fixtures and runs the Python unit tests.

These components are local reference implementations and have no external adapters. SQLite persistence is single-host only. They are not production-ready. Earlier hosted GitHub Actions run 45873313366 passed 67 Python unit tests and all four JSON Schema fixtures on the then-current code; run 45873347832 also passed for the subsequent handoff-only commit. The new durable outbox and its added tests were committed afterward; their hosted CI result is pending verification and must not be inferred from the earlier runs.

## Release 1 — internal research and NOREVYO improvement (P1)

| ID | Deliverable | Acceptance evidence |
|---|---|---|
| OS-101 | Install nine tailored workspaces in isolated runtime | Workspace inventory; no pre-existing config overwritten |
| OS-102 | Enable read-only public research and private artifact writing | Tool audit shows no external write tools |
| OS-103 | Add NOREVYO public-site and approved aggregate-metric research workflow | Weekly opportunity report with citations and assumptions |
| OS-104 | Add landing-page, onboarding and support draft workflow | Draft artifacts only; no publishing or customer-data access |
| OS-105 | Add experiment registry with hypothesis, baseline, cost and success metric | Each experiment has owner, stop rule and evidence |
| OS-106 | Run 7-day read-only internal pilot | Zero unauthorized writes; complete task audit; spend within cap |

## Release 2 — first paid offer validation (P2)

Prioritize one service offer rather than launching several revenue streams simultaneously.

1. Research a narrow, expensive small-business workflow problem using public sources.
2. Compare buyer urgency, willingness-to-pay evidence, delivery complexity, privacy risk and competitive alternatives.
3. Draft one fixed-scope AI automation service offer with explicit exclusions and a measurable outcome.
4. Create a sample/demo using synthetic data only.
5. Build a prospect list only from lawful, public business contact sources; minimize personal data and respect suppression/opt-out.
6. Draft outreach privately. Human approval is required for every send and recipient.
7. Track replies, qualified conversations, delivery time, gross margin and refund/support burden.
8. Do not buy ads, subscriptions, leads or data until separately approved.

**Go/no-go:** require evidence of buyer problem and at least a small set of qualified conversations before building a reusable delivery platform or increasing spend.

## Release 3 — digital products (P3)

Convert validated repeated work into templates, checklists or small tools. Build only after evidence of repeated demand. Use private drafts and synthetic examples; human approval for storefront listing, price, claims, refunds and publication.

## Operating cadence after activation

- Daily: queue health, failed jobs, spend, security alerts and pending approvals.
- Weekly: revenue pipeline, NOREVYO funnel, experiments, cost per outcome and next-week priorities.
- Monthly: permission review, integration grant review, restore test, budget review and portfolio allocation.
- Between cycles: agents may research and prepare private artifacts only within configured quotas.

## Decision gates

- No new revenue stream gets active build capacity without portfolio-manager evidence and operator acceptance.
- No external write before OS-005 and OS-006 are implemented and passing in a production-grade isolated control plane.
- No scheduled 24/7 execution before OS-008 and OS-010 pass.
- No customer data until privacy classification, lawful purpose, retention and access controls are reviewed.
- No production NOREVYO integration without a separate explicit scope and per-action authorization.
