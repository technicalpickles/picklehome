# Services

Reference for services running on picklelab. Covers the shared deployment pattern, on-host paths, and a registry of each service.

For per-service setup details, see the service's own `README.md`.

## Deployment pattern

All services follow the same shape. Deploy from Mac:

```bash
just dotenv                    # refresh secrets from 1Password
just deploy-<service>          # git pull on host, scp filtered .env, docker compose up
```

Each service directory in `homelab/services/<name>/` contains:

| File | Purpose |
|------|---------|
| `compose.yaml` | Local dev compose |
| `compose.picklelab.yaml` | Production overrides (volumes, restart policy) |
| `deploy.sh` | Called by `just deploy-<name>`, handles scp + compose up + systemd |
| `.env.vars` | Which env vars this service needs (filtered from master `.env` by `scripts/service-env`) |
| `Dockerfile` | Custom image build (if applicable) |
| `<name>.service` | systemd unit (every service has one; long-lived services run a `oneshot`+`RemainAfterExit` unit, timer-based ones a triggered unit) |
| `<name>.timer` | systemd timer (timer-based services only: `backup`, `climate-auto-switch`) |

On picklelab, services land at:

- **Compose files:** `/opt/homelab/homelab/services/<service>/`, this is a full `picklehome` checkout kept fast-forwarded by `git pull`, not a scp'd subset. Verify against a specific service's `<service>.service` `WorkingDirectory` if unsure; every service's `deploy.sh` sets `REPO_DIR=/opt/homelab`. (`/srv/containers/<service>/` shows up in early planning docs but no service actually deploys there, don't trust that path.)
- **Persistent data:** `/srv/data/<service>/`
- **Env file:** `/opt/homelab/homelab/services/<service>/.env`, scp'd by `just deploy-<service>` from a filtered subset of the master `.env` (via `scripts/service-env`), landing alongside that service's compose files.

TLS and external access use **Tailscale Services**: `tailscaled` on the host terminates HTTPS and proxies to the local container port. No reverse proxy container needed. Container ports bind to `127.0.0.1:<port>` only — this loopback-only bind is what makes it safe for a service to trust Tailscale's identity headers; see the `tailscale-serve-patterns` skill for why, and before deviating from this default.

Per-service hostname is stored in 1Password as `<SERVICE>_HOST` and pulled into `.env`. The tailnet suffix is documented in the project [CLAUDE.md](../../CLAUDE.md).

**Debugging a Tailscale Service (`svc:<name>`)** — status looking wrong, self-curl hanging, etc: use the `tailscale-cli` skill rather than re-deriving these gotchas.

### Container user model and bind-mount ownership

Containers that write to `/srv/data/<service>/` bind mounts run as a **non-root user whose uid matches the host file ownership**. This is the invariant that makes volume sharing work: Linux bind mounts expose the host inode ownership directly, so a container process can only write if its uid owns (or has group write on) the files.

**How each piece enforces this:**

| Where | What it does |
|-------|--------------|
| `compose.yaml` `user: "uid:gid"` | Sets the process uid inside the container. Use explicit `"uid:gid"` string (e.g. `"1000:1000"`), not a named user — named users couple the compose file to the image's internal `/etc/passwd`. |
| `deploy.sh` `chown -R uid:gid /srv/data/<service>` | Fixes existing host files before the container restarts with a new uid. Pattern: chown immediately after `mkdir -p`, before `docker compose up`. |
| Dockerfile `ARG USER_UID` / `useradd` | Custom images (second-brain-agent, brineworks-agent) create the user inside the image at the same uid. Required when the container process needs a real login shell, home directory, or sshd. Off-the-shelf images (obsidian-sync, woodpecker) use `user:` in compose instead — no Dockerfile change needed. |

**Current uid assignments:**

