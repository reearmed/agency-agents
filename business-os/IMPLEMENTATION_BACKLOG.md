# Implementation backlog

Status: **local safety prototype added; production-grade control plane and runtime remain unimplemented**. A prototype or passing unit test does not complete an infrastructure-dependent backlog item.

## Release 0 — safe foundation (P0)

| ID | Deliverable | Current status | Remaining acceptance evidence |
|---|---|---|---|
| OS-001 | Pin OpenClaw version and runtime image by immutable digest | Not started | Reproducible build and software inventory |
| OS-002 | Provision isolated non-production host and private network | Provider research complete: DigitalOcean Toronto TOR1 US$48/month or Akamai/Linode Toronto ca-central US$48/month for 4 CPU/8 GB; Railway currently has no Canada region; no host provisioned and explicit approval required | Exact checkout quote, host inventory, firewall review, off-host backup test |
| OS-003 | Implement control-plane API and authenticated operator identity | Not started | AuthN/AuthZ tests; no agent can call privileged routes |
| OS-004 | Implement task state machine with atomic transitions and leases | Local transactional SQLite outbox with immutable task intent, bounded worker claims, bulk stale-lease recovery, single-task uniqueness and restart-safe READY recovery; hosted multi-process service not implemented | Authenticated service-side state transitions, multi-host coordination, lease renewal and production concurrency tests |
| OS-005 | Implement approval service with canonical payload hash, expiry and single-use grants | HMAC-signed short-lived grants with exact payload/scope/requester binding, two-person approval, persistent single-use ledger and atomic outbox consumption; identity callback remains a test seam | Production IdP/session validation, roles, grant revocation, key rotation and authenticated approval API |
| OS-006 | Implement idempotent adapter contract and independent verifier | Durable mock-only outbox plus restart-persistent SQLite mock destination; destination accepts only claimed approved intents, enforces idempotency-key/payload matching, and verifies receipts against immutable intents; UNKNOWN and stale leases reconcile without blind retry | Real destination idempotency guarantees, authoritative lookup, authenticated independent verifier and production adapter boundary |
| OS-007 | Implement budget reservation, reconciliation and hard-stop | Per-task and monthly integer-minor-unit budget caps now reserve atomically with signed grant consumption and outbox intent; settlement/release require reconciled terminal evidence; budget changes are audited and integrity-checked | Production invoice metering, hosted reservation service, alerting, multi-host coordination and provider billing reconciliation |
| OS-008 | Implement append-only audit, alerting and global/scoped kill switches | Append-only hash-chained execution events, intent/audit tamper checks, persistent fail-closed local kill switch at grant, claim and mock-destination boundaries, plus verified private SQLite backup helper; no hosted alerting or independently administered switch | External audit sink, alerting, scoped/distributed switches, backup scheduling and restore drills |
| OS-009 | Provision separate Business OS database and durable queue | Supabase Pro published at US$25/month; additional projects start at US$10/month plus compute/usage; separate project not created and explicit approval required | Exact compute/usage quote, RLS/grant review, restore test, queue retry test |
| OS-010 | Run isolated synthetic end-to-end test suite | Local schema/unit/shell/configuration tests and a durable control-plane synthetic E2E smoke test pass in CI; full authenticated runtime E2E remains unimplemented | End-to-end tests across authenticated service, durable queue, budget, mock integrations, multi-process recovery and off-host restore; evidence attached |

## Local prototype added

