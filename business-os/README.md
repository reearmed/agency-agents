# Business OS — guarded, multi-revenue operating system

Status: **blueprint / not deployed**  
Repository: `reearmed/agency-agents`  
Implementation branch: `business-os/blueprint`

Business OS turns selected Agency Agents specialists into a governed operating system for researching, building, marketing and operating multiple revenue streams. It is an orchestration design, not a claim that this repository itself runs agents continuously.

## Business portfolio

1. **NOREVYO SaaS — primary asset.** Improve activation, conversion, retention and support. Treat its existing production systems as protected.
2. **AI automation services — cash-flow experiment.** Package narrowly scoped automation outcomes for small businesses; sell only after a validated offer and delivery process exist.
3. **Digital products — low-overhead experiment.** Build reusable templates, playbooks and small tools from validated customer problems. No speculative inventory or paid traffic by default.

One primary execution bet at a time. Research can cover all three; active build capacity is deliberately constrained.

## What is included

- [Architecture](ARCHITECTURE.md): components, data flow, control plane and runtime.
- [Agent roster](AGENT_ROSTER.md): selected source agents and their Business OS responsibilities.
- [Autonomy policy](AUTONOMY.md): permissions, approval gates and stop conditions.
- [Revenue workflows](REVENUE_WORKFLOWS.md): repeatable operating cycles.
- [Data and security](DATA_SECURITY.md): isolation, secrets, privacy and retention.
- [Deployment runbook](DEPLOYMENT_RUNBOOK.md): staged path from local dry-run to a guarded pilot.
- [Configuration contract](config/system.yaml): intended runtime settings; placeholders only.
- [Agent prompts](agents/): tailored role instructions for this operating system.

## Operating principle

**Research and prepare autonomously; commit, publish, spend, contact, transact or change production only under explicit authorization.** Every task has an owner, purpose, evidence, risk class, approval state and audit record.

## Not yet live

No scheduler, agent runtime, database, credentials, integrations, deployment or background job is provisioned by these documents. Do not paste production secrets into this repository. Follow the runbook and test each integration with least privilege before enabling any live workflow.
