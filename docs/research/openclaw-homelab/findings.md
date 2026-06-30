# OpenClaw on picklelab — initial deployment research

**Status:** initial research only. No decision made, nothing deployed. Captures what OpenClaw is, how a deploy would map onto picklehome conventions, the hard constraints, and the open questions to resolve before writing a plan.

**Date:** 2026-06-30

---

## What OpenClaw is

OpenClaw is a self-hosted **AI gateway**: it bridges messaging apps (WhatsApp, Telegram, Discord) to an AI agent that can *act* — run shell commands, manage files, browse the web, and send alerts. You message a bot; it runs an agentic loop against an LLM and does things on the box it's running on.

The important framing for *this* homelab: **OpenClaw is itself an always-on agent runtime with a chat-driven trigger surface.** That is exactly the kind of "hidden control plane" `homelab_07_agent_access_model.md` is written to avoid (see [Collision with the agent-access model](#collision-with-the-agent-access-model) below). This is the single biggest thing to get right.

## How it runs (Docker)

Public guides converge on a simple shape, though they disagree on specifics (OpenClaw is young and the guides are partly SEO content — treat exact numbers as *verify before relying*):

| Aspect | What the sources say | Confidence |
|---|---|---|
| **Image** | Single official container image, Docker is the recommended deploy path | High |
| **Port** | One HTTP port serving web UI + REST API + webhook callbacks. Default cited as **`18789`** most often; some guides show `3000` or `47981`. | Medium (number varies) |
| **State dir** | Config dir bind-mount (`~/.openclaw` inside container — `/home/node/.openclaw` or `/root/.openclaw` depending on image user). Holds agent config, **memory**, **credentials**, a SQLite memory index, and **channel session tokens**. | High |
| **Workspace dir** | Separate workspace mount where the agent reads/writes files | High |
| **LLM backends** | Anthropic (recommended for predictable billing), OpenAI, and local **Ollama** | High |
| **Auth secret** | `ANTHROPIC_API_KEY` (or OpenAI key) via env; secrets in `.env`, referenced as `${VAR}`, never hardcoded | High |
| **Resources** | ~4 GB RAM minimum to the container, **8 GB if the browser tool is enabled**; ~20 GB disk for image + state + growing memory files | Medium |

Note on env precedence: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_URL` set in the shell **override** OpenClaw's own config files — a known footgun when debugging auth.

## Fit with picklelab hardware

NUC is a Celeron **J3455 (4 weak cores, no GPU), 16 GB RAM**.

- **RAM:** 16 GB total, already running ~9 services. A 4 GB agent fits; an 8 GB browser-enabled agent is tight alongside everything else. Budget this explicitly.
- **Local LLM is not realistic here.** Ollama on a J3455 with no GPU would be unusably slow. If deployed, this uses a **cloud LLM (Anthropic API)** — which means recurring API cost and the agent's actions are driven by a cloud model.
- **Disk:** 20 GB on the local SSD is fine; `/srv/data` is the home for state.

## How it maps onto homelab conventions

This part is the *good* news — the mechanics fit the existing pattern almost exactly:

- **Service layout:** `homelab/services/openclaw/` with `compose.yaml`, `compose.picklelab.yaml`, `deploy.sh`, `.env.vars`, `openclaw.service` (long-lived `oneshot`+`RemainAfterExit`). Data at `/srv/data/openclaw/`, compose at `/srv/containers/openclaw/`.
- **Secrets:** `ANTHROPIC_API_KEY` (and any channel tokens) into 1Password → `.env.template` → filtered into the service `.env` via `scripts/service-env`. Channel tokens (Telegram bot token, etc.) are per-service secrets in the `picklehome` vault.
- **uid/bind-mount:** the container writes `/srv/data/openclaw/` so it **must not run as root**. Pick a uid (next free, e.g. `3000`), set `user: "uid:gid"` in compose, `chown -R` in `deploy.sh` after `mkdir -p`. Mind which internal home the image uses (`/home/node` vs `/root`) when mapping the state dir.
- **Access / ingress — two paths depending on channel transport:**
  - **Outbound-only channels (Telegram long-polling):** no public ingress needed. The bot polls out; you reach the **web UI/REST over Tailscale Services** (`https://openclaw.<tailnet>.ts.net`, loopback bind `127.0.0.1:18789`). This is the clean, no-public-exposure path and matches the default homelab pattern.
  - **Webhook-driven channels (WhatsApp Cloud API, some Discord setups):** need inbound HTTPS, i.e. **Tailscale Funnel** like `woodpecker` does — the homelab's only deliberate public-ingress pattern. More surface, more care.

## Collision with the agent-access model

`homelab_07` explicitly lists "unrestricted root shell," "arbitrary writes across the host," and "a hidden control plane" as things to avoid. **OpenClaw is, by design, a chat-triggered shell-runner.** It doesn't get a free pass just because it's a "service" — its blast radius is whatever its container can reach. Mitigations to design *before* deploying:

1. **Two trust boundaries, not one.** (a) Who can message the bot → drives the agent. (b) What the agent's container can touch → blast radius. Both must be locked down.
2. **Channel auth is load-bearing.** Whoever can DM the bot can run its tools. Lock to an allowlist of your own chat IDs; never leave a channel open.
3. **Contain the container** (lift from the `woodpecker` rootless-CI and `deepmehtait/openclaw-docker-secure` hardening):
   - non-root uid, `security_opt: [no-new-privileges]`, drop caps, read-only rootfs where possible with `tmpfs` for scratch.
   - **No docker socket. No host bind mounts** beyond its own `/srv/data/openclaw` workspace. No sudo. It is a *workload*, not an ops agent — keep it off the `homelab_07` operational path entirely.
   - **Egress control.** It can browse the web and call an LLM — constrain outbound (the secure reference stack routes everything through Gluetun/VPN with a kill-switch; a Squid allowlist proxy is the lighter option). At minimum, decide what it's allowed to reach.
4. **Recoverability.** State (`/srv/data/openclaw`) goes into the nightly restic job — it holds memory + channel tokens. Compose is version-controlled like every other service.

The honest question this raises: *does an autonomous, chat-triggered, command-executing agent belong on the same box as climate control, locks, and the obsidian vaults at all?* Options range from "yes, tightly contained" to "only with no host-tool access" to "give it its own cheap isolated box / VM." Worth deciding deliberately rather than defaulting.

## Open questions to resolve before a plan

- **Why / use case?** What do you actually want it to *do* (ops assistant? notifications? home-automation glue calling the existing `just` CLIs?). The use case decides how much host access it needs — which decides whether it's safe here at all.
- **Which channel(s)?** Telegram (outbound-only, no public ingress) is the lowest-surface starting point. WhatsApp/Discord-webhook needs Funnel.
- **Which LLM + budget?** Anthropic API (cost + cloud-driven actions) vs. anything local (not viable on the J3455). Set a spend expectation.
- **Tool surface?** Default OpenClaw can run shell + browse + filesystem. Decide the minimum set; disable the browser unless needed (saves ~4 GB RAM and a big chunk of attack surface).
- **Exact image facts:** pin the real default port, the in-container home/user, and the canonical volume paths from the official image before writing compose — public guides disagree.

## Suggested next step

A short spike: pull the official image, confirm the real port / volume paths / default user, and stand it up **locally (not on picklelab)** wired to Telegram with a single allowlisted chat ID and the browser tool **off**, cloud LLM, no host mounts. That validates the mechanics and the channel-auth model before committing to a contained on-host deploy and writing a `docs/plans/` design doc.

## Sources

- [Docker · OpenClaw (official docs)](https://docs.openclaw.ai/install/docker) — *403'd to automated fetch; verify port/volumes/user here directly*
- [Self-Host OpenClaw on Docker — Complete 2026 Guide (provision.ai)](https://provision.ai/openclaw-docker)
- [Running OpenClaw in Docker — Simon Willison's TILs](https://til.simonwillison.net/llms/openclaw-docker)
- [deepmehtait/openclaw-docker-secure (GitHub)](https://github.com/deepmehtait/openclaw-docker-secure) — Gluetun VPN egress, no-new-privileges, no public ports, LAN-only
- [OpenClaw on a Synology NAS, hardened for always-on homelab use — David Christiansen](https://davidchristiansen.com/blog/openclaw-docker-hardened-homelab/) — Squid egress allowlist, Docker secrets, read-only rootfs
- [Deploy OpenClaw with Docker & Docker Compose (2026) — openclaw-ai.net](https://openclaw-ai.net/en/guide/docker)
- [coollabsio/openclaw — automated OpenClaw docker images](https://github.com/coollabsio/openclaw)
