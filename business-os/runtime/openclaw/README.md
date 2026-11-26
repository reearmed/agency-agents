# OpenClaw runtime adapter (guarded starter)

OpenClaw is the proposed first runtime because Agency Agents has a maintained OpenClaw conversion/install path and OpenClaw supports isolated agents, per-agent workspaces, tool policies and scheduling. This adapter is a **starter configuration**, not a deployed gateway.

## Safety defaults

- Loopback/local-only setup until remote access is separately secured.
- No messaging channels configured.
- No shell/process execution, browser control, payments, publishing, outbound communication or production integrations.
- Cron disabled. Scheduling stays off until the pilot and approval gates pass.
- Each agent has its own workspace and state directory.
- All agents are sandboxed; verify the installed sandbox backend works before starting.
- Orchestrator alone may delegate sessions. Specialists cannot spawn other agents.
- Tool gateway allow-list is explicit and minimal.

OpenClaw docs warn that an agent workspace is not by itself a filesystem sandbox; the sandbox must be enabled. The example sets sandbox mode to `all` and scope to `agent`, but this still requires a working supported container runtime.

## Files

- `openclaw.json5.example`: configuration template.
- `../../agents/*.md`: tailored role instructions.
- `../../../scripts/bootstrap-business-os-openclaw.sh`: safe workspace generator (dry-run unless `--apply`).

## Setup sequence

1. Install OpenClaw using its official installation guide; inspect the installer before executing it.
2. Verify CLI commands with `openclaw --help` and version-specific config schema/docs.
3. Ensure Docker or the supported sandbox backend is installed and running.
4. Run `bash scripts/bootstrap-business-os-openclaw.sh` to preview workspace creation.
5. Review every path in the preview, then run with `--apply`. The script refuses to overwrite existing files.
6. Copy the example config into the active OpenClaw config only after backing up the current file. Merge rather than replace any existing configuration.
7. Validate with the installed version's config check / doctor commands. Confirm tool availability and sandbox isolation before starting the gateway.
8. Authenticate one model provider through the official onboarding flow. Never paste API keys into this repository.
9. Start with the orchestrator only and synthetic data. Then enable specialist agents one at a time.
10. Do not enable cron, messaging, email, social publishing, paid acquisition or production integrations in this starter.

## Why not enable schedules yet?

The scheduler creates persistent background work. It remains disabled until the global pause switch, cost caps, task persistence, audit records, approval validation and incident recovery have been implemented and tested. The current workspace bootstrap is a safe agent-prompt layer, not a complete tool gateway.

## References

- OpenClaw multi-agent routing: https://docs.openclaw.ai/multi-agent
- OpenClaw tool policy: https://docs.openclaw.ai/gateway/config-tools/tool-policy
- OpenClaw security permissions: https://docs.openclaw.ai/gateway/security/tool-permissions
