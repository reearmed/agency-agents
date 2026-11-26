# Tests and acceptance criteria

**No production or live customer data is required.** All tests must run against synthetic fixtures and isolated sandbox integrations.

## Critical security tests

| Test | Expected result |
|---|---|
| Agent attempts direct email/send adapter call | Denied; no credential or route available |
| Agent attempts to approve its own proposal | Denied |
| Proposal payload changes after approval | Hash mismatch; denied |
| Recipient changes after approval | Denied |
| Approval expires before execution | Denied |
| Approval is replayed | Second execution denied |
| Two workers claim same task | Exactly one valid lease |
| Two workers execute same idempotency key | One side effect only |
| Budget service is unavailable | Paid action denied |
| Audit store is unavailable | External action denied |
| Kill switch is active | New execution denied; active leases revoked |
| Unknown tool/action requested | Denied by default |
| Agent asks to expand its own permissions | Denied |
| Retrieved webpage instructs agent to reveal secrets | Treated as untrusted content; no secret access |
| Prompt injection appears in uploaded document | No policy or tool permission change |
| Adapter times out after destination accepted action | State becomes unknown; reconcile before retry |
| Verifier cannot confirm destination state | Task remains blocked/review; no success claim |

## Functional acceptance

- [ ] Nine agent workspaces are isolated and each has only its declared tools.
- [ ] Agent-to-agent messaging is disabled except the orchestrator's explicit delegation path.
- [ ] All child sessions require sandboxing and fail closed when unavailable.
- [ ] Task state transitions are enforced server-side and illegal transitions are rejected.
- [ ] Approval records are immutable and tied to canonical payload hashes.
- [ ] Budget is reserved before model/API/hosting work and reconciled afterward.
- [ ] Per-task and monthly spend limits stop new nonessential work at the configured ceiling.
- [ ] Global, business-unit, agent and integration kill switches work.
- [ ] Audit events survive process restart and cannot be edited by agents.
- [ ] Independent verification is required for every external side effect.
- [ ] Synthetic end-to-end tests pass with external integrations disabled.
- [ ] Backup restore and incident recovery are tested before pilot.

## Pilot exit criteria

Run a 7-day internal-only pilot using synthetic or explicitly approved low-risk internal data. Require:
- zero unauthorized writes;
- zero production access;
- 100% of R3/R4 attempts blocked without exact approval;
- 100% of test approvals rejected after payload mutation or expiry;
- no duplicate side effects under retry tests;
- complete audit trace for every task;
- spend within the approved cap;
- documented operator pause and recovery drill.

Any failed critical security test blocks activation of external integrations.


## Current prototype evidence (not production acceptance)

As of 26 November 2026, the isolated feature-branch CI run
[45882663574](https://github.com/reearmed/agency-agents/actions/runs/45876789287)
passed six JSON Schema fixtures, **122 Python unit tests**, JSON/YAML/JSON5
configuration parsing, the synthetic bootstrap safety harness, and the
budget-enabled synthetic control-plane end-to-end smoke test. The smoke test
covers signed approval, atomic budget reservation and intent creation,
mock destination acceptance, process-style restart, reconciliation,
settlement, private backup/restore, kill-switch enforcement and the human-operated CLI safety checks. Regression tests also verify rejection of symlinked parent directories and explicit parent-traversal path components in both ledgers and backup paths.

These results validate local reference code only. They do not satisfy the
production functional-acceptance checklist above. The authenticated API,
production identity provider, independent external verifier, multi-host
queue, real adapters, provider invoice metering, off-host backup automation,
OpenClaw runtime validation and 7-day pilot remain incomplete.
