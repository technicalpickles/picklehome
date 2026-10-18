# 2. host-side-deploy-lock

Date: 2026-10-18

## Status

Accepted.

## Context

Several parallel agent sessions (different worktrees, same Mac) can run `just deploy-<service>` at once. Nothing stopped two deploys interleaving on picklelab, and they share state: the `/opt/homelab` checkout (`git pull`), docker, systemd, sudoers. `deploy-openclaw` is also several ssh/scp calls, so a lock around only `deploy.sh` would leave its copy steps unprotected.

## Decision

One host-wide lock: `flock -n` on `/run/lock/homelab-deploy.lock` on picklelab (tmpfs, world-writable, so no sudoers change). Fail fast, naming the holder (recipe, user@host:worktree, start time) from `/run/lock/homelab-deploy.info`.

- `just` deploy recipes hold it for the whole recipe through one background ssh that stays open on a fifo (`scripts/deploy-lock.sh`). Closing it, or the Mac or network dying, releases the lock.
- Every `deploy.sh` and `setup-*.sh` sources `homelab/scripts/deploy-lock.sh`, so hand-run scripts on the host take it too. The recipes pass `HOMELAB_DEPLOY_LOCK_HELD=1` on their final ssh so it doesn't self-deadlock.

## Alternatives considered

- **Mac-side lock** (lockfile/`flock` on the Mac): covers one machine only, and macOS has no `flock(1)`.
- **Per-service locks**: deploys share the git checkout, docker and sudoers, so they aren't independent.
- **PID lockfile**: goes stale on a crash; `flock` is released by the kernel on process death.
- **Wait with timeout**: friendlier for queued sessions, but chosen against; fail fast is simpler and the message says who to wait for.

## Consequences

- A collision exits 75 with the holder's name; re-run when it finishes.
- The lock is a convention among our scripts. Ad hoc `docker`/`systemctl` over ssh ignore it.
- Children that inherit fd 9 from a hand-run script would keep it held; none of the current ones background anything.
