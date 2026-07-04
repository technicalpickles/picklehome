# Docker prune timer + disk investigation tooling

## Context

On 2026-07-03 `/srv` on picklelab hit 100% (30G volume), which wedged the
second-brain-agent container. Diagnosis: `/srv/data` (the data we actually care
about) was only 3.5G. The disk was eaten by Docker build churn with nothing
reaping it:

| Path | Size | What |
|------|------|------|
| `/srv/containerd` | 14G | main Docker's images/layers (containerd snapshot store) |
| `/srv/ci-docker` | 3.5G | CI runner's **separate rootless** dockerd (ci user, uid 2000) |
| `/srv/data` | 3.5G | vault + service data |
| `/srv/backups` | 2.8G | restic, healthy |

This Docker uses the containerd image store (`Storage Driver: overlayfs`,
`driver-type: io.containerd.snapshotter.v1`), so images live in
`/srv/containerd`, not `/srv/docker`. There is no separate volume for Docker —
it shares `vg0-srv` with everything else.

Two independent Docker daemons (main + rootless `ci`) both accumulate dangling
layers and build cache forever. That is the failure mode. A manual
`docker builder prune` + `docker image prune` reclaimed ~5.3G and dropped `/srv`
to 85%.

A second friction surfaced during the investigation: every `du` on a root-owned
`/srv/*` dir and every `vgs`/`lvs` bounced off a sudo password prompt, so
diagnosis meant hand-chaining commands back through the human. Worth fixing at
the same time.

## Goals

1. **Automated cleanup** so build churn can't silently walk `/srv` to 100% again.
2. **Passwordless disk investigation** so the disk picture is one command, no
   prompt, no chaining.

## Non-goals

- Reaping old *tagged* image versions (the aggressive `docker image prune -a`
  path). Dangling-only never touches a tagged/deployed image, needs zero
  bookkeeping, and kills the actual failure mode. Rejected `-a` for the marginal
  savings and real risk of nuking a stopped-but-needed image mid-deploy.
- Splitting Docker onto its own LVM volume. That's the durable structural fix
  but it has downtime; tracked separately (taskwarrior 248).
- Growing `vg0-srv` (a `lvextend -r -L +30G /dev/vg0/srv`, done by hand out of
  band; `vg0` has ~49G VFree).

## Design

### Part 1 — `docker-prune` systemd timer

Mirrors the `backup` service exactly: host-level systemd oneshot + timer + shell
script. No container, no `.env` (no secrets).

**`docker-prune.sh`** (runs as root):
```
disk-report                       # log the before picture (shared util, see Part 2)
# main dockerd
docker builder prune -f
docker image prune -f             # DANGLING ONLY — never -a, never --volumes
# rootless ci dockerd (uid 2000)
sudo -iu ci docker builder prune -f
sudo -iu ci docker image prune -f
disk-report                       # log the after picture
# exit non-zero if /srv is STILL > 85% after pruning
```

Design points:

- **Runs as root.** Root is the only user that cleanly reaches *both* daemons:
  the main one directly, and the ci rootless one via `sudo -iu ci docker …`
  against its socket at `/run/user/2000/docker.sock`.
- **Dangling + cache only.** The deployed image keeps its tag; dangling prune
  reaps the *previous* build (now `<none>`). No keep-list needed — the tag is the
  keep marker and Docker already tracks it. Hardcoded, never `-a`/`--volumes`.
- **The "still full" guard.** Script exits non-zero if `/srv` is above 85% after
  the prune, so systemd marks the run failed and it surfaces — instead of the
  prune quietly falling behind until we're back at 100%.

**`docker-prune.timer`**: weekly, **Saturday 04:00** (after the 3am nightly
backup, low-activity day). `Persistent=true` so a run missed while the box is
asleep fires on next boot.

**`docker-prune.service`**: `Type=oneshot`, `User=root`,
`ExecStart=/opt/homelab/homelab/services/disk-hygiene/docker-prune.sh`.

### Part 2 — `disk-report` utility + passwordless sudo

