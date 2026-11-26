# Deployment and activation runbook

Status: **not deployed**. This checklist is the safe path to a working pilot.

## Phase 0 — repository preparation (this branch)

- [x] Create isolated `business-os/blueprint` branch.
- [x] Define architecture, agent roster, autonomy, workflows and security model.
- [ ] Review generated docs and source agent links.
- [ ] Add integration-specific configuration only after the runtime is selected.
- [ ] Run repository checks and inspect the final diff.

## Phase 1 — choose and provision an isolated runtime

Decision criteria: supported agent format, reliable background worker, tool sandboxing, auditability, model/provider flexibility, Canadian data residency options, backup/restore, operator access and total cost.

- Select one runtime/orchestrator; do not install every agent or multiple competing runtimes.
- Provision a dedicated non-production environment and a new isolated database.
- Configure private network, TLS, authentication, secret manager, backups and monitoring.
- Create separate development credentials with read-only scopes wherever possible.
- Set a hard monthly budget and per-task limits before enabling jobs.

## Phase 2 — local dry-run and agent installation

From a trusted clone of this fork, inspect the installer's help and target paths first. Generate only the required format for the chosen runtime. Use selective agent installation and `--dry-run`; do not use an install-all command. Confirm the target directory and back up existing configuration before any local write.

The upstream installer can write to user-level AI tool configuration directories. A dry-run is mandatory. Do not run installers on production hosts.

## Phase 3 — offline test

- Run orchestrator with mock tools and synthetic data only.
- Verify each role returns the required structured output.
- Test prompt injection, malformed tool responses, timeouts, retries and duplicate-job idempotency.
- Verify approvals are required for every R3/R4 action.
- Confirm that unapproved writes are denied and logged.
- Validate monthly budget stop and global pause switch.

## Phase 4 — read-only pilot

- Enable only public research and approved read-only analytics.
- No email send, publication, payments, ad spend, production writes or customer-data access.
- Run manually for at least one review cycle.
- Measure task success, factual error rate, cost per report, latency and operator review burden.

## Phase 5 — gated actions

Enable one action at a time. Require exact payload approval, recipient/target preview, idempotency, audit event and rollback plan. Start with a reversible internal action; external communication and financial actions remain approval-gated.

## Rollback

1. Pause scheduler and workers.
2. Revoke the affected integration token.
3. Preserve logs and evidence; do not delete incident records.
4. Roll back the last approved deployment or restore isolated Business OS database backup.
5. Verify no external side effect occurred twice.
6. Conduct incident review before resuming.

## Acceptance criteria for “working”

- Background jobs run on an always-on host independent of the user's sleeping Mac.
- Every run has task ID, logs, cost, status and artifact.
- Global pause and per-integration revocation are tested.
- Approval enforcement is tested with negative cases.
- Data is isolated from NOREVYO production.
- Backups restore successfully.
- Read-only pilot produces useful reports within the approved budget.
- No unresolved critical security or privacy findings.
