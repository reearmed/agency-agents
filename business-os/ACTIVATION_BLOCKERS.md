# Activation blockers — what is required before this runs continuously

This repository branch contains the design and agent instructions. It does not itself host an agent process.

## External prerequisites

1. **Runtime selection:** choose one compatible always-on agent runtime and verify its isolation, job execution, tool permissions, audit and recovery capabilities.
2. **Hosting:** provision an isolated non-production worker environment. The owner's Mac can be used for development, but cannot guarantee 24/7 uptime when sleeping or offline.
3. **Database and queue:** provision a new Business OS database and durable queue. Do not reuse NOREVYO production Supabase or credentials.
4. **Model provider:** choose a reasoning model and fallback, set token ceilings and provider spend limits. A small local model may classify or route tasks but must not be the sole strategic reasoning model.
5. **Secret management:** create scoped credentials only after selecting the integrations. No credentials belong in this repository.
6. **Tool adapters:** implement the tool gateway and enforce `config/tool-permissions.yaml` in code. Prompt instructions alone are not a security boundary.
7. **Observability:** configure logs, traces, spend tracking, alerts, backups and tested global pause.
8. **Install validation:** use the upstream selective install list and installer dry-run. Confirm paths before writing to any local agent configuration.
9. **Pilot data:** use synthetic data first, then public research and approved aggregate read-only metrics. No production customer records.
10. **Operator acceptance:** review the security test results and explicitly authorize any live integration or external action.

## Current state

- Repository blueprint: created on `business-os/blueprint`.
- Runtime: not selected or provisioned.
- Database/queue: not provisioned.
- Integrations/credentials: not connected or authorized by this blueprint.
- Schedules: disabled.
- External actions: approval-gated or prohibited.
- Production changes: prohibited.

## Definition of done for initial pilot

The system is considered operational only after the acceptance criteria in `DEPLOYMENT_RUNBOOK.md` and `TEST_PLAN.md` pass in an isolated environment and a read-only pilot completes successfully.
