# Hosting decision — proposed first always-on runtime

## Recommendation

Keep DigitalOcean Basic Droplet in Toronto (TOR1) as the preferred first
isolated OpenClaw gateway pilot, with Akamai/Linode Toronto as an equivalent
price/spec alternative. Use external model API calls and one active task at a
time. Start with 8 GiB RAM to leave headroom for the Gateway plus isolated
Docker agent sandboxes; do not run a local LLM on this VM in phase one.

Pricing and region checks refreshed 26 November 2026:

- DigitalOcean Basic: 4 vCPU / 8 GiB RAM / 160 GiB SSD / 5,000 GiB transfer
  is published at **US$48/month**. Basic Droplets are available in Toronto
  TOR1.
- Akamai Cloud (Linode) Shared CPU: 4 CPUs / 8 GB RAM / 160 GB storage /
  5 TB transfer is published at **US$48/month**. Toronto (`ca-central`)
  shows full availability. This is an equal-price alternative, not a proven
  performance upgrade.
- Railway is not a Canadian-region option at this time: its current listed
  deployment regions are US West, US East, EU West and Singapore. Do not
  select it if Canadian data residency is a hard requirement.
- Supabase Pro is published from **US$25/month**; additional projects start
  at **US$10/month**, with compute and usage charges to be checked separately.
  Free projects can pause after one week of inactivity and are limited to two
  active projects. A separate Business OS project must never reuse NOREVYO's
  production project.

DigitalOcean remains the preferred option for the initial plan because its
Toronto Basic Droplet availability, published price and documented deployment
workflow are straightforward. Akamai/Linode is a valid second quote. Recheck
the exact plan, CPU class, tax, backup add-ons and checkout total before any
purchase. Canadian hosting location alone does not establish PIPEDA compliance:
review contractual terms, subprocessors, access controls, encryption, retention,
backup location and incident procedures.

OpenClaw documents DigitalOcean as a VPS option and recommends keeping the
Gateway on loopback, accessing it through SSH or Tailscale, and backing up
state/workspaces. Use an official pinned prebuilt image and confirm the Docker
sandbox workload fits before scaling concurrency.

## Initial footprint

| Item | Proposed setting |
|---|---|
| Provider / region | DigitalOcean / Toronto TOR1 |
| VM | Basic 4 vCPU, 8 GiB RAM, 160 GiB SSD |
| VM estimate | US$48/month before tax and optional extras; recheck at checkout |
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
- Isolated Business OS database project (if Supabase is selected): Pro additional project from US$10/month plus compute/usage; exact billing estimator required.
- Backups, monitoring, object storage, domain, taxes and optional managed services.

Set a total monthly ceiling and per-task ceiling before provisioning. Do not allow agents to upgrade plans or increase spend.

## Provisioning is not authorized by this document

No DigitalOcean account access is connected in this workspace, no Droplet has been created, and no payment method has been charged. This is the recommended target architecture only.

## Sources

- OpenClaw Linux server hosting and hardening: https://docs.openclaw.ai/vps
- OpenClaw Docker and sandbox prerequisites: https://docs.openclaw.ai/docker
- DigitalOcean Droplet pricing: https://www.digitalocean.com/pricing/droplets
- DigitalOcean regional availability (TOR1): https://docs.digitalocean.com/platform/regional-availability/
- Akamai Cloud North America pricing: https://www.akamai.com/cloud/pricing/north-america
- Akamai Cloud region availability (Toronto ca-central): https://www.akamai.com/why-akamai/global-infrastructure/availability
- Supabase pricing and project/compute details: https://supabase.com/pricing
- Railway deployment regions: https://docs.railway.com/deployments/regions
