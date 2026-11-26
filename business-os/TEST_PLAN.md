# Business OS validation plan

## Required pre-pilot tests

| Test | Expected result |
|---|---|
| Missing/ambiguous permission | Deny and log |
| Prompt injection in webpage/email | Treat as untrusted; no policy override |
| Agent requests secret | Deny; redact and alert |
| R3 action without approval | Deny |
| Payload modified after approval | Invalidate approval and deny |
| Expired approval | Deny |
| R4 action without independent reviewer | Deny |
| Duplicate webhook/job retry | One side effect only |
| Monthly budget reaches hard limit | Stop nonessential new jobs |
| Tool returns malformed data | Validate schema; fail safely |
| Worker crashes mid-task | Recover lease; resume safely or mark failed |
| Business unit attempts cross-tenant read | Deny and alert |
| Global pause enabled | Stop dispatch and external writes |
| Kill switch audit write fails | Persistent stop remains engaged |
| Process restarts after intent persistence but before claim | Recover READY intent exactly once |
| Worker lease expires during dispatch | Move to UNKNOWN; never blindly re-dispatch |
| Destination accepts then worker times out | Reconcile persistent destination receipt before terminal state |
| Intent proposal or audit event is tampered with | Integrity verification fails |
| Local SQLite backup is created and reopened | SQLite, foreign-key, audit-chain, intent, budget and destination integrity checks pass |
| Budget reservation is included in signed payload | Grant consumption, intent and reservation commit atomically |
| Monthly or per-task budget cap exceeded | Grant, intent and reservation all roll back; no destination call |
| Budget settlement requested before reconciliation | Denied until terminal outcome and evidence exist |
| Budget release requested without verified no-effect | Denied; release only follows reconciled FAILED outcome |
| Budget cap or reservation rows are tampered with | Immutable triggers block ordinary edits; integrity verification detects privileged tampering |
| Bootstrap dry-run/apply/re-run | No dry-run writes; private workspaces; no overwrite; unsafe paths rejected |
| Production endpoint write attempted | Deny and alert |
| Secret appears in log/artifact | Redact, quarantine artifact and rotate secret |

## Quality metrics

- Task completion rate by workflow and agent.
- Factual correction rate after independent review.
- Approval rejection and edit rate.
- Duplicate side-effect count (target zero).
- Cost per successful task and cost per qualified opportunity.
- Mean time to detect and contain incidents.
- Queue delay and worker availability.

The CI workflow also parses the JSON/YAML/JSON5 runtime configuration, checks bootstrap shell syntax, and exercises the bootstrapper against a synthetic repository (dry-run, apply, file permissions, no-overwrite, relative path, symlink and broad-permission rejection). Do not declare the system production-ready based only on unit tests. Require authenticated permission tests, off-host restore test, operator walkthrough and a bounded read-only pilot.
