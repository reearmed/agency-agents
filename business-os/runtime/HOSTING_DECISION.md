# Hosting decision — proposed first always-on runtime

## Recommendation

Use a dedicated DigitalOcean Basic Droplet in Toronto (TOR1) for the first isolated OpenClaw gateway pilot, with external model API calls and one active task at a time. Start with 8 GiB RAM to leave headroom for the Gateway plus isolated Docker agent sandboxes; do not run a local LLM on this VM in phase one.

Why:
- OpenClaw documents DigitalOcean as a VPS option and recommends keeping the Gateway on loopback, accessing it through SSH or Tailscale, and backing up state/workspaces.
- DigitalOcean confirms Basic Droplets are available in Toronto (TOR1).
- The current published Basic plan for 4 vCPU / 8 GiB RAM / 160 GiB SSD is US$48/month. This is a planning estimate, not a quote at checkout.
- OpenClaw's Docker guide says prebuilt images avoid the 6 GB RAM requirement for local source image builds. Use an official pinned prebuilt image and confirm the Docker sandbox workload fits before scaling concurrency.

## Initial footprint

| Item | Proposed setting |
|---|---|
| Provider / region | DigitalOcean / Toronto TOR1 |
| VM | Basic 4 vCPU, 8 GiB RAM, 160 GiB SSD |
| VM estimate | US$48/month before tax and optional extras |
| Runtime | OpenClaw Gateway, pinned official release/image |
| Model | External reasoning API; provider and exact model still need selection/authentication |
| Local model | Do not host Qwen3-0.6B on this VM; reserve local model for lightweight routing only |
| Concurrency | 1 active workflow initially |
| Network | SSH/Tailscale administration; Gateway loopback only; no public Gateway port |
| Sandbox | Docker-backed per-agent sandbox, separate per-agent scope |
| Channels | None in first pilot |
| Schedules | Disabled until approval and cost controls are tested |

A smaller 4 GiB Basic plan is published at US$24/month, but is not the recommended starting point for a multi-agent sandboxed pilot. If measured load exceeds 8 GiB, scale up rather than weakening isolation.

## Costs not included

- Model/API usage.
- Isolated Business OS database project (if Supabase is selected).
- Backups, monitoring, object storage, domain, taxes and optional managed services.

Set a total monthly ceiling and per-task ceiling before provisioning. Do not allow agents to upgrade plans or increase spend.

## Provisioning is not authorized by this document

No DigitalOcean account access is connected in this workspace, no Droplet has been created, and no payment method has been charged. This is the recommended target architecture only.

## Sources

- OpenClaw Linux server hosting and hardening: https://docs.openclaw.ai/vps
- OpenClaw Docker and sandbox prerequisites: https://docs.openclaw.ai/docker
- DigitalOcean Droplet pricing: https://www.digitalocean.com/pricing/droplets
- DigitalOcean regional availability (TOR1): https://docs.digitalocean.com/platform/regional-availability/
