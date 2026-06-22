# Woodpecker CI on picklelab: design

Date: 2026-06-18
Status: design approved, pending implementation plan

## Goal

Stand up one self-hosted CI system serving two private GitHub repos:

- **pirpg** (Node/TypeScript) — currently runs CI on the self-hosted
  `github-actions-runner`.
- **brineworks** (`technicalpickles/brineworks`, local clone `pickled-finances`;
  Python/FastAPI) — has no CI today.

Scope for this round is **test-only** CI (run the suite on push/PR, report the
green/red check back to GitHub). Build-image and deploy pipelines are a likely
future phase but are explicitly *not* designed here beyond leaving room for them.

## Why Woodpecker (and why not just the Actions runner)

The driver is consolidation: brineworks needs CI, and rather than bolt a second
Actions runner on, stand up one system for both. Woodpecker was chosen over
keeping/expanding the Actions runner with eyes open:

- **The Actions runner polls** (outbound HTTPS), which is why it slotted into the
  tailnet-only, no-inbound homelab with zero friction.
- **Woodpecker is webhook-driven**, so GitHub must reach *in*. There is no poll
  mode. This is the one real cost: it requires a single deliberate public ingress
  (Tailscale Funnel). That cost was accepted in exchange for fully self-hosted
  orchestration, config-as-code pipelines, and clean container-per-step
  isolation.

The trade is conscious. If the goal were purely "least work," a single
user-scoped Actions runner pointed at both repos would have been less. We are
paying some complexity for self-hosting on principle.

## Architecture

```
GitHub (webhooks + OAuth)
        │  HTTPS public, via Tailscale Funnel on the sidecar's node identity
        ▼
┌──────────────────────────────────────────────────────────┐
│  ts-woodpecker (tailscale sidecar, userspace, zero-priv)  │
│  hostname: woodpecker  →  woodpecker.tail2023b7.ts.net    │
│  Funnel :443 → 127.0.0.1:8000   (funnel.json, checked in) │
│                                                            │
│   shares netns:                                            │
│   ┌─────────────────────┐      ┌──────────────────────┐   │
│   │ woodpecker-server    │ ───► │ woodpecker-agent      │  │
│   │ :8000 HTTP (UI/API)  │ gRPC │ DOCKER_HOST = rootless│  │
│   │ :9000 gRPC           │ :9000│   ci socket           │  │
│   └─────────────────────┘      └──────────┬───────────┘   │
└───────────────────────────────────────────┼──────────────┘
                                             │ spawns step containers on
                                             ▼ the ROOTLESS daemon (user: ci)
                              ┌──────────────────────────────┐
                              │ rootless dockerd as `ci`      │
                              │ CI steps run as ci's uid;     │
                              │ cannot read root- or          │
                              │ technicalpickles-owned files  │
                              │ (incl. /opt/homelab/.env)     │
                              └──────────────────────────────┘
```

## Section 1 — Service shape and homelab placement

New service dir `homelab/services/woodpecker/`, mirroring the established
pattern:

| File | Role |
|------|------|
| `compose.yaml` | base: ts sidecar + server + agent |
| `compose.picklelab.yaml` | prod overrides: data volumes under `/srv/data/woodpecker/`, `restart: unless-stopped` |
| `funnel.json` | Tailscale serve/funnel config (config as code) |
| `deploy.sh` | scp via `scripts/service-env`, `compose up`, link+enable systemd unit |
| `woodpecker.service` | systemd unit (oneshot + RemainAfterExit, like the runner) |
| `.env.vars` | the vars this service needs, filtered from master `.env` |

Decisions:

- Server HTTP binds loopback (`127.0.0.1:8000`) inside the sidecar netns. Funnel
  is the only thing that exposes it.
- gRPC `:9000` stays inside the shared netns (server↔agent over `localhost`).
  Never funneled, never host-published.
- Data under `/srv/data/woodpecker/` (`server/` SQLite, `ts-state/` node
  identity). On restic's path automatically.
- One agent, `WOODPECKER_MAX_WORKFLOWS=2` to start, so CI cannot starve the
  home-automation containers on the Celeron J3455.

## Section 2 — Funnel via container-as-node sidecar

