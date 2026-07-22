# Open Terminal for Open WebUI: design

Date: 2026-07-21
Status: design approved, pending implementation plan

## Goal

Give the chat AI in [Open WebUI](https://openwebui.com/) (already deployed on
picklelab, see `homelab/services/open-webui/`) a real sandboxed compute
environment via [Open Terminal](https://docs.openwebui.com/features/open-terminal/):
shell access, file read/write, package installs, running scripts/servers, all
driven by tool calls from the chat model. This is the tool integration, not a
change to Open WebUI's model/auth config.

## What Open Terminal actually is

A separate container (`ghcr.io/open-webui/open-terminal`) exposing an HTTP API
(bearer-key auth) that Open WebUI's backend proxies tool calls to. Key facts
that shaped this design (confirmed by reading the upstream `Dockerfile` and
`entrypoint.sh` in `open-webui/open-terminal`, not just the docs site):

- The image creates a non-root `user` account via `useradd -m` (uid is
  whatever the base Debian image's `login.defs` assigns, expected 1000, to be
  confirmed at deploy time) but grants it **passwordless sudo to root inside
  its own container** — that's how it installs packages on demand. The
  isolation boundary this depends on is the **container**, not that account;
  treat "runs as non-root" as cosmetic for this image, unlike every other
  service in `homelab/services/README.md`'s uid table.
- It optionally mounts `/var/run/docker.sock` for docker-in-docker workflows
  (the entrypoint adds `user` to the socket's group if present). We are **not**
  mounting it — that would hand the AI a straightforward escape to picklelab's
  host Docker daemon, which owns every other service's containers. If
  docker-in-docker ever becomes a real need, `woodpecker`'s Option D (a
  second, rootless `dockerd` owned by a dedicated non-privileged user, see
  `docs/plans/2026-06-18-woodpecker-ci-design.md` Section 4) is the template
  to reach for — not a plain bind of the host root socket. Not needed for
  this round.
- It has a built-in egress firewall (`OPEN_TERMINAL_ALLOWED_DOMAINS`): a DNS
  whitelist enforced via a local `dnsmasq` + `iptables`, after which
  `CAP_NET_ADMIN` is permanently dropped. Available if we ever want it; not
  used in this round (see Decisions).
- Connects to Open WebUI via the `TERMINAL_SERVER_CONNECTIONS` env var — a
  JSON array, and a `ConfigVar` (seeds the DB on first boot only, same
  first-boot-only caveat already documented for `OLLAMA_API_CONFIGS` in
  `homelab/services/open-webui/README.md`).

## Architecture

Bundle `open-terminal` as a second container inside the existing
`homelab/services/open-webui/` directory, rather than a new top-level service
directory. Precedent: `woodpecker` already runs three containers
(`ts-woodpecker` + `woodpecker-server` + `woodpecker-agent`) from one service
dir when they're this tightly coupled. Open Terminal only exists to serve
Open WebUI, so one deploy target (`just deploy-open-webui`) manages both, and
they share the default Compose network — Open WebUI reaches it at
`http://open-terminal:8000` by service name, no host port published, no
Tailscale Service. Nothing outside the Compose network needs to talk to it
directly.

```
                          Tailscale Services (unchanged)
                                    │
                                    ▼
┌───────────────────────────────────────────────────────────────┐
│ homelab/services/open-webui/  (one Compose project)            │
│                                                                  │
│  ┌──────────────┐  TERMINAL_SERVER_CONNECTIONS   ┌────────────┐│
│  │  open-webui   │ ──────────────────────────────▶│open-terminal││
│  │  :8080         │  http://open-terminal:8000     │  :8000     ││
│  │  (unchanged)   │◀──────────────────────────────  │  (new)     ││
│  └──────────────┘         tool-call results        └────────────┘│
│         │                                                  │      │
│    /srv/data/open-webui/                          /srv/data/     │
│    (existing, backed up)                          open-terminal/ │
│                                                     (new, NOT     │
│                                                      backed up)   │
└───────────────────────────────────────────────────────────────┘
```

## Decisions

1. **Placement**: bundled into `homelab/services/open-webui/`, not a
   standalone service directory. Simplest option given it only serves
   Open WebUI; matches the `woodpecker` multi-container precedent.
2. **Image**: `ghcr.io/open-webui/open-terminal:0.11.34` (latest release as
   of 2026-07-21), pinned like `open-webui`'s own image. Bump deliberately.
3. **Docker socket**: not mounted. Closes the container-escape path the
   upstream image otherwise supports for docker-in-docker workflows.
4. **Egress**: no restriction (`OPEN_TERMINAL_ALLOWED_DOMAINS` left unset).
   Full internet access, consistent with the trust level already extended to
   Ollama Cloud / openclaw, and most terminal use cases (arbitrary package
   installs, cloning arbitrary repos, hitting arbitrary APIs) need open
   egress anyway. Revisit later if it feels too loose in practice — the
   upstream firewall is a config change away, not a rebuild.

   What "full internet access" actually reaches, concretely (neither a pro
   nor a con here, just what's true): the container is not a Tailscale node
   and has no sidecar (unlike `woodpecker`/`brineworks-agent`), so it does
   not inherit tailnet reachability — it cannot resolve `*.ts.net` MagicDNS
   names or reach other tailnet devices/services just by existing on
   picklelab. Outbound traffic NATs through the Docker bridge and picklelab's
   normal default route (USG → AT&T BGW → internet, per the project
   `CLAUDE.md` network topology), same as any container on this host.
   Within the Compose network it can reach the `open-webui` container by
   service name (the point of this integration); it cannot reach other
   services' containers (each lives in its own Compose project's isolated
   default network) unless those services expose ports on an interface
   broader than loopback, which none currently do.
5. **Package pre-seeding**: none. `OPEN_TERMINAL_PACKAGES` /
   `_PIP_PACKAGES` / `_NPM_PACKAGES` left unset; the AI installs what it
   needs per-session via its own sudo.
6. **Connection wiring**: `TERMINAL_SERVER_CONNECTIONS` set as an env var on
   the `open-webui` container (a `ConfigVar`, so it only seeds on first
   boot — matches the existing `OLLAMA_API_CONFIGS` pattern and caveat).
   Avoids a manual Admin UI step on every fresh deploy/rebuild.

   **Confirmed gap in this reasoning, hit on first deploy (2026-07-22):**
   "first boot" means the database's first boot, not the container's. Open
   WebUI's database here was already initialized weeks before this env var
   existed (the original deploy), so adding a *new* `ConfigVar` to an
   *already-running* instance does not seed it — `ConfigVar` env seeding
   only ever applies to a brand-new, user-less database, never
   retroactively to one that already exists. `GET
   /api/v1/configs/terminal_servers` came back empty after this deploy,
   confirming the env var was silently ignored. The connection had to be
   added by hand via Admin Settings → Integrations → Open Terminal (same
   fields the env var would have set: URL, API key, Bearer auth) — verified
   via the server log showing `POST /api/v1/configs/terminal_servers 200`.
   **Takeaway for any future `ConfigVar` added to this service:** it only
   auto-applies on a fresh install; adding one to an existing instance
   always needs a manual one-time Admin UI step, no exceptions.
7. **Ownership**: no `user:` override in Compose for `open-terminal` — let
   the image's baked-in `USER user` stand, since forcing a uid that doesn't
   match its `/etc/passwd` entry could break `sudo`/`$HOME` resolution
   inside the container. Confirm the actual uid with
   `docker exec open-terminal id` on first deploy, then `chown` the host
   data dir to match in `deploy.sh` (same "check the base image's default"
   step called out in `homelab/services/CLAUDE.md`).
8. **Backup**: `/srv/data/open-terminal` is explicitly excluded from the
   nightly restic job, same treatment as the existing `dev-home` exclude in
   `homelab/services/backup/backup.sh`. This is a disposable AI scratch
   sandbox, not source-of-truth data — anything worth keeping gets moved to
   a real vault/repo/service by the human or the AI during the session.

## Secrets

One new secret, `OPEN_TERMINAL_API_KEY`, via the existing 1Password →
`.env.template` → `just dotenv` → `scripts/service-env` flow. New 1Password
item (`Open Terminal`, `picklehome` vault) rather than adding a field to the
existing `Open WebUI` item, since it's a distinct credential for a distinct
container. Added to `homelab/services/open-webui/.env.vars` alongside the
five existing vars.

## Verification

- `deploy.sh` gains a health check against `open-terminal`'s `/health`
  endpoint, alongside the existing `open-webui` `/health` check.
- Manual smoke test after deploy: Admin Panel → Settings → Integrations →
  Open Terminal shows a green "Connected" indicator; then ask the chat AI
  something like "what OS are you running on?" and confirm it drives the
  terminal tool rather than guessing.

## Open items to resolve during implementation

- Confirm the actual uid the image's `user` account gets (expected 1000, but
  verify — see Decision 7) before writing the `chown` line in `deploy.sh`.
- Confirm whether `docker-compose.yml`'s example wiring in the upstream docs
  needs `depends_on` between `open-webui` and `open-terminal` for clean
  startup ordering, or whether Open WebUI's connection check tolerates
  `open-terminal` not being up yet on first boot.
- Decide the 1Password item's field name(s) for the API key (likely a single
  `api_key` field, matching the `Open WebUI` item's field-naming style).
