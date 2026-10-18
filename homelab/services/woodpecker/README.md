# Woodpecker CI

Self-hosted [Woodpecker CI](https://woodpecker-ci.org) serving private GitHub repos (test-only pipelines today: run the suite on push/PR, report the check back to GitHub). Consolidates CI that would otherwise need a second GitHub Actions runner.

Unlike the polling [`github-actions-runner`](../github-actions-runner/README.md), Woodpecker is **webhook-driven**, so GitHub has to reach in. That's the one real cost: a single deliberate public ingress via **Tailscale Funnel**, attached to a dedicated CI tailnet node rather than picklelab's host identity.

Design: [`docs/plans/2026-06-18-woodpecker-ci-design.md`](../../../docs/plans/2026-06-18-woodpecker-ci-design.md). Implementation: [`docs/plans/2026-06-18-woodpecker-ci-plan.md`](../../../docs/plans/2026-06-18-woodpecker-ci-plan.md).

## Architecture

```
GitHub (webhooks + OAuth)
        │  HTTPS public, via Tailscale Funnel on the sidecar's node identity
        ▼
  ts-woodpecker (tailscale sidecar, userspace, zero-priv)
  hostname: woodpecker  →  woodpecker.tail2023b7.ts.net
  Funnel :443 → 127.0.0.1:8000   (funnel.json, checked in)
        │  shares netns
        ├── woodpecker-server  (:8000 HTTP UI/API, :9000 gRPC)
        └── woodpecker-agent   (DOCKER_HOST → rootless ci socket)
                                        │ spawns step containers on the
                                        ▼ ROOTLESS dockerd running as `ci`
```

Three containers share one network namespace (`network_mode: service:ts-woodpecker`):

- **ts-woodpecker** — Tailscale sidecar in **userspace mode** (`TS_USERSPACE=true`: HTTP-only, no `NET_ADMIN`, no `/dev/net/tun`). Owns the `woodpecker` MagicDNS name and the Funnel. Funnel config is the checked-in [`funnel.json`](funnel.json) (`TS_SERVE_CONFIG`), proxying `:443 → 127.0.0.1:8000`.
- **woodpecker-server** — UI/API on loopback `:8000` (only Funnel exposes it). gRPC `:9000` is reachable by the local agent over loopback and, via a `TCPForward` in `funnel.json`, by tailnet members only (see [Remote agents](#remote-agents-optional)). It is deliberately absent from `AllowFunnel`, so it is not public. SQLite DB. Pinned to `:v3` (Woodpecker dropped `:latest` to prevent accidental major upgrades; `--pull always` gets patches/minors, never a major).
- **woodpecker-agent** — runs as the `ci` uid, points at the rootless docker socket via `DOCKER_HOST`. `WOODPECKER_MAX_WORKFLOWS=2` so CI can't starve the home-automation containers on the Celeron J3455.

### Agent isolation: rootless Docker as a dedicated `ci` user

The agent spawns step containers, which needs Docker socket access. Mounting the root `docker.sock` would be host-root-equivalent (a compromised CI step could `-v /:/host` and read `/opt/homelab/.env`). Instead, a second **rootless** `dockerd` runs as a dedicated `ci` user that owns nothing sensitive: a step that bind-mounts `/` reads everything as `ci`'s uid, so root- and `technicalpickles`-owned files (including the mode-600 secret superset) are unreadable. No privileged container, and the persistent daemon keeps the image-layer cache.

The Woodpecker stack itself runs on the normal root daemon; only the agent is *pointed at* the rootless socket. `compose.picklelab.yaml` bind-mounts `/run/user/2000/docker.sock` (the `ci` user's rootless socket) into the agent at `/rootless/docker.sock`. The agent mounts *only* that socket, never the root socket.

## Prerequisites (one-time)

1. **Host: rootless docker for the `ci` user** (uid 2000). Create the `ci` user, run `dockerd-rootless-setuptool.sh install` as `ci`, `loginctl enable-linger ci`, set up subuid/subgid maps. See [`homelab/docs/homelab_03_host_setup.md`](../../docs/homelab_03_host_setup.md). The deploy script pre-flight checks for `/run/user/2000/docker.sock` and fails loudly if it's missing.

2. **Tailscale ACL**: grant the `funnel` nodeAttr to `tag:ci`, and define `tag:ci` with `technicalpickles` as tagOwner. Funnel runs inside the sidecar, so picklelab's own `:443` and identity stay untouched.

3. **GitHub OAuth App** (an OAuth App, *not* a GitHub App — GitHub Apps mishandle Woodpecker's token refresh today):

   | Field | Value |
   |-------|-------|
   | Application name | `Woodpecker CI` |
   | Homepage URL | `https://woodpecker.tail2023b7.ts.net` |
   | Authorization callback URL | `https://woodpecker.tail2023b7.ts.net/authorize` |

4. **1Password item** `Woodpecker CI` in the `picklehome` vault, surfaced via `.env.template` → `just dotenv`:

   | `.env` var | Source |
   |------------|--------|
   | `WOODPECKER_GITHUB_CLIENT` | OAuth App Client ID |
   | `WOODPECKER_GITHUB_SECRET` | OAuth App Client Secret |
   | `WOODPECKER_AGENT_SECRET` | `openssl rand -hex 32` |
   | `WOODPECKER_TS_AUTHKEY` | Tailscale reusable `tag:ci` auth key |

   Because Funnel makes the endpoint public, three server settings are security-bearing and baked into `compose.yaml`: `WOODPECKER_OPEN=false`, `WOODPECKER_REPO_OWNERS=technicalpickles`, `WOODPECKER_ADMIN=technicalpickles`.

## Remote agents (optional)

Additional agents on other machines (for example an OrbStack VM on the laptop, running its own tailnet node) connect to the server's gRPC port over the tailnet.

`funnel.json` is a Tailscale **Serve** config that happens to carry the public Funnel entry. Only ports listed under `AllowFunnel` are public (just `:443`). The `9000` `TCPForward` entry is not listed there, so it is tailnet-only. Keep it out of `AllowFunnel`, and omit the key rather than setting it to `false`: a present-but-false key still shows a Funnel badge on the Machines page.

Policy additions (admin console, not checked in):

```json
{
  "tagOwners": { "tag:ci-agent": ["<same owners as tag:ci>"] },
  "grants": [
    { "src": ["tag:ci-agent"], "dst": ["tag:ci"], "ip": ["tcp:9000"] }
  ]
}
```

Check the live policy for an existing wildcard grant (`*` to `*`) first. If one is still active it already allows this, and the grant is decorative until the wildcard goes.

Create the agent in the UI **before** starting it (Settings, Agents, Add agent). Filters are set there, and the agent gets its own token, so it can't pick up anything it shouldn't from its first connection. The filter form has separate key and value boxes. Enter key `!host`, value `laptop` (not `!host=laptop` as one string, which the form stores as a label literally named that). The `!` on the key makes the workflow *require* the label, so only pipelines with `labels: host: laptop` land on the VM. A plain `host` = `laptop` filter does not exclude workflows that have no `host` label at all, so unlabeled pipelines would still run there. Verify placement after any change (a no-label workflow must not reach the VM). Labels alone don't restrict an agent, since an agent reports whatever labels it likes; the server-side filter is what enforces it. Save the token to 1Password as `agent_token` on the "Woodpecker Agent VM" item, then run [`agent-vm/start-agent.sh`](agent-vm/start-agent.sh). That token, not the system `WOODPECKER_AGENT_SECRET`, is what the VM agent uses.

The VM agent mounts the VM's root docker socket. That is deliberate (a VM that only does CI), unlike picklelab's rootless `ci` setup.

After deploying a `funnel.json` change, verify:

1. `docker compose exec ts-woodpecker tailscale serve status --json` shows `9000` under `TCP` and `AllowFunnel` unchanged.
2. From a tailnet node, `nc -vz woodpecker.tail2023b7.ts.net 9000` succeeds.
3. From off the tailnet (phone on cellular), the same check fails.

### Agent switch (prefer the laptop agent while it is online)

Woodpecker has no agent priority or fallback: filters and labels are hard match rules and the first agent to ask gets the work. `agent_switch.py` fakes a preference by flipping two server-side settings through the API, from a systemd timer (`woodpecker-agent-switch.timer`, every minute):

- laptop agent online (`last_contact` within `STALE_AFTER_SECONDS`, default 300): clear its `!host` filter so it takes unlabeled pipelines too, and set picklelab's agent to `no_schedule`.
- laptop agent missing, never connected, or stale: picklelab schedulable again, laptop filter back to `!host=laptop`.

It is stateless (each run reads the agent list and converges), so a missed tick or restart costs nothing. PATCH order keeps at least one agent able to take unlabeled work at every step, and anything unexpected fails open toward picklelab. A running job whose agent goes quiet is requeued by the server after its 1 minute lease expires, so it reruns elsewhere; side effects repeat.

It runs as the profile-gated compose service `woodpecker-agent-switch` (`docker compose --profile switch run --rm --no-deps`), sharing `ts-woodpecker`'s network namespace to reach the API on `localhost:8000`. The stock Woodpecker images are `FROM scratch`, which is why it is a separate image rather than part of them.

- **Needs** `WOODPECKER_API_TOKEN` (an admin user's personal access token) in 1Password and in `.env.vars` / `.env.template`, and the two agent names in `compose.yaml` matching Settings, Agents.
- **Ships off:** `SWITCH_TIMER_ENABLED=0` in `deploy.sh`. Flip it to `1` and redeploy to start the timer. `/etc/opt/homelab/woodpecker-agent-switch.env` containing `SWITCH_ARGS=--dry-run` makes it log without changing anything.
- **Logs:** `just woodpecker-switch-logs`.
- **Rollback:** `just woodpecker-switch-reset` stops the timer and restores defaults. A reboot restarts an enabled timer, and `systemctl disable` is not in the passwordless sudo allowlist, so to keep it off across reboots disable it interactively (`ssh -t picklelab sudo systemctl disable woodpecker-agent-switch.timer`).
- **Manual override:** setting `no_schedule` on picklelab's agent by hand gets overridden on the next tick. Stop the timer first.
- **Arch drift:** the VM is arm64 and picklelab is amd64. While the filter is lifted, unlabeled pipelines can land on either, so pin amd64-only pipelines with a platform label (check the exact label in the UI before relying on it).
- **Tests:** `uv run pytest tests/homelab/` (unit tests plus an in-process fake Woodpecker server, no docker or token needed).

## First-time Setup

```bash
just dotenv             # pull the four Woodpecker secrets from 1Password
just deploy-woodpecker
```

`deploy.sh` is idempotent (safe on first setup or any redeploy): it checks the rootless socket, creates `/srv/data/woodpecker/{ts-state,server}` (chowning `server/` to uid 1000 so the non-root server image can create its SQLite DB), pulls images, links + enables the systemd unit, restarts, then health-checks `http://127.0.0.1:8000/healthz` from inside the sidecar netns.

If the Funnel hostname doesn't resolve yet, check `docker compose exec ts-woodpecker tailscale funnel status`. Because `TS_STATE_DIR` is persisted to `/srv/data/woodpecker/ts-state`, the `woodpecker` name survives recreates instead of dedup'ing to `woodpecker-1`.

Per-repo CI is a checked-in `.woodpecker.yml` in each target repo plus enabling the repo in the Woodpecker UI (auto-creates the webhook).

## Deploying Updates

```bash
just deploy-woodpecker
```

## Status & Logs

```bash
just woodpecker-status   # systemd unit + docker compose ps
just woodpecker-logs     # follow server + agent logs (last 100 lines)
```

## Data Locations (on picklelab)

```
/opt/homelab/homelab/services/woodpecker/   # service files (git-managed)
/srv/data/woodpecker/ts-state/              # tailscale node identity (persisted, backed up)
/srv/data/woodpecker/server/                # SQLite DB (uid 1000, backed up nightly)
```

## Backup

State lands under `/srv/data/woodpecker/`, already swept by the nightly restic job. Most of it is rebuildable (build history is disposable, repo activations re-create webhooks, pipeline secrets duplicate 1Password). The bit worth persisting is `ts-state/` (the node identity), which keeps the `woodpecker` hostname across a rebuild.

Sharp edge: restic snapshots SQLite live, so a backup taken mid-write could be torn. For a test-only CI DB written a few times a day the risk is tiny and the data is rebuildable. No pre-backup SQLite dump for now.