This deliberately departs from the source doc, which assumed host `tailscaled`
funnel. The homelab already evolved past that with `brineworks-agent`
(container-as-node). Woodpecker fits that pattern even better:

- HTTP-only ingress means the sidecar runs in **userspace mode**
  (`TS_USERSPACE=true`): no `NET_ADMIN`, no `/dev/net/tun`. Cleaner than
  brineworks-agent, which needs TUN only for mosh's UDP.
- Funnel attaches to the **sidecar's** node identity
  (`woodpecker.tail2023b7.ts.net`), not picklelab's host name. Public exposure
  rides a dedicated, tagged CI node; the host's own `:443` and identity stay
  clean.
- Funnel config is a **checked-in `funnel.json`** (`TS_SERVE_CONFIG`), not an
  imperative host command. Git-managed and reproducible.

Compose shape:

```yaml
services:
  ts-woodpecker:
    image: tailscale/tailscale:latest
    hostname: woodpecker
    environment:
      - TS_AUTHKEY=${WOODPECKER_TS_AUTHKEY}    # reusable, tag:ci, in .env
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_USERSPACE=true                       # HTTP-only: no NET_ADMIN, no tun
      - TS_EXTRA_ARGS=--advertise-tags=tag:ci
      - TS_SERVE_CONFIG=/config/funnel.json
    volumes:
      - /srv/data/woodpecker/ts-state:/var/lib/tailscale
      - ./funnel.json:/config/funnel.json:ro
    restart: unless-stopped

  woodpecker-server:
    image: woodpeckerci/woodpecker-server:latest
    network_mode: service:ts-woodpecker
    depends_on: [ts-woodpecker]
    environment:
      - WOODPECKER_HOST=https://woodpecker.tail2023b7.ts.net
      # GitHub OAuth + admin + repo-owners: see Section 3
    volumes:
      - /srv/data/woodpecker/server:/var/lib/woodpecker

  woodpecker-agent:
    image: woodpeckerci/woodpecker-agent:latest
    network_mode: service:ts-woodpecker
    depends_on: [woodpecker-server]
    environment:
      - WOODPECKER_SERVER=localhost:9000
      - WOODPECKER_MAX_WORKFLOWS=2
      - DOCKER_HOST=unix:///rootless/docker.sock   # see Section 4
    # runs as the ci uid; mounts only the rootless socket
```

`funnel.json`:

```json
{
  "TCP": { "443": { "HTTPS": true } },
  "Web": {
    "woodpecker.tail2023b7.ts.net:443": {
      "Handlers": { "/": { "Proxy": "http://127.0.0.1:8000" } }
    }
  },
  "AllowFunnel": { "woodpecker.tail2023b7.ts.net:443": true }
}
```

Funnel attention list (mostly declarative, one ACL edit):

1. **ACL edit**: grant the `funnel` nodeAttr to `tag:ci`; define `tag:ci` with
   `technicalpickles` as tagOwner.
