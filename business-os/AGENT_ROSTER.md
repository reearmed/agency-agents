# Business OS agent roster

The source of truth for original specialist personas remains the Agency Agents files in this repository. These tailored role cards narrow their authority for Business OS. Install only this roster, not the entire catalogue.

## Exact source files from this fork

These are the upstream specialist definitions selected for the initial runtime install:

| Agent ID | Repository source |
|---|---|
| `agents-orchestrator` | `specialized/agents-orchestrator.md` |
| `project-manager-senior` | `project-management/project-manager-senior.md` |
| `product-sprint-prioritizer` | `product/product-sprint-prioritizer.md` |
| `product-trend-researcher` | `product/product-trend-researcher.md` |
| `marketing-growth-hacker` | `marketing/marketing-growth-hacker.md` |
| `marketing-content-creator` | `marketing/marketing-content-creator.md` |
| `sales-outbound-strategist` | `sales/sales-outbound-strategist.md` |
| `support-finance-tracker` | `support/support-finance-tracker.md` |
| `support-analytics-reporter` | `support/support-analytics-reporter.md` |
| `engineering-backend-architect` | `engineering/engineering-backend-architect.md` |
| `engineering-devops-automator` | `engineering/engineering-devops-automator.md` |
| `security-senior-secops` | `security/security-senior-secops.md` |
| `testing-reality-checker` | `testing/testing-reality-checker.md` |
| `support-legal-compliance-checker` | `support/support-legal-compliance-checker.md` |

The nine tailored Business OS role cards in `business-os/agents/` narrow and adapt these responsibilities to the owner's guarded-autonomy policy. They are not replacements for the upstream source files.

## Command and planning

| Business OS role | Source specialist | Responsibility |
|---|---|---|
| Chief Orchestrator | Agency Agents runbook roster ID `agents-orchestrator`; Business OS implementation: `business-os/agents/00-chief-orchestrator.md` | Intake, task decomposition, delegation, status and escalation |
| Portfolio & Delivery Manager | `project-management/project-manager-senior.md` | Portfolio capacity, milestones, blockers and weekly plan |
| Opportunity Researcher | Research division market/trend researcher | Market sizing, competitor and customer evidence |
| Reality & Evidence Reviewer | `testing/testing-reality-checker.md` | Independent verification; rejects unsupported claims |

## Revenue teams

| Business unit | Core agents | Deliverables |
|---|---|---|
| NOREVYO | Growth Hacker, Content Creator, Analytics Reporter, Product Sprint Prioritizer, Backend Architect, DevOps Automator, SecOps | Funnel diagnosis, product experiments, drafts, backlog and reviewed implementation proposals |
| AI automation services | Outbound Strategist, Growth Hacker, Content Creator, Finance Tracker, Legal Compliance Checker | ICP research, offer design, prospect briefs, proposal drafts, delivery economics |
| Digital products | Opportunity Researcher, Content Creator, Growth Hacker, Analytics Reporter, Finance Tracker | Validated problem briefs, product outline, landing-page draft, experiment readout |

## Shared control specialists

- **Finance & Unit Economics:** source `support/support-finance-tracker.md`. Tracks revenue, costs, margin, runway and spend anomalies. Cannot initiate payments.
- **Analytics & Reporting:** source `support/support-analytics-reporter.md`. Produces source-backed KPI reports; cannot change tracking or dashboards in production.
- **Security & Privacy:** source `security/security-senior-secops.md` plus privacy specialist. Threat models, least privilege, data classification, incident readiness.
- **Legal & Compliance:** source `support/support-legal-compliance-checker.md`. Flags Canadian privacy, anti-spam, consumer and contract risks; not a substitute for qualified legal advice.
- **Engineering:** backend architect and DevOps Automator. Development branch and sandbox only unless separately approved.

## Delegation contract

Every delegated task must include: objective, business unit, task ID, allowed sources, data classification, allowed tools, forbidden actions, output schema, deadline, budget ceiling, acceptance criteria and escalation conditions.

Agents return: summary, evidence, assumptions, risks, recommended next step, artifact references and any approval required. No agent may report a task complete without a verifiable artifact or explicit reason it could not be completed.

## Selection rule

Use one lead agent and no more than three supporting agents per task by default. Add specialists only when the task requires them. The Reality & Evidence Reviewer is independent of the author for externally consequential work.
