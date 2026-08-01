# Nikke roster scanner as a picklelab service

## Why this exists

The nikke roster dashboard currently runs inside a coi container on the
`pickled-coi` OrbStack VM, kept alive by a detached tmux session. That setup has
three problems that no amount of tuning fixes:

- **The URL keeps moving.** coi auto-allocates a host port per workspace slot,
  so the dashboard lives at `http://<vm-ip>:21080` and `nikke-serve` has to
  discover and print the port on every run.
- **The container is ephemeral.** `coi list` reports it as ephemeral, so a stop
  is a delete. Bring-up depends on a guard around `coi shell`, which is not
  idempotent and will pile up containers if the guard is ever skipped.
- **It only exists while the Mac is awake.** An OrbStack VM stops when the host
  sleeps, so "check my roster from my phone" was never going to work.

picklelab is always on, already runs Docker Compose, already terminates HTTPS
with Tailscale Services, and already takes nightly restic snapshots of
`/srv/data`. Moving nikke there solves all three problems by inheriting
infrastructure that already exists, rather than rebuilding any of it on the VM.

## Scope

Three repos:

- **picklehome**: a new `homelab/services/nikke/` service directory plus Justfile
  recipes. Most of the new code.
- **nikke-roster-scanner**: a `Dockerfile` and `.dockerignore`, and deletion of
  the coi-specific `nikke-serve`, `nikke-sync`, and `lib/nikke-container.sh`.
- **pickled-coi**: no deployment role anymore. The `coi --profile nikke` profile
  stays for interactive development. A `docs/findings.md` entry records what we
  learned about incus OCI images so nobody re-derives it.

## Architecture

`homelab/services/nikke/`, modeled on `brineworks-server` (external private
repo, Tailscale Service, loopback binding) with `climate-auto-switch`'s timer
shape for scheduled sync.

| File | Purpose |
|---|---|
| `compose.yaml` | `serve` and `sync` services, both from `nikke:local` |
| `compose.picklelab.yaml` | build context, loopback port binding, `/srv/data/nikke` mount |
| `deploy.sh` | pull app source, write `.env.build`, prep data dir, register the Tailscale Service, link and restart units, health check |
| `nikke.service` | long-lived serve unit |
| `nikke-sync.service` + `nikke-sync.timer` | 6-hourly sync |
| `README.md` | per-service reference |

nikke has no secrets. The blablalink session is a file on the data volume, not
an environment variable, and there's no database password or API key. So,
unlike every other service, nikke ships **no** `.env.vars`: an empty-but-present
`.env.vars` was the original design, but `scripts/service-env` builds its key
list with a `grep -v '^#'` pipeline, and a comment-only file makes that grep
match nothing, so the command substitution exits 1 and takes the
`set -euo pipefail` `deploy-nikke` recipe down with it. `just deploy-nikke`
skips the filtered-env/scp step entirely as a result. Add `.env.vars` and the
scp block back together if nikke ever gains a secret.
`NIKKE_PORT` is not a secret either, so it comes from `deploy.sh` writing
`.env.build`, the same way `brineworks-server` handles `BRINEWORKS_SERVER_PORT`.

### One image, two compose services

`serve` and `sync` are the same codebase invoked with different subcommands, so
they share one image built from the nikke-roster-scanner repo:

```yaml
services:
  serve:
    image: nikke:local
    restart: unless-stopped
    command: >
      nikke-scan serve --host 0.0.0.0
      --port ${NIKKE_PORT:?set by deploy.sh}
      --db /data/roster.db

  sync:
    image: nikke:local
    command: >
      nikke-scan blablalink sync --headless
      --db /data/roster.db
```

`serve` binds `0.0.0.0` inside the container, which is the container's own
interfaces, not the host's. Restricting exposure happens at the compose
`ports:` line below, which publishes to host loopback only.

`sync` never starts on its own. The timer runs it with `docker compose run --rm
sync`, matching how `climate-auto-switch` already works. Playwright and chromium
ship in the image because sync needs them. Serve doesn't, but splitting into two
images to save disk on a NUC isn't worth the second build.

Building on picklelab means amd64 instead of the VM's arm64, which is the
better-trodden path for Playwright's chromium.

### Where the source comes from

The Dockerfile lives in nikke-roster-scanner, matching brineworks. `deploy.sh`
clones the repo to `/opt/nikke-roster-scanner` on first run and
`git pull --ff-only`s it after that, then records the SHA in `.env.build` so the
running image is traceable to a commit:

