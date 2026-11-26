# Business OS — guarded, multi-revenue operating system

Status: **blueprint with local safety prototype; not deployed**  
Repository: `reearmed/agency-agents`  
Implementation branch: `business-os/blueprint`

Business OS turns selected Agency Agents specialists into a governed operating system for researching, building, marketing and operating multiple revenue streams. The repository is not itself a continuously running agent service.

## Business portfolio

1. **NOREVYO SaaS — primary asset.** Improve activation, conversion, retention and support. Treat its existing production systems as protected.
2. **AI automation services — cash-flow experiment.** Package narrowly scoped automation outcomes for small businesses; sell only after a validated offer and delivery process exist.
3. **Digital products — low-overhead experiment.** Build reusable templates, playbooks and small tools from validated customer problems. No speculative inventory or paid traffic by default.

One primary execution bet at a time. Research can cover all three; active build capacity is deliberately constrained.

## What is included

- [Architecture](ARCHITECTURE.md): components, data flow, control plane and runtime.
- [Agent roster](AGENT_ROSTER.md): selected source agents and their Business OS responsibilities.
- [Autonomy policy](AUTONOMY.md): permissions, approval gates and stop conditions.
- [Control plane specification](CONTROL_PLANE_SPEC.md): enforcement boundary, identity, idempotency, budget and fail-closed behavior.
- [Execution protocol](EXECUTION_PROTOCOL.md): exact-payload approval and one-time execution lifecycle.
- [Security acceptance tests](TESTS_AND_ACCEPTANCE.md): critical bypass, replay, budget, kill-switch and pilot tests.
- [Implementation backlog](IMPLEMENTATION_BACKLOG.md): sequenced infrastructure, safety and revenue milestones.
- [Revenue workflows](REVENUE_WORKFLOWS.md): repeatable operating cycles.
- [Data and security](DATA_SECURITY.md): isolation, secrets, privacy and retention.
- [Memory architecture](MEMORY_ARCHITECTURE.md): operational state, curated shared knowledge and agent-local memory.
- [Database reference](database/README.md): private isolated schema and verification queries.
- [OpenClaw runtime starter](runtime/openclaw/README.md): guarded multi-agent configuration and workspace bootstrap.
- [Hosting decision](runtime/HOSTING_DECISION.md): proposed Toronto VPS footprint and cost estimate.
- [Deployment runbook](DEPLOYMENT_RUNBOOK.md): staged path from local dry-run to a guarded pilot.
- [Configuration contract](config/system.yaml): intended runtime settings; placeholders only.
- [Agent prompts](agents/): tailored role instructions for this operating system.

## Local safety prototype

The `control_plane/README.md` documents the isolated tests and limitations. The `contracts/` directory contains strict JSON Schemas and valid/invalid fixtures. The `control_plane/` package contains in-memory guardrails, a transactional SQLite reference store, signed short-lived approval grants, and a durable mock-only execution outbox. The outbox commits grant consumption and the immutable execution intent in one transaction, supports single-use worker claims and bulk stale-lease recovery, preserves ambiguous outcomes as `UNKNOWN`, and records state transitions in an append-only hash-chained event log. A persistent kill switch blocks new grants, intent creation, worker claims and synthetic destination acceptance. The durable mock destination stores receipts across gateway restarts and enforces idempotency-key/payload matching. The feature-branch GitHub Actions workflow validates schemas and runs the unit-test suite.

**This is not a production control plane.** SQLite is a single-host local prototype, not a multi-host service. There is no authenticated network API, production identity provider, independently authenticated verifier, hosted backup, real adapter, destination idempotency, alerting or external action. The identity-verifier callback and mock verifier are test seams, not production trust anchors. The audit hash chain is tamper-evident, not tamper-proof against a privileged database operator. The prototype is not authorization to send, publish, spend, transact, or touch production.

## Operating principle

**Research and prepare autonomously; commit, publish, spend, contact, transact or change production only under explicit authorization.** Every task has an owner, purpose, evidence, risk class, approval state and audit record.

## Not yet live

No scheduler, agent runtime, database, credentials, integrations, deployment, durable control-plane service or background job is provisioned. The reference database schema is not an applied migration. The OpenClaw config is an example and has not been runtime-validated. Follow the runbook and test each integration with least privilege before enabling any live workflow.
