# Incident response and recovery

## Severity levels

- **SEV-1:** unauthorized production write, data exposure, credential compromise, unapproved external communication/payment, or inability to stop a harmful workflow.
- **SEV-2:** suspected policy bypass, repeated adapter failures, audit gaps, unexpected spend, or sandbox escape concern.
- **SEV-3:** isolated non-sensitive task failure, stale source, or recoverable internal artifact issue.

## Immediate containment

1. Activate global pause. If the control plane is unavailable, stop the runtime and revoke adapter credentials at the provider.
2. Disable affected integration grants and revoke short-lived execution leases.
3. Stop schedules and queued jobs; do not delete evidence or logs.
4. Preserve task IDs, payload hashes, timestamps, adapter request IDs and relevant audit events.
5. Determine whether an external side effect occurred. Do not assume timeout means failure.
6. Escalate to the human operator. No agent may declare an incident resolved.

## Investigation

- Identify first affected task, agent, model, runtime version, integration and policy version.
- Establish the exact action, target, data classification and payload hash.
- Check audit completeness, approval validity, idempotency and destination state.
- Determine whether credentials, customer data or personal information were exposed.
- Identify root cause and scope; treat generated explanations as hypotheses until corroborated.

## Recovery

- Rotate compromised credentials at the provider; never paste new secrets into chat or Git.
- Restore from a known-good backup where required and verify integrity.
- Patch the policy or adapter in an isolated branch and test against the critical test suite.
- Re-enable one integration at a time, initially read-only.
- Require operator approval before resuming any external write capability.
- Document impact, timeline, containment, remediation and follow-up controls.

## Notification and legal review

Follow applicable contractual, privacy, regulatory and provider notification obligations. Do not let an agent independently determine whether a reportable breach occurred or send notices. Escalate to the responsible human/legal/privacy reviewer.

## Recovery objectives

Set and test explicit RPO/RTO before pilot. Backups must be encrypted, access-controlled, isolated from runtime credentials and periodically restore-tested. A backup that has never been restored is not a validated recovery mechanism.