| Service | uid:gid | Set via |
|---------|---------|---------|
| second-brain-agent | 1000:1000 | Dockerfile `ARG USER_UID` + `compose.yaml` (implicit, Dockerfile sets it) |
| brineworks-agent | 1000:1000 | Dockerfile in brineworks repo |
| obsidian-sync (all vaults) | 1000:1000 | `compose.yaml` `user: "1000:1000"` |
| woodpecker-server | 1000:1000 | Image default (woodpecker v3 ships uid 1000); `deploy.sh` chowns `/srv/data/woodpecker/server` |
| woodpecker-agent | 2000:2000 | `compose.yaml` `user: "2000:2000"`; matches the `ci` system user that owns the rootless docker socket |
| climate-auto-switch | root | No volume sharing; no write-access risk |
| backup | `backup` system user | Systemd service user; uses `setfacl` for read access to other services' files |
| openclaw | 1000:1000 | Image default (node); `compose.yaml` `user: "1000:1000"` |
| open-webui | 1000:1000 | `compose.yaml` `user: "1000:1000"` + custom `Dockerfile` chowning `/app/backend/open_webui/static` at build time (stock image untested non-root, see service README "Non-root fix") |
| open-terminal | 1000:1000 | Image default (`useradd -m` on Debian base, no explicit uid); confirmed via `docker top` at first deploy, see `homelab/services/open-webui/deploy.sh` |
| nikke | 1000:1000 | `compose.yaml` `user: "1000:1000"`; Dockerfile `useradd -u 1000`; `deploy.sh` chowns `/srv/data/nikke` |

**Cross-service volume sharing** requires uid alignment at both ends:
- **Producer** (the writer): set `user: "uid:gid"` in compose
- **Consumer** (the reader/writer): set `user:` or build with matching uid in Dockerfile
- **deploy.sh**: chown the shared path to the common uid as part of both services' deploy scripts
- **Transition recovery**: if an entrypoint needs to chown a bind mount (e.g. files existed as root before the uid fix), gate it on a fast check (`stat -c %u`) so it doesn't recurse on every start once ownership is already correct

Current cross-service share: obsidian-sync → second-brain-agent (both uid 1000, `/srv/data/obsidian-sync/vaults/pickled-knowledge`).

### When the default doesn't fit: container-as-node (UDP, native node identity)

Tailscale Services (host `tailscaled` + serve) is **TCP/HTTP only**. A service that needs **UDP** (e.g. mosh, WireGuard, game/voice protocols) or wants its own first-class tailnet identity cannot use the serve proxy: UDP aimed at a serve-proxied hostname has nowhere to land.

For those, run a **`tailscale` sidecar** so the service container is its own tailnet node, and UDP flows natively over WireGuard:

```yaml
services:
  ts-<name>:
    image: tailscale/tailscale:latest
    hostname: <name>                     # becomes the MagicDNS name
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY}          # reusable, tagged auth key; in the filtered .env
      - TS_STATE_DIR=/var/lib/tailscale   # node identity persists across recreates
      - TS_USERSPACE=false                # kernel/TUN mode: required for arbitrary UDP
      - TS_EXTRA_ARGS=--advertise-tags=tag:server
    volumes:
      - /srv/data/<name>/ts-state:/var/lib/tailscale
    devices:
      - /dev/net/tun:/dev/net/tun
    cap_add:
      - net_admin                          # NET_ADMIN only, not --privileged
    restart: unless-stopped

  <name>:
    network_mode: service:ts-<name>        # share the node's netns; drop the loopback ports: block
```

Tradeoffs to weigh before reaching for this:

- **`TS_USERSPACE=false` is load-bearing.** Userspace mode (the zero-privilege default) only proxies TCP/HTTP, so it does *not* solve UDP. TUN mode is what carries UDP, and it costs a `/dev/net/tun` device + the `NET_ADMIN` capability.
- **Privilege vs `homelab_07` (workload-not-ops).** `NET_ADMIN` + tun lets the container manage *its own* network interface, not the host. It is not `--privileged`, no docker socket, no sudo, no host mount, no host reach. Read as within the principle's spirit, but confirm per service. If you won't grant it, the fallback is to bind the published port(s) to the host's tailscale IP and reach the service as `picklelab` (fiddlier, and still no clean UDP for serve-style hostnames).
- **Persist `TS_STATE_DIR`** on `/srv/data/<name>/` (restic-backed) so the node doesn't churn the tailnet device list on every recreate.
- **MagicDNS names don't auto-reclaim.** Tailscale assigns the name at registration; if `<name>` is already taken then (a leftover `svc:<name>` Service, another device), it dedups to `<name>-1` and will **not** rename itself once the conflict clears. The tell: `ssh <name>.<tailnet>.ts.net` hangs (bare name resolves to nothing real) while `<name>-1` works. Fix by renaming the machine in [Tailscale Machines](https://login.tailscale.com/admin/machines) (or re-checking "auto-generate from OS hostname", since the container's `hostname:` already matches). Persisting `TS_STATE_DIR` keeps the corrected name across recreates.
- It **replaces** the serve/Service/loopback wiring for that service rather than adding to it.

