# Plan: Second Brain Agent + CLAUDE.md Obsidian Awareness

## Context

The picklehome homelab already runs an `obsidian-sync` service that continuously syncs two Obsidian vaults (`rpg`, `pickled-knowledge`) to the host at `/srv/data/obsidian-sync/vaults/<vault>/`. The brineworks-agent pattern provides a blueprint for a containerized, phone-reachable Claude Code session: Ubuntu + sshd + Claude Code + tmux, running as its own Tailscale node (for mosh UDP), with persistent state on `/srv/data/`, filtered secrets, and systemd lifecycle management.

The goal is two things:
1. Create a `second-brain-agent` service that reuses that exact pattern but mounts the `pickled-knowledge` vault (read-write) so Claude Code sessions can read and write notes directly.
2. Add Obsidian sync context to the top-level `CLAUDE.md` so future agent sessions don't have to explore blindly to find the vault.

---

## Part 1: second-brain-agent service

### What's different from brineworks-agent

| Dimension | brineworks-agent | second-brain-agent |
|-----------|------------------|--------------------|
| Build context | `/opt/brineworks` (external app repo, bakes `bw` CLI) | Dockerfile in picklehome (`homelab/services/second-brain-agent/Dockerfile`) — no separate app repo needed |
| Vault access | none (explicitly noted in deploy.sh) | `/srv/data/obsidian-sync/vaults/pickled-knowledge` mounted at `/vault` (read-write) |
| Secrets | KEYRING_CRYPTFILE_PASSWORD, BRINEWORKS_API_KEY, WORKSPACE_DEPLOY_KEY_B64, TS_AUTHKEY | SECOND_BRAIN_AGENT_TS_AUTHKEY only (Claude auth lives on the volume) |
| Workspace deploy key | yes (brineworks-workspace repo) | not needed |
| Gmail keyring | yes | not needed |

### Files created

All under `homelab/services/second-brain-agent/`:

**`Dockerfile`** — in picklehome (no separate app repo)
- Base: `ubuntu:24.04` (same as brineworks-agent)
- Install: openssh-server, git, curl, jq, tmux, ripgrep, Node.js 22, Claude Code
- tmux-resurrect + tmux-continuum cloned to `/usr/local/lib/`
- Same entrypoint pattern: fetch GitHub SSH keys into `authorized_keys`, redirect `~/.claude` to `/data/claude`, start sshd

**`entrypoint.sh`**
- SSH host keys generated once to `/data/ssh/host_keys` (survives redeploys; avoids SSH fingerprint churn)
- GitHub keys fetched to `authorized_keys` on first boot
- `~/.claude` → `/data/claude` symlink (Claude credentials survive redeploys)
- `~/.claude.json` → `/data/claude.json` symlink

**`tmux.conf`**
- `@resurrect-dir` set to `/data/tmux-resurrect`
- tmux-continuum auto-save every 15 minutes, auto-restore on start

**`compose.yaml`** — portable base (non-secret config only)

**`compose.picklelab.yaml`** — production overrides
- `ts-agent` sidecar: `tailscale/tailscale:v1.98.4` (pinned), hostname `second-brain-agent`, `TS_AUTHKEY=${SECOND_BRAIN_AGENT_TS_AUTHKEY}`
- agent: builds from `/opt/homelab` (picklehome repo root), `network_mode: service:ts-agent`
- volumes: `/srv/data/second-brain-agent:/data`, `/srv/data/obsidian-sync/vaults/pickled-knowledge:/vault`

**`.env.vars`**: `SECOND_BRAIN_AGENT_TS_AUTHKEY` (only secret needed)

**`deploy.sh`** — idempotent
1. Creates `/srv/data/second-brain-agent/{ssh/host_keys,ts-state,claude,tmux-resurrect}` (uid 1000)
2. Links systemd unit, reloads, restarts
3. Polls `second-brain-agent.<tailnet>.ts.net:22` (up to 10 retries)

**`second-brain-agent.service`** — oneshot/RemainAfterExit, `After=obsidian-sync.service`

### `.env.template` addition

```
# Second Brain Agent Tailscale node auth key (1Password item: Second Brain Agent).
# Separate key from brineworks-agent (lower blast radius per service).
SECOND_BRAIN_AGENT_TS_AUTHKEY={{ op://picklehome/Second Brain Agent/ts_authkey }}
```

### Justfile additions

```
deploy-second-brain-agent host="picklelab"
second-brain-agent-logs host="picklelab" lines="50"
second-brain-agent-logs-follow host="picklelab"
```

### One-time setup

1. Mint a reusable, non-ephemeral `tag:server` auth key in Tailscale admin → store in 1Password as item `Second Brain Agent`, field `ts_authkey`
2. Add `op://` reference to `.env.template`, re-run `just dotenv`
3. `just deploy-second-brain-agent`
4. Approve node at Tailscale Machines (first deploy only)
5. `ssh technicalpickles@second-brain-agent.<tailnet>.ts.net` → `tmux attach`
6. `claude` to authenticate (credentials persist on `/data/claude`)

No Gmail bootstrap, no deploy key, no keyring — much simpler than brineworks-agent.

### Dependency on obsidian-sync

The vault bind-mount requires obsidian-sync to be running. The agent starts fine without it (directory will be empty until sync catches up). `After=obsidian-sync.service` in the systemd unit ensures correct boot ordering.

---

## Part 2: CLAUDE.md improvements

### What was missing

The top-level `CLAUDE.md` Integrations table covered only smart home hardware. The homelab entry just said "see `homelab/README.md`". A new Claude session had no idea:
- There are Obsidian vaults on the host
- `pickled-knowledge` is the personal knowledge base ("second brain")
- Vault files are at `/srv/data/obsidian-sync/vaults/<vault>/`

### Changes made

**1. Expanded the `homelab/` Directories entry:**

```markdown
- `homelab/`: NUC server services and infrastructure; see `homelab/README.md`
  - Key services: `obsidian-sync` (vaults: `rpg`, `pickled-knowledge`), `brineworks-server`, `brineworks-agent`, `second-brain-agent`, `taskchampion-sync`
  - Obsidian vaults on host: `/srv/data/obsidian-sync/vaults/<vault>/` — `pickled-knowledge` is the personal knowledge base (second brain); `rpg` is campaign notes
  - `second-brain-agent` mounts `pickled-knowledge` read-write at `/vault`, reachable at `ssh technicalpickles@second-brain-agent.<tailnet>.ts.net`
```

**2. Added a "Homelab Services" section** after the Integrations table, listing all always-on services with directory, purpose, and deploy commands.

---

## Confirmed decisions

- **Vault access**: read-write (agent can create/edit notes)
- **Vaults**: `pickled-knowledge` only
- **Dockerfile**: in picklehome at `homelab/services/second-brain-agent/Dockerfile` (no external app repo)
- **Tailscale auth key**: new dedicated key per service (lower blast radius; separate 1Password item)

---

## Verification

```bash
just deploy-second-brain-agent
ssh technicalpickles@second-brain-agent.<tailnet>.ts.net
ls /vault     # should show pickled-knowledge vault files
claude        # Claude Code should launch; credentials persist after redeploy
```

Write a test note inside the container at `/vault/` and verify obsidian-sync picks it up and pushes it to Obsidian cloud.
