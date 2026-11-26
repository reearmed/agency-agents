# OpenClaw operator runbook

This is a staged local validation procedure, not an instruction to run unreviewed commands on a production host.

## Before installation

- Use a clean development machine or isolated VPS.
- Check out the `business-os/blueprint` branch.
- As of 26 November 2026, the official OpenClaw docs identify **v2026.11.10** as the latest release. Pin that exact release and its official container image by immutable digest after checking provenance; never deploy a floating `latest` tag.
- Verify the official OpenClaw release and installation instructions.
- Ensure Docker Engine/Desktop is installed and running for agent sandboxing.
- Ensure Python 3 is available; the bootstrap helper uses it to reject symlinked or unsafe destination paths.
- Do not sign the VPS into personal email, browser, password manager or personal cloud accounts.

## Workspace bootstrap

From the repository root:

```bash
bash scripts/bootstrap-business-os-openclaw.sh
```

The default is dry-run. Review every destination path. To create the nine isolated agent workspaces:

```bash
bash scripts/bootstrap-business-os-openclaw.sh --apply
```

The script refuses to overwrite existing workspace files. It copies each tailored role prompt into `SOUL.md`, plus local autonomy and task-contract policies.

## Configuration

1. Back up the existing OpenClaw config before changing it.
2. Review `openclaw.json5.example` against the installed version's current schema.
3. Merge the template into the existing config; do not replace unrelated user settings.
4. Keep the Gateway local/loopback and access it only through SSH or Tailscale.
5. Authenticate a model provider through the official onboarding flow; never commit API keys.
6. Verify sandbox support and inspect the effective tool list for every agent. The example uses an explicit sandbox tool allowlist as a second gate; a tool being allowed globally does not guarantee it is available inside a sandbox.

## Current-version security gates

The example is deliberately restrictive, but JSON5 parsing is not schema validation. On the pinned installation, run `openclaw config schema` and `openclaw config validate` before starting the Gateway. Preserve the generated schema and validation output with the release record. Do not assume the example is valid merely because the syntax parses.

OpenClaw's `tools.gatewayPolicy` limits model-directed built-in tool calls; the official reference explicitly says it does **not** configure native Codex tools or restrict arbitrary Harness-local programs. The official Docker image documentation also says the default images bundle the `codex` and `diagnostics-otel` plugins. Before any pilot, inspect the actual plugin inventory and disable/remove native Codex or other execution surfaces unless they have a separate reviewed authorization and sandbox boundary. The current Business OS policy does not authorize native Codex execution.

OpenClaw's Docker sandbox materially limits tool execution but is not described by its maintainers as a perfect security boundary; the Gateway process itself remains on the host. Keep the Gateway private and dedicate this first pilot to one trusted operator. Do not host mutually untrusted users or customer workloads in this same Gateway. Use separate Gateways/OS trust boundaries for that case.

## Validate before running work

```bash
openclaw config validate
openclaw doctor
openclaw security audit
openclaw agents list --tree
openclaw sandbox list
openclaw gateway status
openclaw sandbox explain --agent business-os-orchestrator
openclaw sandbox explain --agent business-os-research
```

If the installed CLI differs, consult `openclaw --help` and the version-matched docs rather than guessing command flags. Confirm the effective sandbox backend is Docker, scope is agent, workspace access is only `rw` for the private workspace, Docker network is `none`, root filesystem is read-only, and all Linux capabilities are dropped. Verify the effective sandbox tool allowlist and each agent's effective tool policy; fail closed if the sandbox is unavailable or any unexpected tool is exposed.

## First synthetic task

After the operator has confirmed the config, run a bounded read-only task:

```bash
openclaw agent --agent business-os-orchestrator --message "Using synthetic data only, verify the Business OS agent roster, list missing activation prerequisites, and return a report. Do not contact external parties, change files outside the Business OS workspace, schedule jobs, or modify any production system."
```

Review logs, spawned child sandbox status, tool calls, workspace writes and model spend. Do not enable schedules or external integrations during this test.

## After a successful smoke test

- Enable only public research and manually supplied synthetic data.
- Add the Business OS database adapter and isolated database only after project cost and organization are approved.
- Implement approval validation in the tool gateway before adding any external-write tool.
- Add one recurring job only after budget caps, pause controls, audit and incident recovery have passed negative tests.