```yaml
  serve:
    build:
      context: /opt/nikke-roster-scanner
      dockerfile: Dockerfile
      args:
        GIT_SHA: ${NIKKE_GIT_SHA:-unknown}
```

`.env.build` is loaded by both the systemd unit (`EnvironmentFile=`) and the
container (`env_file:`). The unit path is what makes compose's strict
`${NIKKE_PORT:?}` interpolation succeed when systemd restarts the service with
an otherwise-empty environment.

### Networking and TLS

Tailscale Services, the standard pattern from `homelab/services/README.md`. The
container binds loopback only:

```yaml
    ports:
      - "127.0.0.1:${NIKKE_PORT:?set by deploy.sh}:${NIKKE_PORT:?set by deploy.sh}"
```

and `deploy.sh` registers the service:

```sh
sudo tailscale serve --service=svc:nikke --https=443 "http://127.0.0.1:$NIKKE_PORT"
```

The dashboard ends up at `https://nikke.tail2023b7.ts.net`, with no port in the
URL and no reverse proxy container. `NIKKE_PORT` defaults to 8770.

Tailscale Services is the right pattern here rather than the container-as-node
sidecar that `second-brain-agent` and `brineworks-agent` use. Those need a real
tailnet node because mosh needs UDP and `tailscale serve` is TCP only. A web
dashboard is TCP, so it gets a service instead of a node, and the tailnet device
list stays clean.

### Data

`/srv/data/nikke/` holds `roster.db` and `.blablalink-session.json`, mounted at
`/data`. Both containers run as an explicit `user: "1000:1000"`, and `deploy.sh`
chowns the directory after `mkdir -p` and before `docker compose up`, per the
bind-mount rules in `homelab/services/README.md`.

The `serve` and `sync` containers both touch `roster.db`, and sync runs while
serve is up. SQLite handles that as long as both processes use the same uid,
which the shared `user:` guarantees.

Nightly restic already snapshots everything under `/srv/data` with 7/4/6 GFS
retention, so the roster history is backed up from the first deploy with no
registration step.

### Auth

Blablalink login needs a real browser and picklelab is headless, so login stays
on the Mac. A `just nikke-login` recipe runs the headed login locally, then
copies the session file up:

```sh
scp .blablalink-session.json picklelab:/tmp/
ssh picklelab "sudo install -o 1000 -g 1000 -m 600 /tmp/.blablalink-session.json /srv/data/nikke/ && rm /tmp/.blablalink-session.json"
```

The container finds it via `NIKKE_SESSION_PATH=/data/.blablalink-session.json`,
an environment variable the CLI already reads.

Sessions expire, so the dashboard is how you find out you need to re-run login.
`nikke-scan blablalink sync` already records every attempt to the
`sync_attempts` table and already categorizes a dead session as `auth_expired`.
The staleness banner reads that table and tells you to run `just nikke-login`.
No separate alerting.

### Scheduled sync

```ini
[Timer]
OnCalendar=*-*-* 00/6:00:00
Persistent=true
```

`Persistent=true` matters: picklelab reboots, and without it a missed window is
just skipped. The service unit is `Type=oneshot` running `docker compose run
--rm sync`, same as `climate-auto-switch`.

Sync failures are recorded rather than alerted. The `error_category` values
already exist (`auth_expired`, `infra`, `other`) and drive the banner.

## Deploying

Standard picklehome shape, added to the Justfile alongside the others:

```sh
just dotenv        # refresh secrets from 1Password
just deploy-nikke  # push, git pull on host, scp filtered .env, run deploy.sh
```

Plus `nikke-logs` and `nikke-logs-follow` recipes matching the brineworks pair.

## Migrating the existing data

`roster.db` on the VM is 13MB of real scan history and can't be regenerated, so
it moves rather than starting fresh. One time, before the first deploy:

```sh
orb -m pickled-coi bash -lc 'cd ~/projects/nikke-roster-scanner && sqlite3 roster.db ".backup /tmp/roster-migrate.db"'
# copy /tmp/roster-migrate.db to picklelab:/srv/data/nikke/roster.db, chown 1000:1000
```

Use `.backup` rather than `cp` so the copy is consistent even if something is
mid-write. Verify the character count matches on both sides before deleting
anything on the VM, and leave the VM copy in place until the new deploy has
completed a successful sync.

