# Activation blockers — what is required before this runs continuously

This repository branch contains the design and agent instructions. It does not itself host an agent process.

## External prerequisites

1. **Runtime validation:** OpenClaw is the proposed first runtime; install it in an isolated environment and validate the pinned release, sandbox backend, tool permissions, audit and recovery capabilities before enabling jobs.
2. **Hosting:** provision an isolated non-production worker environment. The owner's Mac can be used for development, but cannot guarantee 24/7 uptime when sleeping or offline.
3. **Database and queue:** provision a new Business OS database and durable queue. Do not reuse NOREVYO production Supabase or credentials.
4. **Model provider:** choose a reasoning model and fallback, set token ceilings and provider spend limits. A small local model may classify or route tasks but must not be the sole strategic reasoning model.
5. **Secret management:** create scoped credentials only after selecting the integrations. No credentials belong in this repository.
6. **Tool adapters:** implement the control plane and adapters described in [CONTROL_PLANE_SPEC.md](CONTROL_PLANE_SPEC.md). Enforce `config/tool-permissions.yaml` in code. Prompt instructions and OpenClaw workspace separation alone are not a security boundary.
7. **Approval enforcement:** implement [EXECUTION_PROTOCOL.md](EXECUTION_PROTOCOL.md), including canonical payload hashing, single-use grants, idempotency, expiry and independent verification. No agent may call a consequential adapter directly.
8. **Spend and pause controls:** implement task/monthly budgets, reservations, reconciliation, global and scoped kill switches, and durable audit logging. Missing policy/audit services must block external writes.
9. **Observability and recovery:** configure logs, traces, spend tracking, alerts, backups and tested global pause. Complete [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) recovery drills.
10. **Install validation:** use the upstream selective install list and installer dry-run. Confirm paths before writing to any local agent configuration.
11. **Pilot data:** use synthetic data first, then public research and approved aggregate read-only metrics. No production customer records.
12. **Operator acceptance:** pass every critical check in [TESTS_AND_ACCEPTANCE.md](TESTS_AND_ACCEPTANCE.md), review evidence, and explicitly authorize any live integration or external action.

## Current state

- Repository blueprint: created on `business-os/blueprint`.
- Runtime: OpenClaw proposed; not installed or provisioned.
- Database/queue: not provisioned.
- Control plane: specification only; no enforcement service exists.
- Integrations/credentials: not connected or authorized by this blueprint.
- Schedules: disabled.
- External actions: approval-gated or prohibited.
- Production changes: prohibited.

## Definition of done for initial pilot

The system is operational only after the control plane is implemented, all critical acceptance tests pass in an isolated environment, restore and incident drills succeed, and a read-only pilot completes without unauthorized writes or spend-limit breaches. Passing documentation review alone is not operational readiness.
