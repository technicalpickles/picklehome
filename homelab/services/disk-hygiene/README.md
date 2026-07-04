# disk-hygiene

Keeps `/srv` from silently filling. Two pieces:

- **`docker-prune`**: a weekly systemd timer (Sat 04:00) that prunes dangling
  images + build cache on **both** docker roots: the main dockerd and the
  rootless `ci` dockerd (uid 2000). Dangling-only (`docker builder prune -f` +
  `docker image prune -f`); never `-a`, never `--volumes`, so no tagged/deployed
  image is ever removed. Fails the unit if `/srv` is still above 85% afterward,
  so a prune that can no longer keep up surfaces instead of rotting.
- **`disk-report`**: a root-owned read-only diagnostic installed to
  `/usr/local/sbin/disk-report`, made passwordless via a pinned sudoers line, so
  investigating disk is a single `sudo disk-report` (df, `/srv` du breakdown,
  LVM free space, `docker system df` for both roots) instead of a chain of sudo
  prompts.

## Why

On 2026-07-03 `/srv` (30G, shared by all services) hit 100% and wedged
second-brain-agent. Root cause: two docker daemons accumulating build churn with
nothing reaping it; `/srv/containerd` alone was 14G. See
[docs/plans/2026-07-03-docker-prune-and-disk-tooling.md](../../../docs/plans/2026-07-03-docker-prune-and-disk-tooling.md).

The structural follow-up (Docker on its own LVM volume) is tracked separately in
taskwarrior.

## Deploy

```bash
just deploy-disk-hygiene
```

Runs `deploy.sh` on the host: installs `disk-report` root-owned, validates the
sudoers drop-in with `visudo -cf` before activating it, verifies the rootless
`ci` docker is reachable, then symlinks + enables the timer.

## Commands

| Command | What |
|---------|------|
| `just deploy-disk-hygiene` | Install/update the tooling on picklelab |
| `just docker-prune-now` | Trigger a prune immediately, show the log |
| `just docker-prune-status` | Timer + last-run status |
| `just docker-prune-logs` | Tail the prune log |
| `just disk-report` | Run the disk diagnostic (passwordless) |

## Safety notes

- **`disk-report` must stay read-only.** It's pinned in sudoers, so anything it
  runs, it runs as root without a password. Installed root-owned and
  non-user-writable so the pin can't become a root-escalation hole.
- **Prune is dangling-only by design.** Reaping old *tagged* versions (`-a`) was
  deliberately rejected: it risks removing a stopped-but-needed image mid-deploy
  for marginal savings.
