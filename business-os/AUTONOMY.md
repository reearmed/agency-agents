# Autonomy and approval policy

**Default posture: guarded.** If an action is not explicitly allowed below, it is not allowed.

## Risk tiers

| Tier | Examples | Permission |
|---|---|---|
| R0 — Read | Read public sources, approved internal docs, authorized analytics | Automatic within source allow-list |
| R1 — Prepare | Research, summarize, calculate, draft, create reports and code in sandbox | Automatic; outputs remain private |
| R2 — Internal reversible | Create issue/branch, update non-production project board, write to Business OS staging DB | Allowed only when integration scope and project policy explicitly enable it |
| R3 — External or consequential | Send email/DM, publish content, contact a prospect, change ad settings, purchase, subscribe, create customer-facing offer | Exact human approval required |
| R4 — Critical | Production deployment, production schema/data mutation, customer billing/refund, credential rotation, legal commitment, destructive action | Explicit approval per action and independent verification; otherwise prohibited |

## Hard prohibitions

- No changes to NOREVYO production, Supabase production, Stripe live configuration, Resend sending configuration, DNS, Vercel production or production customer data by default.
- No merge to `main`, no auto-merge, no auto-deploy and no branch-protection changes.
- No payments, refunds, subscriptions, advertising spend or purchases without approval.
- No sending email, SMS, social messages or prospect outreach automatically.
- No scraping behind authentication, bypassing access controls, evading platform limits or collecting sensitive personal data without a documented lawful basis.
- No storing secrets, API keys, access tokens, passwords or customer data in Git, agent prompts, logs or generated reports.
- No autonomous policy edits, permission escalation, tool installation or new integration grants.

## Approval object

An approval is valid only for one exact action and payload. It must contain:
- action type and target system/environment;
- exact content or diff, amount/currency if financial;
- recipient/audience and source/purpose if communication;
- expected effect, rollback plan and risk tier;
- approver identity, timestamp and expiry;
- immutable payload hash.

Changing the content, recipient, amount, target, environment or payload invalidates the approval. Expired or ambiguous approvals fail closed.

## Spend controls

- Track model, API, hosting and third-party spend by project and task.
- Configure monthly and per-task ceilings before enabling scheduled work.
- Alert at 50%, 75% and 90%; stop new nonessential jobs at 100%.
- No automatic budget increases or paid plan upgrades.
- Start with a conservative pilot ceiling and raise it only after reviewing cost per qualified opportunity and cost per delivered outcome.

## Stop conditions

Immediately pause affected workflow on: suspected data leak, unexpected production write, unapproved external send, repeated tool failure, spend-limit breach, source provenance failure, unresolved security alert, opt-out/suppression conflict or uncertain authorization.

## Human control

Provide a global pause switch, per-business-unit pause, per-integration revoke, job cancellation and audit export. Operator can reject, edit or expire any pending action. A model response is never itself an approval.
