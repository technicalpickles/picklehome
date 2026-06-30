# OpenClaw on picklelab — initial deployment research

**Status:** initial research only. No decision made, nothing deployed. Captures what OpenClaw is, how a deploy would map onto picklehome conventions, the hard constraints, and the open questions to resolve before writing a plan.

**Date:** 2026-06-30

---

## What OpenClaw is

OpenClaw is a self-hosted **AI gateway**: it bridges messaging apps (WhatsApp, Telegram, Discord) to an AI agent that can *act* — run shell commands, manage files, browse the web, and send alerts. You message a bot; it runs an agentic loop against an LLM and does things on the box it's running on.

The right framing for *this* homelab: **OpenClaw is a deliberate agent surface, a sibling to `brineworks-agent` and `second-brain-agent`** — not a hostile workload to cage. The difference is that OpenClaw provides the agent loop and a chat front-end *out of the box*, where the existing two are Claude Code sessions you SSH into over Tailscale. So the model is the same as those: trusted-but-shaped, deployed on purpose. The one boundary that genuinely differs is the **front door** (chat channel vs. SSH key) — see [Where it fits the agent model](#where-it-fits-the-agent-model).

## How it runs (Docker)

Public guides converge on a simple shape, though they disagree on specifics (OpenClaw is young and the guides are partly SEO content — treat exact numbers as *verify before relying*):

| Aspect | What the sources say | Confidence |
|---|---|---|
| **Image** | Single official container image, Docker is the recommended deploy path | High |
| **Port** | One HTTP port serving web UI + REST API + webhook callbacks. Default cited as **`18789`** most often; some guides show `3000` or `47981`. | Medium (number varies) |
| **State dir** | Config dir bind-mount (`~/.openclaw` inside container — `/home/node/.openclaw` or `/root/.openclaw` depending on image user). Holds agent config, **memory**, **credentials**, a SQLite memory index, and **channel session tokens**. | High |
| **Workspace dir** | Separate workspace mount where the agent reads/writes files | High |
| **LLM backends** | Anthropic, OpenAI, and Ollama (OpenClaw ships a [native Ollama provider](https://docs.openclaw.ai/providers/ollama)). Ollama can be a **local server or its cloud subscription** — same OpenAI-compatible API either way. | High |
| **Auth secret** | An LLM API key via env; secrets in `.env`, referenced as `${VAR}`, never hardcoded | High |
| **Resources** | ~4 GB RAM minimum to the container, **8 GB if the browser tool is enabled**; ~20 GB disk for image + state + growing memory files | Medium |

Note on env precedence: provider env vars set in the shell (the documented case is the `ANTHROPIC_*` family, but the same pattern applies to the Ollama/OpenAI vars) **override** OpenClaw's own config files — a known footgun when debugging auth. Since we inject via `.env`, just be aware config-file values won't win over an env var of the same name.

## Fit with picklelab hardware

NUC is a Celeron **J3455 (4 weak cores, no GPU), 16 GB RAM**.

- **RAM:** 16 GB total, already running ~9 services. A 4 GB agent fits; an 8 GB browser-enabled agent is tight alongside everything else. Budget this explicitly.
- **LLM runs off-box via an Ollama cloud subscription** (the chosen backend). This sidesteps the J3455 entirely — no local inference, which would be unusably slow on a GPU-less Celeron. Mechanically it's an [Ollama API key](https://ollama.com/settings/keys) pointed at the OpenAI-compatible endpoint `https://ollama.com/v1`, via OpenClaw's native Ollama provider. The key lives in 1Password → `.env` like every other secret. (Keeps inference off Anthropic/OpenAI billing; pick the cloud model from Ollama's catalog.)
- **Disk:** 20 GB on the local SSD is fine; `/srv/data` is the home for state.

## How it maps onto homelab conventions

This part is the *good* news — the mechanics fit the existing pattern almost exactly:

- **Service layout:** `homelab/services/openclaw/` with `compose.yaml`, `compose.picklelab.yaml`, `deploy.sh`, `.env.vars`, `openclaw.service` (long-lived `oneshot`+`RemainAfterExit`). Data at `/srv/data/openclaw/`, compose at `/srv/containers/openclaw/`.
- **Secrets:** the Ollama API key (and any channel tokens) into 1Password → `.env.template` → filtered into the service `.env` via `scripts/service-env`. Channel tokens (Telegram bot token, etc.) are per-service secrets in the `picklehome` vault.
- **uid/bind-mount:** the container writes `/srv/data/openclaw/` so it **must not run as root**. Pick a uid (next free, e.g. `3000`), set `user: "uid:gid"` in compose, `chown -R` in `deploy.sh` after `mkdir -p`. Mind which internal home the image uses (`/home/node` vs `/root`) when mapping the state dir.
- **Access / ingress — two paths depending on channel transport:**
  - **Outbound-only channels (Telegram long-polling):** no public ingress needed. The bot polls out; you reach the **web UI/REST over Tailscale Services** (`https://openclaw.<tailnet>.ts.net`, loopback bind `127.0.0.1:18789`). This is the clean, no-public-exposure path and matches the default homelab pattern.
  - **Webhook-driven channels (WhatsApp Cloud API, some Discord setups):** need inbound HTTPS, i.e. **Tailscale Funnel** like `woodpecker` does — the homelab's only deliberate public-ingress pattern. More surface, more care.

## Where it fits the agent model

OpenClaw is a **deliberate agent surface**, the same category as `brineworks-agent` and `second-brain-agent`. We do **not** treat it as a hostile workload to be caged — the heavy containment in the community guides (Gluetun VPN egress, kill-switch, zero host mounts, fully dropped caps) exists to *grant an untrusted thing some access*; OpenClaw's whole purpose is to *be* the agent with access, so caging it to zero reach defeats the point. Model it on the two existing agent containers: trusted-but-shaped, deployed on purpose.

What that means concretely:

1. **The front door is the real boundary.** `brineworks-agent`/`second-brain-agent` are gated by an SSH key over Tailscale (you, authenticated). OpenClaw's gate is *whoever can message the bot*. So the **chat-channel allowlist is the equivalent of the SSH key** — lock the bot to your own chat IDs, never leave a channel open. This is the one genuinely new thing vs. the existing agents, and it's the thing to get right.
2. **Give it the tools you want it to have, deliberately.** Like `second-brain-agent` mounting the vault read-write on purpose, decide OpenClaw's tool surface intentionally (shell? the existing `just` CLIs? a workspace dir?) rather than either caging it to nothing or handing it the whole host by default. The browser tool is the one to default *off* unless wanted — it's ~4 GB RAM and the biggest passive attack surface.
3. **Standard service hygiene, same as everything else** (this is `homelab_07`'s actual ask — auditable, recoverable, repo-driven, not "no agents"):
   - non-root uid + `chown` in `deploy.sh` (every service does this).
   - State (`/srv/data/openclaw`) into the nightly restic job — it holds memory + channel tokens.
   - Compose version-controlled; no docker socket, no sudo (it's an agent surface, not an ops agent on the `/opt/homelab` control path).

The remaining judgment call: OpenClaw shares the box with climate control, locks, and the obsidian vaults. That argues for a deliberate, *minimal* tool surface to start (notifications + a couple of read-only `just` checks) and widening later — same trust-grows-with-capability path `homelab_07` describes — rather than wiring it to everything on day one.

## Open questions to resolve before a plan

- **Why / use case?** What do you actually want it to *do* (ops assistant? notifications? home-automation glue calling the existing `just` CLIs?). The use case decides how much host access it needs — which decides whether it's safe here at all.
- **Which channel(s)?** Telegram (outbound-only, no public ingress) is the lowest-surface starting point. WhatsApp/Discord-webhook needs Funnel.
- **Which Ollama cloud model + plan tier?** Backend is decided (Ollama cloud subscription). Remaining: pick the model from Ollama's catalog and confirm the subscription tier covers an always-on agent's request volume.
- **Tool surface?** Default OpenClaw can run shell + browse + filesystem. Decide the minimum set; disable the browser unless needed (saves ~4 GB RAM and a big chunk of attack surface).
- **Exact image facts:** pin the real default port, the in-container home/user, and the canonical volume paths from the official image before writing compose — public guides disagree.

## Suggested next step

A short spike: pull the official image, confirm the real port / volume paths / default user, and stand it up **locally (not on picklelab)** wired to Telegram with a single allowlisted chat ID, the browser tool **off**, and the Ollama cloud subscription as the backend. That validates the mechanics, the channel-auth front door, and the Ollama provider wiring before committing to an on-host deploy and writing a `docs/plans/` design doc.

## Sources

- [Docker · OpenClaw (official docs)](https://docs.openclaw.ai/install/docker) — *403'd to automated fetch; verify port/volumes/user here directly*
- [Self-Host OpenClaw on Docker — Complete 2026 Guide (provision.ai)](https://provision.ai/openclaw-docker)
- [Running OpenClaw in Docker — Simon Willison's TILs](https://til.simonwillison.net/llms/openclaw-docker)
- [deepmehtait/openclaw-docker-secure (GitHub)](https://github.com/deepmehtait/openclaw-docker-secure) — Gluetun VPN egress, no-new-privileges, no public ports, LAN-only
- [OpenClaw on a Synology NAS, hardened for always-on homelab use — David Christiansen](https://davidchristiansen.com/blog/openclaw-docker-hardened-homelab/) — Squid egress allowlist, Docker secrets, read-only rootfs
- [Deploy OpenClaw with Docker & Docker Compose (2026) — openclaw-ai.net](https://openclaw-ai.net/en/guide/docker)
- [coollabsio/openclaw — automated OpenClaw docker images](https://github.com/coollabsio/openclaw)
- [Ollama provider · OpenClaw docs](https://docs.openclaw.ai/providers/ollama)
- [Cloud models · Ollama Blog](https://ollama.com/blog/cloud-models) and [OpenAI compatibility · Ollama](https://docs.ollama.com/api/openai-compatibility) — cloud subscription, API key at `ollama.com/settings/keys`, OpenAI-compatible endpoint `https://ollama.com/v1`
