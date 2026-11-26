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

Do not declare the system production-ready based only on unit tests. Require negative permission tests, restore test, operator walkthrough and a bounded read-only pilot.