2. **Auth key**: reusable, `tag:ci`-scoped key in 1Password →
   `WOODPECKER_TS_AUTHKEY` (same pattern as brineworks-agent's `TS_AUTHKEY`).
3. **`funnel.json`** checked into the service dir.
4. **Persist `TS_STATE_DIR`** to `/srv/data/woodpecker/ts-state` so the
   `woodpecker` MagicDNS name does not dedup to `woodpecker-1` on recreate (the
   gotcha documented in `homelab/services/README.md`).
5. **No host sudoers change.** Funnel runs inside the sidecar; picklelab's `:443`
   and identity are untouched.

Tradeoff accepted: the long-lived agent daemon shares the funnel'd node's netns.
The funnel forwards only `:443→:8000` (server), so nothing reaches the agent from
outside. Stricter separation (agent as its own bridge container / tailnet node)
was considered and rejected as more plumbing for marginal gain.

## Section 3 — GitHub OAuth app and secrets

- **OAuth App, not a GitHub App.** GitHub Apps mishandle Woodpecker's user-token
  refresh today. Accepted downside: the token carries full personal repo scope
  rather than a narrow per-repo install. Fine for a personal homelab.
- Because Funnel makes the endpoint public, three settings are security-bearing:
  `WOODPECKER_OPEN=false`, `WOODPECKER_REPO_OWNERS=technicalpickles`,
  `WOODPECKER_ADMIN=technicalpickles`.

OAuth App registration:

| Field | Value |
|-------|-------|
| Application name | `Woodpecker CI` |
| Homepage URL | `https://woodpecker.tail2023b7.ts.net` |
| Authorization callback URL | `https://woodpecker.tail2023b7.ts.net/authorize` |

Secrets, via the existing 1Password → `.env.template` → `service-env` flow (one
new `picklehome`-vault item, `Woodpecker CI`):

| `.env` var | Source |
|------------|--------|
| `WOODPECKER_GITHUB_CLIENT` | OAuth App Client ID |
| `WOODPECKER_GITHUB_SECRET` | OAuth App Client Secret |
| `WOODPECKER_AGENT_SECRET` | `openssl rand -hex 32` |
| `WOODPECKER_TS_AUTHKEY` | Tailscale reusable `tag:ci` key |

The agent gets the minimum env (server addr, agent secret, max workflows, docker
host). It never receives the homelab secret superset, consistent with the
reasoning that stripped `env_file: /opt/homelab/.env` off the
`github-actions-runner`.

## Section 4 — Agent isolation: rootless Docker as a dedicated user (Option D)

The agent must spawn step containers, which means Docker socket access. The
default (mounting the host root `docker.sock`) is host-root-equivalent: a
compromised CI step could `-v /:/host` and read `/opt/homelab/.env` (the full
secret superset). That is a *new* privilege surface vs the current runner, which
mounts no socket.

Options weighed:

| | Closes host-root escalation? | Privileged container? | Layer cache? | Host setup |
|---|---|---|---|---|
| A host root socket | No | No | shared | none |
| B socket proxy | No (path/method filter only; create+bind still allowed) | No | shared | low, misleading |
| C dind | Yes | Yes (dind is privileged) | lost/needs volume | medium |
| **D rootless daemon, dedicated `ci` user** | **Yes** | **No** | **shared** | medium (one-time) |

**Decision: D, from day one.** A second, *rootless* `dockerd` runs as a
dedicated `ci` user that owns nothing sensitive. A CI step that bind-mounts `/`
reads everything as `ci`'s uid, so root- and `technicalpickles`-owned files
(including `/opt/homelab/.env`, mode 600) are unreadable. No privileged container,
and the persistent daemon keeps the image-layer cache.

Wiring: the Woodpecker stack runs on the normal root daemon; the agent is only
*pointed at* the rootless socket. The host socket
`/run/user/<ci-uid>/docker.sock` is bind-mounted into the agent at
`/rootless/docker.sock`, and `DOCKER_HOST=unix:///rootless/docker.sock` (the
in-container path shown in the Section 2 compose) targets it. The agent container
runs as the `ci` uid and mounts *only* the rootless socket, never the root
socket, so the agent itself cannot escalate either. Step containers spawn on the
rootless daemon, confined to `ci`.

Host setup (one-time, lands in `homelab/plans/homelab_03_host_setup.md`):

- Create dedicated `ci` user owning nothing sensitive.
- `dockerd-rootless-setuptool.sh install` as `ci`; `loginctl enable-linger ci`;
  subuid/subgid maps.
- Accept rootless networking via `slirp4netns` (NAT egress works for image
  pulls/clones, measurably slower than bridge; no host-network mode for steps,
  irrelevant for CI).

## Section 5 — Per-repo pipelines (test-only)

**pirpg** — direct port of `.github/workflows/ci.yml`:

```yaml
when:
  - event: [push, pull_request]
steps:
  - name: check
    image: node:22
    commands:
      - npm ci
      - npx prettier --check .
      - npx tsc --noEmit
      - npm run build
      - npm test
```

Notes:
- No built-in npm cache (Actions' `cache: npm` has no direct equivalent). `npm ci`
  re-fetches each run; acceptable for test-only. A host-volume or
  `plugin-s3-cache` step can add it back later.
- Events widened to `[push, pull_request]` (Actions `ci.yml` is `on: push` only)
  so PRs get checks.

**brineworks** — Python 3.11 (mise pins `3.11.9`), pip-based (`pip install -e .`):

```yaml
when:
  - event: [push, pull_request]
steps:
  - name: test
    image: python:3.11
    commands:
      - pip install -e '.[test]'   # confirm the real test-deps extra at impl time
      - pytest
```

Open item to resolve at implementation: confirm the exact install line that pulls
in pytest (likely a `test`/`dev` extra or dependency group; `pip install -e .`
alone may not include it). `pyproject.toml` has `[tool.pytest.ini_options]` with
`testpaths = ["tests"]`.

## Section 6 — Cutover

- **brineworks**: net-new. Add `.woodpecker.yml`, enable the repo. No cutover.
- **pirpg**: parallel-run. Both systems can run during validation (two checks per
  commit: `CI` from Actions, `woodpecker` from Woodpecker).
  1. Enable the repo in Woodpecker (auto-creates webhook).
  2. Add `.woodpecker.yml`; push a branch; confirm the green check lands on the
     GitHub commit.
  3. Once Woodpecker's check matches Actions, delete
     `pirpg/.github/workflows/ci.yml`.

`dependabot-auto-merge.yml` is the one workflow that cannot move: it uses
`dependabot/fetch-metadata`, `gh pr merge --auto`, and `GITHUB_TOKEN` (all
Actions-native), and it cannot fall back to GitHub-hosted runners (billing-blocked,
the reason the self-hosted runner exists).

**Decision: B1.** Move `ci.yml` to Woodpecker; keep the `github-actions-runner`
alive solely for `dependabot-auto-merge` (it then fires only on Dependabot PRs,
near-zero footprint). Reimplementing auto-merge as a Woodpecker pipeline (B2) or
dropping it (B3) is a follow-up decision, filed as a task rather than solved here.

## Section 7 — Backup

Woodpecker state lands under `/srv/data/woodpecker/`, already swept by the nightly
restic job. No new backup config.

Most of it is rebuildable: build history is disposable, repo activations
re-create webhooks on re-enable, and pipeline secrets duplicate 1Password. The one
genuinely worth-persisting bit, `ts-state/` (the node identity), is already on the
backed-up path so the `woodpecker` hostname survives a rebuild.

Sharp edge: restic snapshots SQLite live (no `pg_dump` equivalent), so a backup
taken mid-write could be torn. For a test-only CI DB written a few times a day the
risk is tiny and the data is rebuildable. No pre-backup SQLite dump for now; add a
`VACUUM INTO` hook later if build-history durability ever matters.

Recovery story: restore `ts-state/` (keeps the hostname), re-add secrets from
1Password, re-enable repos.

## Decisions summary

| # | Decision |
|---|----------|
| 1 | New `homelab/services/woodpecker/`; ts sidecar + server + agent; loopback-only; data on `/srv/data/woodpecker/` |
| 2 | Container-as-node sidecar (userspace, zero-priv) owns Funnel; `funnel.json` checked in; endpoint `woodpecker.tail2023b7.ts.net`; ACL grants `funnel` to `tag:ci`; reusable tagged auth key |
| 3 | GitHub OAuth App (not GitHub App); 4 secrets via 1Password→`.env.template`→`service-env`; `OPEN=false`, scoped `REPO_OWNERS`/`ADMIN` |
| 4 | Option D: rootless dockerd as dedicated `ci` user; agent points at its socket; closes host-root escalation, keeps layer cache, no privileged container |
| 5 | Test-only `.woodpecker.yml` per repo; pirpg (node:22, port of `ci.yml`), brineworks (python:3.11, pip+pytest); events `[push, pull_request]` |
| 6 | Parallel-run cutover; delete pirpg `ci.yml` once green; B1 keep shrunken runner for `dependabot-auto-merge`; B2/B3 as follow-up task |
| 7 | restic snapshots `/srv/data/woodpecker/` as-is; Woodpecker documented as rebuildable; persist `ts-state` |

## Open items to resolve during implementation

- Confirm brineworks test-deps install line (the `.[test]`/`dev` extra).
- Confirm Funnel works in userspace mode inside the sidecar with the shared-netns
  proxy to `:8000` (smoke-test against a throwaway before relying on it).
- Confirm Woodpecker's fork-PR pipelines require approval and withhold secrets by
  default (the untrusted-code gate).
- File the B2/B3 dependabot-auto-merge follow-up as a taskwarrior task.
