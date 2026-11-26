# Implementation backlog

Status: **planned work only**. Items below are not complete until code, tests and evidence exist in an isolated environment.

## Release 0 — safe foundation (P0)

| ID | Deliverable | Dependencies | Acceptance evidence |
|---|---|---|---|
| OS-001 | Pin OpenClaw version and runtime image by immutable digest | Hosting decision | Reproducible build and software inventory |
| OS-002 | Provision isolated non-production host and private network | Operator selects provider/region and approves cost | Host inventory, firewall review, backup test |
| OS-003 | Implement control-plane API and authenticated operator identity | OS-002 | AuthN/AuthZ tests; no agent can call privileged routes |
| OS-004 | Implement task state machine with atomic transitions and leases | OS-003 | Concurrency and invalid-transition tests |
| OS-005 | Implement approval service with canonical payload hash, expiry and single-use grants | OS-003 | Mutation, replay, expiry and recipient-swap tests |
| OS-006 | Implement idempotent adapter contract and independent verifier | OS-003, OS-005 | Duplicate request and timeout reconciliation tests |
| OS-007 | Implement budget reservation, reconciliation and hard-stop | OS-003 | Cap exhaustion and unavailable-budget tests |
| OS-008 | Implement append-only audit, alerting and global/scoped kill switches | OS-003 | Restore, tamper-attempt and pause drills |
| OS-009 | Provision separate Business OS database and durable queue | Operator selects organization/provider and approves cost | RLS/grant review, restore test, queue retry test |
| OS-010 | Run isolated synthetic end-to-end test suite | OS-001 through OS-009 | All critical tests pass; evidence attached |

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
- No external write before OS-005 and OS-006 are implemented and passing.
- No scheduled 24/7 execution before OS-008 and OS-010 pass.
- No customer data until privacy classification, lawful purpose, retention and access controls are reviewed.
- No production NOREVYO integration without a separate explicit scope and per-action authorization.