A single **root-owned** script installed to `/usr/local/sbin/disk-report`
(root:root, `0755`, **not** writable by `technicalpickles`), running the fixed
read-only diagnostic bundle:

- `df -h /srv /`
- `du -xh -d1 /srv` and `du -xh -d1 /srv/data`
- LVM free space: `vgs`, `lvs`, `pvs`
- `docker system df` for both roots (main + `sudo -iu ci docker system df`)

sudoers grants exactly one thing:
```
technicalpickles ALL=(root) NOPASSWD: /usr/local/sbin/disk-report
```

Investigating disk = `sudo disk-report`. One command, no prompt, no chaining.

**Why a fixed root-owned script, not per-binary NOPASSWD:** pinning one script
that root controls locks down *what* runs as root. It must be installed
root-owned and non-user-writable — if it lived writable in the repo checkout,
NOPASSWD on it would be a clean root escalation (edit the script, run anything).
So `deploy.sh` installs it to `/usr/local/sbin` with root ownership, separate
from the repo. Rejected NOPASSWD on `du`/`vgs`/`lvs` individually: broader
(passwordless `sudo du <anything>` is a whole-filesystem info-disclosure
primitive, args unpinnable).

**Reuse:** `docker-prune.sh` calls `disk-report` for its before/after logging, so
there's one source of truth for "what does the disk look like."

### File layout

Everything lives in `homelab/services/disk-hygiene/`:

```
homelab/services/disk-hygiene/
  docker-prune.sh        # the prune job (root)
  docker-prune.service   # oneshot unit
  docker-prune.timer     # weekly Sat 04:00
  disk-report.sh         # read-only diagnostic bundle; installed to /usr/local/sbin
  docker-prune.sudoers   # the NOPASSWD line; installed to /etc/sudoers.d/
  deploy.sh              # install script + units + sudoers, enable timer
  README.md
```

The dir is named `disk-hygiene` (broader than `docker-prune`) because it houses
both the prune timer *and* the general `disk-report` investigation utility. The
systemd unit inside is still named `docker-prune.timer`/`.service` — the dir is
the category, the unit is the specific job.

### Deploy (`deploy.sh`)

Mirrors `backup/deploy.sh`. Steps:

1. Install `disk-report.sh` → `/usr/local/sbin/disk-report`, `chown root:root`,
   `chmod 0755`.
2. Install `docker-prune.sudoers` → `/etc/sudoers.d/docker-prune`, `chmod 0440`,
   validate with `visudo -cf` before activating (a broken sudoers file can lock
   out sudo — validate or bail).
3. **Verify the ci rootless socket is reachable** (`sudo -iu ci docker version`).
   Fail loudly if not, rather than silently pruning only half the box. (Depends
   on `ci` lingering, set up by the woodpecker rootless-docker install.)
4. Symlink `docker-prune.service` + `docker-prune.timer` into
   `/etc/systemd/system/`, `daemon-reload`, `enable --now` the timer.
5. Print timer status + next run.

### `just` commands (mirror `backup`)

- `just deploy-docker-prune`
- `just docker-prune-now` — trigger the service once
- `just docker-prune-status` — timer + last-run status
- `just docker-prune-logs` — journal for the unit
- `just disk-report` — run `sudo disk-report` on picklelab over SSH

## Testing / verification

- **Dry-run safety:** confirm `docker image prune -f` on the box lists only
  `<none>` images before wiring the timer (no tagged image in the removal set).
- **ci reach:** `sudo -iu ci docker version` succeeds from the deploy.
- **Guard:** temporarily lower the threshold and confirm the script exits
  non-zero + the unit shows failed when `/srv` is "over."
- **sudoers:** `sudo disk-report` runs with no password; `visudo -cf` passes.
- **First real run:** `just docker-prune-now`, confirm reclaimed space in the
  before/after `disk-report` output and `/srv` stays well under 85%.

## Followups (already in taskwarrior)

- **247** (`picklehome.homelab.backup`) — this work.
- **248** (`picklehome.homelab`) — dedicated Docker LVM volume (structural fix,
  needs a maintenance window).
