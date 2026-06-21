# second-brain-agent

An always-on, phone-reachable Claude Code session on picklelab with the `pickled-knowledge` Obsidian vault mounted read-write at `/vault`. Reached over Tailscale by SSH; work happens in a long-lived tmux session.

Modeled on `homelab/services/brineworks-agent/` (Tailscale node sidecar for mosh UDP, persistent `/data` volume, filtered secrets) but with no external app repo — the image is built directly from picklehome.

## What it is

An Ubuntu container with a real `sshd` (key-only, `authorized_keys` pulled from your GitHub keys), Claude Code, and tmux (resurrect/continuum). You SSH in from a phone, `tmux attach`, and you're in a full Claude Code session with the vault at `/vault/`.

The `pickled-knowledge` vault is synced continuously by the `obsidian-sync` service: writes the agent makes are picked up by obsidian-sync and pushed to the Obsidian cloud (E2E encrypted). obsidian-sync must be running for the vault to stay current.

## Prerequisites (one-time)

**Tailscale admin:**
- `tag:server` applied to picklelab with `tagOwners` in the ACL (already done for brineworks-agent).
- Mint a **reusable, non-ephemeral auth key** at https://login.tailscale.com/admin/settings/keys, tagged `tag:server`. Store it in the `picklehome` 1Password vault as a new item `Second Brain Agent` with a field `ts_authkey`. Add the `op://` reference to `.env.template`:

```
SECOND_BRAIN_AGENT_TS_AUTHKEY={{ op://picklehome/Second Brain Agent/ts_authkey }}
```

`SECOND_BRAIN_AGENT_TS_AUTHKEY` is already in `.env.vars`; until the `op://` reference exists it is skipped silently and the node cannot authenticate. Re-run `just dotenv` after adding it.

Your phone's SSH public key must be in your GitHub keys (`https://github.com/technicalpickles.keys`) — the entrypoint fetches that into `authorized_keys` on first boot.

## First-time Setup

```bash
just dotenv          # pull secrets from 1Password (incl. SECOND_BRAIN_AGENT_TS_AUTHKEY)
just deploy-second-brain-agent
```

`deploy.sh` creates the `/data` volume directories, builds the image from picklehome, and starts the systemd service (the `ts-agent` node sidecar plus the agent container).

### Approve the node (first deploy only)

The agent joins the tailnet as its own node (`second-brain-agent`) via the `ts-agent` sidecar. If your tailnet requires device approval:

1. Open [Tailscale Machines](https://login.tailscale.com/admin/machines)
2. Find `second-brain-agent` and approve it. Confirm it carries `tag:server`.
3. Verify: `ssh technicalpickles@second-brain-agent.<tailnet>.ts.net`

`deploy.sh` prints these steps if the node isn't reachable.

### Claude Code auth (first login only)

Claude credentials are stored on the `/data/claude` volume and survive redeploys. On first login, authenticate Claude:

```bash
ssh technicalpickles@second-brain-agent.<tailnet>.ts.net
claude          # follow the OAuth prompt
```

Credentials are now persisted at `/data/claude/.credentials.json`.

## Connecting

```bash
ssh technicalpickles@second-brain-agent.<tailnet>.ts.net
```

You land directly in the persistent `main` tmux session — a `/etc/profile.d` hook
auto-attaches every interactive SSH/mosh login (the session is started detached at
container boot, so it's always there). Detaching (`C-b d`) drops you to a plain shell;
`tmux attach` gets you back in. Non-interactive channels (`scp`, `ssh host <cmd>`) are
left alone.

The vault is at `/vault/`. Use `claude` to start a session; ripgrep (`rg`) is available for full-text vault search.

The tmux session is long-lived and survives disconnects. A redeploy recreates the container; tmux-resurrect/continuum plus `~/.claude` on the volume restore the layout and conversation on reattach.

## Deploying Updates

```bash
just deploy-second-brain-agent
```

Pulls latest picklehome, rebuilds the image, restarts the service. The vault bind-mount is re-attached automatically.

## Architecture

- **Build from picklehome:** the image builds from `/opt/homelab` (the whole picklehome repo) with `homelab/services/second-brain-agent/Dockerfile`. No separate app repo.
- **Compose layering:** `compose.yaml` is the portable base (non-secret config). `compose.picklelab.yaml` adds the `build:` directive, the `ts-agent` Tailscale node sidecar, `network_mode: service:ts-agent`, the `/data` volume, and the vault mount.
- **Vault mount:** `/srv/data/obsidian-sync/vaults/pickled-knowledge` is bind-mounted read-write at `/vault`. Writes are picked up by obsidian-sync and synced to the cloud.
- **Secrets:** the container receives only its filtered `.env` (`SECOND_BRAIN_AGENT_TS_AUTHKEY`), never the master `/opt/homelab/.env`. Claude credentials live on the `/data` volume.
- **Networking:** same Tailscale container-as-node pattern as brineworks-agent (see `homelab/services/README.md` "container-as-node"). mosh UDP works natively via the sidecar's WireGuard interface.

## Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `VAULT_DIR` | compose | `/vault` — the Obsidian vault mount point |
| `GITHUB_USER` | compose | `technicalpickles` — for fetching `authorized_keys` from GitHub |
| `SECOND_BRAIN_AGENT_TS_AUTHKEY` | `.env` (1Password) | Reusable `tag:server` auth key the `ts-agent` sidecar uses to join the tailnet |

## Data Locations (on picklelab)

```
/srv/data/second-brain-agent/ssh/host_keys     # persistent sshd host keys
/srv/data/second-brain-agent/ts-state/         # ts-agent Tailscale node identity
/srv/data/second-brain-agent/claude/           # ~/.claude (credentials, settings, transcripts)
/srv/data/second-brain-agent/tmux-resurrect/   # tmux-resurrect session saves
/srv/data/obsidian-sync/vaults/pickled-knowledge/  # Obsidian vault (managed by obsidian-sync)
```

## Logs

```bash
just second-brain-agent-logs
just second-brain-agent-logs-follow
```
