# Memory architecture

## Memory is not one undifferentiated transcript

Use three layers with different trust and retention rules:

1. **Operational state (database):** tasks, approvals, costs, experiments, artifacts and audit events. This is authoritative for workflow status.
2. **Curated shared knowledge (versioned files):** approved business facts, product positioning, policies, customer problem patterns and reusable playbooks. Every item has source/provenance and review date.
3. **Agent-local session memory (runtime):** short-lived context and working notes for an individual agent. It is not the source of truth for approvals, spend or task status.

## Sharing rules

- Shared knowledge is explicitly published to a shared read-only knowledge folder after review.
- Agent workspaces remain separate; no implicit transcript sharing.
- The orchestrator receives only task artifacts and approved summaries from specialists.
- Do not copy raw personal data, secrets, credentials, customer transcripts or restricted production data into shared memory.
- Every memory item records source, owner, created/updated date, classification, retention rule and confidence.
- Stale or conflicting memory is flagged for review, not silently overwritten.

## OpenClaw implications

OpenClaw maintains separate workspaces and session stores per agent. Cross-agent transcript access is not a reliable shared-memory design. The starter config restricts session visibility to the spawned task tree and disables ordinary agent-to-agent messaging. A shared knowledge folder should be mounted read-only into each sandbox only after the sandbox bind paths and access model are verified.

## Memory lifecycle

Capture -> classify -> source-check -> review -> publish to shared knowledge -> periodic freshness check -> archive/expire.

Business OS database records remain authoritative for task and approval state. An LLM summary must never override the database state machine.