## Cleanup after cutover

In nikke-roster-scanner: delete `nikke-serve`, `nikke-sync`,
`lib/nikke-container.sh`, and `systemd/nikke-sync.{service,timer}`. All of it
exists to work around coi container lifecycle, which no longer applies. `coi-run`
stays, since interactive development in coi still happens.

In pickled-coi: keep `coi/profiles/nikke/` for development sessions. Update the
README's nikke section to point at picklehome instead of describing
`nikke-serve`. Add a `docs/findings.md` entry for the incus OCI research below.

## Gotchas

These come from reading the existing services, and are worth getting right the
first time rather than debugging later.

**Tailscale Services need approval, and tailscaled doesn't notice it happened.**
On the first deploy, the service shows up pending at
`https://login.tailscale.com/admin/services`. After approving, you have to
re-advertise by hand:

```sh
sudo tailscale serve --service=svc:nikke --https=443 off
sleep 2
sudo tailscale serve --service=svc:nikke --https=443 "http://127.0.0.1:$NIKKE_PORT"
```

`brineworks-server/deploy.sh` prints this on health-check failure. Copy that.

**HTTPS has to be enabled in the tailnet admin console.** One-time, already done
for the other services, but a fresh tailnet would need it.

**`.dockerignore` is load-bearing.** `roster.db` is data and
`.blablalink-session.json` is live auth material. Neither belongs in an image
layer. Also exclude `.venv`, `.venv-coi`, and `scratch/`.

**The `--db` flag has no environment variable.** It defaults to `roster.db`
relative to the working directory, so both compose services pass
`--db /data/roster.db` explicitly. Forgetting it writes to a container-local
file that vanishes on the next `run --rm`.

**Debugging a Tailscale Service** has its own set of traps (status looking
wrong, self-curl hanging). Use the `tailscale-cli` skill rather than
rediscovering them.

## Testing

- `deploy.sh` health checks, matching brineworks: curl the local port first,
  then the tailnet URL, so a failure tells you which half broke.
- Manual smoke after first deploy: dashboard loads over the tailnet URL from the
  Mac and from the phone, character count matches the migrated database, a
  manual `systemctl start nikke-sync.service` completes and writes a
  `sync_attempts` row.
- Deliberately corrupt the session file, run sync, confirm the attempt records
  `auth_expired` and the banner appears.
- Reboot picklelab, confirm serve comes back and the timer re-arms.

## What we learned about incus, and why it isn't here

The first pass at this design tried to keep nikke on the pickled-coi VM as an
incus application container. That's recorded in pickled-coi's `docs/findings.md`,
but the short version, since it cost real time to establish:

- `incus image import` only accepts incus's own format. Handing it an
  `oci-archive` fails with "Metadata tarball is missing metadata.yaml".
- `incus remote add --protocol oci` only accepts `https://` URLs. No `file://`,
  no local path, no plain HTTP. So running a locally built OCI image on incus
  means standing up a registry.
- An incus image is two tarballs: a metadata tarball holding a 104-byte
  `metadata.yaml` plus an umoci-generated `config.json`, and a flat rootfs
  tarball. Exporting an OCI-derived image and re-importing the raw tarballs
  produces a working `CONTAINER (APP)`, so hand-assembling one locally is
  possible.

All true, all irrelevant once picklelab is the target, because Docker Compose is
already there. Recorded so the next person doesn't spend an evening on it.

## Open risks

- **Playwright in the image is untested here.** The nikke coi profile solved
  chromium dependencies for arm64 Ubuntu; the Dockerfile re-solves them for
  amd64. Shipped as `python:3.13-slim` plus
  `playwright install --with-deps chromium` rather than the official
  Playwright base image: it does the same apt work, but keeps the chromium
  version tied to the `playwright` pin in `uv.lock` instead of a
  separately-versioned base image tag -- same outcome, one fewer version to
  keep in sync.
- **Sync duration versus timer interval.** Sync took about 16 seconds against a
  warm coi container. A cold `docker compose run --rm` adds container start
  time but not much. Not expected to approach the 6-hour window, so no
  overlap protection is designed in.
- **uid 1000 is assumed available.** It matches what most picklelab services
  already use, and nothing in `/srv/data/nikke/` is shared with another service,
  so there's no cross-service uid coupling to get wrong.
