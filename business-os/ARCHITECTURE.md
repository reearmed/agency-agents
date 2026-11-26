# Business OS architecture

## 1. Design goals

- Turn the Agency Agents markdown specialists into reusable roles under one accountable orchestrator.
- Support multiple revenue streams without allowing agents to create uncontrolled parallel projects.
- Run durable, observable jobs with retries, budgets, approvals and audit trails.
- Keep business intelligence separate from NOREVYO production customer data.
- Be provider-neutral: agent prompts are portable; runtime, model, database and scheduler are replaceable.
- Fail closed when identity, permissions, spend limits, consent or approval state is uncertain.

## 2. Logical architecture

```text
Owner / Operator
  | requests, approvals, stop switch
  v
Control plane (policy + task registry + approvals)
  | creates scoped jobs
  v
Orchestrator
  | plans, delegates, checks budgets and deadlines
  +--> Research & market intelligence
  +--> Revenue operations (NOREVYO / services / products)
  +--> Product & engineering
  +--> Marketing & sales preparation
  +--> Finance, analytics, compliance, security
  |
  v
Tool gateway (allow-listed, scoped capabilities)
  | read APIs / sandbox / draft queues / approval-gated actions
  +--> GitHub development branch
  +--> CRM / prospect research store
  +--> Email draft provider (send disabled by default)
  +--> Analytics (read-only)
  +--> NOREVYO systems (read-only, separately authorized)
  |
  v
Business OS data plane
  - PostgreSQL: jobs, approvals, run logs, metrics, business entities
  - Object storage: generated reports and artifacts
  - Secret manager: credentials (never stored in DB prompts or Git)
  - Queue + scheduler: durable jobs, leases, retries
  - Observability: traces, logs, spend and failure alerts
```

## 3. Runtime services

| Service | Responsibility | Initial mode |
|---|---|---|
| API/control plane | Authenticate operator, accept tasks, manage approvals | Private |
| Orchestrator worker | Plan, select agents, enforce policy | Single worker |
| Queue/scheduler | Durable execution, retries, recurring schedules | Disabled until pilot |
| Agent executor | Run one bounded specialist task per job | Sandboxed |
| Tool gateway | Enforce per-tool allow-list and scopes | Deny by default |
| Postgres | Jobs, state, evidence, audit and metrics | New isolated database |
| Artifact store | Reports, drafts, generated code and exports | Private |
| Observability | Logs, traces, error and cost metrics | Required before pilot |

A single worker and queue are sufficient for the first pilot. Do not start with a distributed swarm. Scale concurrency only after measured queue latency, task success and cost justify it.

## 4. Task lifecycle

1. **Intake:** record requester, objective, business unit, expected output, deadline and data classification.
2. **Triage:** orchestrator assigns risk tier, checks duplicate work, budget and required approvals.
3. **Plan:** break work into bounded subtasks and choose the smallest qualified agent team.
4. **Execute:** each agent receives only its task context and allow-listed tools.
5. **Verify:** independent reality-checker validates claims, links, tests, calculations and artifact completeness.
6. **Stage:** save drafts and evidence; do not publish or transact.
7. **Approve:** operator reviews a human-readable diff/preview and authorizes the exact action.
8. **Commit:** tool gateway executes only the approved action, with idempotency key and audit event.
9. **Learn:** record outcome and update metrics; never silently change policy or permissions.

## 5. Data model (minimum viable)

- `business_units`: NOREVYO, automation-services, digital-products.
- `projects`: objective, owner, status, priority, budget ceiling.
- `tasks`: input, output schema, assigned agent, risk tier, status, due date.
- `task_events`: append-only lifecycle and tool-call events.
- `approvals`: exact action, payload hash, approver, expiry, decision.
- `artifacts`: URI, checksum, classification, provenance.
- `contacts`: lawful source, purpose, consent/permission basis, suppression state, retention date.
- `experiments`: hypothesis, cohort, metric, guardrail, start/end and result.
- `cost_events`: provider, model, tokens/units, amount, currency, project and task.
- `integration_grants`: tool, scope, environment, expiry and status (never secret values).

Use tenant/business-unit identifiers on every business record. Enforce row-level authorization in the application and database. Keep credentials in a secret manager, not in rows.

## 6. Execution patterns

- Prefer deterministic code for arithmetic, scheduling, validation, billing reconciliation and state transitions.
- Use LLM agents for research synthesis, drafting, planning, classification and code assistance.
- Use structured input/output schemas for all tool-using agents.
- Require source URLs or artifact references for external factual claims.
- Set per-job timeout, maximum tool calls, model-token ceiling and retry ceiling.
- Use idempotency keys for every external write; retries must not duplicate emails, charges or records.
- Never allow an agent to grant itself tools, elevate its role or approve its own action.

## 7. Deployment topology

**Recommended pilot:** isolated managed app/worker and isolated Postgres in a Canadian region where available, private network access, encrypted backups, TLS, secret manager and external uptime monitoring. A Mac development workstation is not the 24/7 production runtime; sleep, network changes and local disk availability make it unsuitable as the only always-on host.

Do not select a hosting vendor until region, data-processing terms, recovery, pricing and access controls are checked. Keep the deployment reproducible with infrastructure-as-code and separate dev/staging/prod environments.