- Strict task and approval JSON Schemas with valid and invalid fixtures.
- Standard-library-only reference code for canonical payload SHA-256, immutable proposed-task binding, approval scope/hash/expiry/replay checks, guarded state transitions, idempotency claims, budget cap and fail-closed audit behavior.
- A transactional SQLite reference store with persistent task/approval/idempotency/budget records, BEGIN IMMEDIATE write transactions, append-only audit triggers, a verifiable event hash chain, restrictive file permissions and a kill switch that remains active if audit writing fails.
- Signed HMAC-SHA256 approval grants with exact payload/scope/requester binding, short expiry, two-person approval, injected fail-closed identity verification, constant-time signature comparison and transactional one-use consumption.
- A durable mock-only execution outbox. Consumed-grant insertion and immutable intent creation are atomic in one SQLite transaction. The worker supports READY recovery, bounded single-use claims, bulk stale-lease-to-UNKNOWN recovery, no automatic retry, separate mock reconciliation and append-only hash-chained execution events. Intent proposal fields are immutable and tampering is checked against the original audit event. It rejects non-mock adapters.
- A restart-persistent SQLite mock destination with immutable receipts and idempotency-key/payload matching. The persistent kill switch blocks new grants, grant consumption, intent creation, worker claims and destination acceptance; it remains active if its audit write fails. The durable worker checks the external kill-switch callback before and after claiming work.
- A transactional local budget ledger. A signed `_budget` payload carries reservation ID, amount in integer minor units, currency and month; the grant, intent and budget reservation commit atomically. Monthly/per-task caps fail closed; settlement requires a reconciled terminal result and cannot exceed the reservation; release requires a reconciled FAILED/no-effect outcome. Budget events are audit-chained and integrity-checked. No actual model/API invoice metering or hosted billing service exists.
- A private SQLite backup helper using the SQLite backup API. It refuses overwrite, verifies SQLite integrity and foreign keys, restores into a new ledger instance, and checks the execution audit chain, intent integrity and budget integrity. Backup scheduling and off-host restore automation remain unimplemented.
- The earlier in-memory mock gateway remains as a simple reference. The durable gateway has dedicated tests for atomic grant+intent persistence, READY recovery, timeout-after-commit reconciliation, fail-before-commit reconciliation, stale lease recovery, duplicate idempotency, kill-switch denial, payload substitution, audit integrity, private backup/restore and concurrent claims. The latest expanded suite passed 104 Python tests in GitHub Actions run 45876207073, including budget hard-stop, settlement/release, immutability and privileged tamper-detection tests.
- Terminal success/failure requires a verifier identity and evidence hash; adapter timeouts can remain `unknown` pending reconciliation. These are test-only trust parameters, not authenticated identity or evidence verification.
- Feature-branch CI validates JSON schemas/fixtures, JSON/YAML/JSON5 configuration syntax, bootstrap shell syntax, and a synthetic bootstrap harness covering dry-run, apply, private permissions, no-overwrite, relative paths, symlinks and broad-permission rejection; it runs the Python unit tests and `synthetic_e2e.py`, which exercises grant approval, durable execution, process-style restart, reconciliation, private backup/restore and kill-switch enforcement.

These components are local reference implementations and have no external adapters. SQLite persistence is single-host only. They are not production-ready. Hosted GitHub Actions run 45874983027 (run 121, https://github.com/reearmed/agency-agents/actions/runs/45874983027) passed on commit fc3412aad6ab3004dc5f80d87c6ed3eb8e0146fa with all six JSON Schema fixtures and 96 Python unit tests, including durable outbox recovery, kill-switch, tamper detection, destination idempotency and backup/restore tests. The expanded CI run 45875237846 (run 126, https://github.com/reearmed/agency-agents/actions/runs/45875237846) passed JSON/YAML/JSON5 configuration parsing, bootstrap shell syntax, the synthetic bootstrap safety harness, all six schemas and all 96 Python tests. Run 45875537466 (run 136, https://github.com/reearmed/agency-agents/actions/runs/45875537466) passed the synthetic durable control-plane end-to-end smoke test covering grant approval, dispatch, restart, reconciliation, backup/restore and kill-switch enforcement. Run 45876109831 (run 153, https://github.com/reearmed/agency-agents/actions/runs/45876109831) passed the E2E smoke test with an atomic budget reservation, post-reconciliation settlement, backup/restore and kill-switch denial. Run 45876207073 (run 159, https://github.com/reearmed/agency-agents/actions/runs/45876207073) passed the 104-test budget integrity suite. Run 45876406287 (run 163, https://github.com/reearmed/agency-agents/actions/runs/45876406287) passed all 105 Python tests, including concurrent outbox budget reservations; the budget-enabled E2E smoke test also passed in run 45876109831. Run 45876789287 (run 177, https://github.com/reearmed/agency-agents/actions/runs/45876789287) passed all six JSON Schema fixtures, all 105 Python tests, configuration parsing, bootstrap safety harness and the synthetic E2E after moving the budget reservation into the signed task payload schema. Run 45877161008 (run 190, https://github.com/reearmed/agency-agents/actions/runs/45877161008) passed all 109 Python tests and the synthetic E2E with the stricter approved-intent-only destination boundary. Run 45877489366 (run 201, https://github.com/reearmed/agency-agents/actions/runs/45877489366) passed all 115 Python tests, including six local CLI tests for safe database paths, one-time budget configuration, read-only usage, verified backup, persistent kill-switch activation and absence of a clear command.

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