First user: `brineworks-agent` (mosh from a phone). Full rationale and rejected alternatives live in the brineworks repo at `docs/decisions/0006-agent-tailnet-node-for-mosh.md` and `docs/runbooks/phone-ssh-agent-setup.md` (Part B). Reference: [Tailscale in Docker](https://tailscale.com/docs/features/containers/docker).

## Service registry

### climate-auto-switch

Runs `climate comfort-switch auto` every 15 minutes. Checks outdoor temperature and switches between heat/cool comfort modes.

| | |
|---|---|
| **Purpose** | Automated seasonal HVAC comfort mode switching |
| **Compose** | `/opt/homelab/homelab/services/climate-auto-switch/` |
| **Data** | `/srv/data/climate/` (OAuth tokens, last-run state, JSONL run log) |
| **Access** | No UI. systemd timer triggers the service unit. |
| **Env vars** | `ECOBEE_API_KEY`, `AMBIENT_STATION_MACS`, `HOME_LAT`, `HOME_LON`, `HOME_ZIP_CODE`, `BLUEAIR_*` |
| **Backup** | Yes, nightly (flat files) |
| **Restart** | N/A (runs on timer, not long-lived) |

Commands: `just deploy-climate`, `just seed-climate-tokens`, `just climate-check`, `just climate-log`

---

### backup

Nightly restic backups of `/srv/data` with Postgres dumps. Runs as a dedicated `backup` system user.

| | |
|---|---|
| **Purpose** | Nightly backup of all service data |
| **Compose** | N/A (restic runs directly on host, no container) |
| **Data** | `/srv/backups/restic` (restic repository on local SSD) |
| **Access** | No UI. systemd timer at 3am. |
| **Env vars** | `RESTIC_REPOSITORY`, `RESTIC_PASSWORD` |
| **Backup** | This IS the backup service |
| **Restart** | N/A (runs on timer) |

Retention: 7 daily, 4 weekly, 6 monthly (GFS). Future: Synology NAS, S3 offsite.

Commands: `just deploy-backup`, `just backup-now`, `just backup-snapshots`, `just backup-status`, `just backup-logs`

See [backup/README.md](backup/README.md) for what's captured and restore procedure.

---

### disk-hygiene

Weekly docker prune (both roots) + a passwordless `disk-report` diagnostic. Keeps `/srv` from silently filling.

| | |
|---|---|
| **Purpose** | Reap docker build churn; one-command disk investigation |
| **Compose** | N/A (host systemd timer + scripts, no container) |
| **Data** | None (operates on `/srv/containerd`, `/srv/ci-docker`) |
| **Access** | No UI. systemd timer at Sat 04:00. |
| **Env vars** | None |
| **Backup** | N/A |
| **Restart** | N/A (runs on timer) |

Prunes dangling images + build cache on the main dockerd and the rootless `ci` dockerd. Ships a root-owned `disk-report` at `/usr/local/sbin`, passwordless-sudo-able via a pinned `/etc/sudoers.d/docker-prune`.

Commands: `just deploy-disk-hygiene`, `just docker-prune-now`, `just docker-prune-status`, `just docker-prune-logs`, `just disk-report`

See [disk-hygiene/README.md](disk-hygiene/README.md).

---

### obsidian-sync

Headless Obsidian Sync client that keeps vault files on picklelab in sync with the Obsidian cloud.

| | |
|---|---|
| **Purpose** | Sync Obsidian vaults to picklelab for agent access |
| **Compose** | `/opt/homelab/homelab/services/obsidian-sync/` |
| **Data** | `/srv/data/obsidian-sync/` (synced vault files) |
| **Access** | No UI. Long-running sync process. |
| **Env vars** | None in `.env.vars` (auth handled interactively via `just obsidian-sync-exec`) |
| **Backup** | Not yet (synced from cloud, so cloud is the source of truth) |
| **Restart** | `restart: unless-stopped` |

Commands: `just deploy-obsidian-sync`, `just obsidian-sync-exec`, `just obsidian-sync-logs`, `just obsidian-sync-logs-follow`, `just obsidian-sync-status`

---

### brineworks-server

FastAPI REST API for personal relationship management (contacts, interactions, organizations).

| | |
|---|---|
| **Purpose** | Backend for brineworks email triage pipeline |
| **Compose** | `/opt/homelab/homelab/services/brineworks-server/` |
| **Data** | `/srv/data/brineworks-server/` (Postgres) |
| **Access** | `https://brineworks-server.<tailnet>.ts.net` (Tailscale Services) |
| **Env vars** | `BRINEWORKS_DB_PASSWORD`, `BRINEWORKS_API_KEY` |
| **Backup** | Not yet (needs adding to backup service) |
| **Restart** | `restart: unless-stopped` |
| **Source** | `technicalpickles/brineworks` (private repo), cloned to `/opt/brineworks` on host |

Commands: `just deploy-brineworks-server`, `just brineworks-server-logs`, `just brineworks-server-logs-follow`

See [brineworks-server/README.md](brineworks-server/README.md) for full setup.

---

### brineworks-agent

Always-on, phone-reachable Claude Code session running the brineworks CLI against prod. SSH + tmux into a container over Tailscale.

| | |
|---|---|
| **Purpose** | Mobile agent surface: reach a full Claude Code + `bw` session from a phone |
| **Compose** | `/opt/homelab/homelab/services/brineworks-agent/` |
| **Data** | `/srv/data/brineworks-agent/` (sshd host keys, cryptfile keyring, session workspace) |
| **Access** | `ssh technicalpickles@brineworks-agent.<tailnet>.ts.net` (Tailscale Services, raw TCP to loopback `2223` internally) |
| **Env vars** | `KEYRING_CRYPTFILE_PASSWORD`, `BRINEWORKS_API_KEY` (filtered `.env` only, never the master env) |
| **Backup** | Not yet (needs adding to backup service) |
| **Restart** | `restart: unless-stopped` |
| **Source** | `technicalpickles/brineworks` (private repo), built from `/opt/brineworks` on host |

The homelab's first **raw-TCP** Tailscale service (SSH, not HTTPS). Container internals copy `homelab/dev/`; deploy/orchestration shape copies `brineworks-server`.

Commands: `just deploy-brineworks-agent`, `just brineworks-agent-logs`, `just brineworks-agent-logs-follow`

See [brineworks-agent/README.md](brineworks-agent/README.md) for full setup.

---

### second-brain-agent

Always-on Claude Code session with the `pickled-knowledge` Obsidian vault mounted read-write. SSH + tmux into a container over Tailscale; same Tailscale node-as-container pattern as brineworks-agent.

| | |
|---|---|
| **Purpose** | Phone-reachable Claude Code session for reading and writing the pickled-knowledge vault |
| **Compose** | `/opt/homelab/homelab/services/second-brain-agent/` |
| **Data** | `/srv/data/second-brain-agent/` (sshd host keys, Claude state, tmux sessions) |
| **Vault** | `/srv/data/obsidian-sync/vaults/pickled-knowledge/` (mounted read-write at `/vault`) |
| **Access** | `ssh technicalpickles@second-brain-agent.<tailnet>.ts.net` (Tailscale node) |
| **Env vars** | `SECOND_BRAIN_AGENT_TS_AUTHKEY` (filtered `.env` only, never the master env) |
| **Backup** | Not yet |
| **Restart** | `restart: unless-stopped` |
| **Source** | Built from picklehome at `homelab/services/second-brain-agent/Dockerfile` (no external app repo) |

Depends on `obsidian-sync` being running to keep the vault current; systemd `After=obsidian-sync.service` ensures ordering on boot.

Commands: `just deploy-second-brain-agent`, `just second-brain-agent-logs`, `just second-brain-agent-logs-follow`

See [second-brain-agent/README.md](second-brain-agent/README.md) for full setup.

---

### taskchampion-sync

Self-hosted Taskwarrior sync server. Replicates the Mac's `~/.task` to picklelab; encryption secret stays client-side, server only sees opaque blobs.

| | |
|---|---|
| **Purpose** | Off-laptop replica of Taskwarrior data; future multi-device sync |
| **Compose** | `/opt/homelab/homelab/services/taskchampion-sync/` |
| **Data** | `/srv/data/taskchampion-sync/` (SQLite, encrypted blobs) |
| **Access** | `https://taskchampion.<tailnet>.ts.net` (Tailscale Services, port 9080 internally) |
| **Env vars** | `TASKCHAMPION_SYNC_HOST`, `TASKCHAMPION_SYNC_SERVER_CLIENT_ID` |
| **Backup** | Yes, nightly (SQLite picked up by `/srv/data` restic job) |
| **Restart** | `restart: unless-stopped` |

Commands: `just deploy-taskchampion`, `just taskchampion-status`, `just taskchampion-logs`, `just taskchampion-logs-follow`

See [taskchampion-sync/README.md](taskchampion-sync/README.md) for full setup.

---

### github-actions-runner

Self-hosted GitHub Actions runner for the pirpg repo (GitHub-hosted runners are billing-blocked on that private repo). Polls GitHub over outbound HTTPS.

| | |
|---|---|
| **Purpose** | Run pirpg CI on the homelab box |
| **Compose** | `/opt/homelab/homelab/services/github-actions-runner/` (no `compose.picklelab.yaml`; single `compose.yaml`, see below) |
| **Data** | `runner-config` Docker volume (persisted `.runner`/`.credentials`, so it survives reboots without re-registering) |
| **Access** | No UI. Registers as runner `picklelab`, labels `self-hosted,linux,picklelab`. |
| **Env vars** | `GITHUB_RUNNER_REPO_URL`, `GITHUB_RUNNER_TOKEN` (token is a one-time bootstrap, not ongoing auth) |
| **Backup** | No (re-bootstrappable from a fresh registration token) |
| **Restart** | `restart: unless-stopped` |

Unlike other services, this one has **no `compose.picklelab.yaml`**: it only ever runs on picklelab and has no prod-vs-local difference, and an `env_file: [/opt/homelab/.env]` override would have leaked the entire homelab secret set into a container that runs arbitrary CI jobs.

Commands: `just deploy-github-runner`, `just github-runner-logs`, `just github-runner-status`

See [github-actions-runner/README.md](github-actions-runner/README.md) for the auth model and re-bootstrap procedure.

---

### woodpecker

Self-hosted Woodpecker CI (server + agent + tailscale Funnel sidecar) for private GitHub repos. Test-only pipelines today. The one webhook-driven service, so it owns the homelab's only deliberate public ingress.

| | |
|---|---|
| **Purpose** | Self-hosted CI for private GitHub repos (consolidates onto one system) |
| **Compose** | `/opt/homelab/homelab/services/woodpecker/` |
| **Data** | `/srv/data/woodpecker/` (`server/` SQLite, `ts-state/` node identity) |
| **Access** | `https://woodpecker.<tailnet>.ts.net` (public via **Tailscale Funnel** on the sidecar's node, not host `tailscaled`) |
| **Env vars** | `WOODPECKER_GITHUB_CLIENT`, `WOODPECKER_GITHUB_SECRET`, `WOODPECKER_AGENT_SECRET`, `WOODPECKER_TS_AUTHKEY` |
| **Backup** | Yes, nightly (`/srv/data/woodpecker` picked up by restic; mostly rebuildable, `ts-state` is the bit worth keeping) |
| **Restart** | `restart: unless-stopped` |

CI steps run on a **rootless `dockerd` as a dedicated `ci` user** (uid 2000), so a compromised step can't read root/`technicalpickles`-owned secrets. Funnel uses userspace mode (HTTP-only, zero-priv); needs a one-time host setup (rootless docker for `ci`) and a Tailscale ACL granting `funnel` to `tag:ci`.

Commands: `just deploy-woodpecker`, `just woodpecker-logs`, `just woodpecker-status`

See [woodpecker/README.md](woodpecker/README.md) for full setup and the OAuth/Funnel prerequisites.

---

### openclaw

Self-hosted OpenClaw gateway (chat -> agent that can act), reached via Telegram and a Tailscale-only control UI. A migration from the `pickleclaw` OrbStack-VM spike, not a from-scratch bring-up.

| | |
|---|---|
| **Purpose** | Phone-reachable agent surface, sibling to `brineworks-agent` / `second-brain-agent` |
| **Compose** | `/opt/homelab/homelab/services/openclaw/` |
| **Data** | `/srv/data/openclaw/` (config, workspace/memory repo, auth-profile store, drop-in CLI dir) |
| **Access** | `https://openclaw.<tailnet>.ts.net` (Tailscale Services, port 18789 internally) + gateway token; Telegram bot gated by a chat-ID allowlist |
| **Env vars** | `OPENCLAW_HOST`, `OPENCLAW_GATEWAY_TOKEN`, `OLLAMA_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, `OPENCLAW_ALLOWED_CHAT_IDS`, `GOOGLE_PLACES_API_KEY`, `OPENCLAW_WORKSPACE_DEPLOY_KEY_B64`, `OPENCLAW_WORKSPACE_GITHUB_TOKEN`, `OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64`, `GOG_MCP_TOKEN`, `GOG_KEYRING_PASSWORD`, `OPENCLAW_IMAGE` |
| **Backup** | Yes, nightly (`/srv/data/openclaw` picked up by restic) |
| **Restart** | `restart: unless-stopped` |

Off-box inference only (Ollama Cloud, no local model — not viable on the J3455). Tool policy is `coding` with full exec (`security: "full"`, `ask: "off"`) and no deny list, widened from the original `minimal` on 2026-07-02 to match `pickleclaw`'s local model 1:1. No `docker.sock` grant. Session visibility is `agent` (2026-07-26), so the chat-ID allowlist is the only thing isolating sessions from each other. Both settings rest on this being a single-operator bot; see the [openclaw README](openclaw/README.md#security). Two config sections (`openclaw.tools.json5`, `openclaw.mcp.json5`) live in the private `pickleclaw` repo and are symlinked in, not committed here — the MCP one would leak real server names into a public repo.

Commands: `just deploy-openclaw`, `just openclaw-status`, `just openclaw-logs`, `just openclaw-logs-follow`

See [openclaw/README.md](openclaw/README.md) for full setup and the Telegram bot cutover procedure; [docs/plans/2026-06-30-openclaw-deploy.md](../../docs/plans/2026-06-30-openclaw-deploy.md) for design rationale.

---

### open-webui

Open WebUI chat interface backed by Ollama Cloud, plus [Open Terminal](https://docs.openwebui.com/features/open-terminal/) for sandboxed AI shell access. No local models; picklelab only hosts the UI/terminal containers and the UI's database, inference happens at ollama.com.

| | |
|---|---|
| **Purpose** | Web chat UI over Ollama Cloud models, single admin login, plus a sandboxed terminal the AI can drive |
| **Compose** | `/opt/homelab/homelab/services/open-webui/` |
| **Data** | `/srv/data/open-webui/` (SQLite `webui.db`, uploads, embedding cache); `/srv/data/open-terminal/` (Open Terminal's scratch home dir, **excluded from backup**) |
| **Access** | `https://openwebui.<tailnet>.ts.net` (Tailscale Services `svc:openwebui`, port 8090 internally); Open Terminal is internal-only (`http://open-terminal:8000` inside the Compose network, no host port) |
| **Env vars** | `OPEN_WEBUI_HOST`, `OPEN_WEBUI_ADMIN_EMAIL`, `OPEN_WEBUI_ADMIN_PASSWORD`, `OPEN_WEBUI_SECRET_KEY`, `OLLAMA_API_KEY`, `OPEN_TERMINAL_API_KEY` |
| **Backup** | Yes for `open-webui` (SQLite picked up by `/srv/data` restic job); no for `open-terminal` (excluded, disposable scratch space) |
| **Restart** | `restart: unless-stopped` (both containers) |

Commands: `just deploy-open-webui`, `just open-webui-status`, `just open-webui-logs`, `just open-webui-logs-follow`

See [open-webui/README.md](open-webui/README.md) for config-management gotchas (ConfigVar seeding) and upgrade steps.

---

### nikke

Roster dashboard for NIKKE, backed by a SQLite store synced from blablalink.com every 6 hours.

| | |
|---|---|
| **Purpose** | Browse and track a synced NIKKE character roster |
| **Compose** | `/opt/homelab/homelab/services/nikke/` |
| **Data** | `/srv/data/nikke/` (`roster.db`, `.blablalink-session.json`) |
| **Access** | `https://nikke.<tailnet>.ts.net` (Tailscale Services, port 8770 internally) |
| **Env vars** | None (`.env.vars` doesn't exist; `deploy-nikke` skips the `.env` scp) |
| **Backup** | Yes, nightly (`/srv/data/nikke` picked up by the `/srv/data` restic job, no per-service registration) |
| **Restart** | `serve`: `restart: unless-stopped`; `sync`: `run --rm` from `nikke-sync.timer` (every 6h) |
| **Source** | `technicalpickles/nikke-roster-scanner` (private repo), cloned to `/opt/nikke-roster-scanner` on host |

Commands: `just deploy-nikke`, `just nikke-logs`, `just nikke-logs-follow`, `just nikke-sync-now`, `just nikke-login`

See [nikke/README.md](nikke/README.md) for full setup.

---

## Planned services

- Home Assistant (containerized short-term, may migrate to dedicated hardware)
- Caddy reverse proxy (internal HTTPS hostnames), though Tailscale Services may make this unnecessary
