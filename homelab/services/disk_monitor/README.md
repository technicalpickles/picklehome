# disk-monitor

Disk usage monitoring with rate-of-change detection and alerting.

**What it does:**
- Checks `/`, `/srv`, `/srv/containerd` and `/srv/ci-docker` on picklelab over ssh.
  A mount that doesn't exist yet (before the Docker split) is skipped, not an error
- Tracks usage history in CSV (rate calculation, trend analysis)
- Alerts when:
  - Usage > 80% (warning) or > 90% (critical)
  - Fill rate > 2GB/day or > 5%/week
  - Time to full < 7 days
- Silent when all is well (no spam)
- **Loud when it can't look.** If picklelab is unreachable it prints an alert and
  exits 1, so a broken monitor never looks like a healthy one

**Status:** nothing reliable schedules this. A Hermes cron job in the
`kenny-chen` OrbStack VM was meant to run it every 2 hours and deliver alerts
to Telegram, but it's stale: it ran on schedule once (2026-08-18), its path
still says `homelab/services/disk-monitor/` (the directory is now
`disk_monitor/`), Hermes logged `Failed to read cron database: Too many open
files`, and the VM was off for most of the time since. Where this should run
(that VM, this Mac, or a systemd timer on picklelab itself) and how alerts get
delivered are still open.

**ssh user:** unset by default, so it runs plain `ssh picklelab.<tailnet>`, which
uses `~/.ssh/config` or your local username. Set `DISK_MONITOR_SSH_USER` to
override. It used to be hardcoded to `kenny`, the account the VM's Hermes agent
uses; this Mac has no key for it. Anything running this as `kenny` should set
`DISK_MONITOR_SSH_USER=kenny` (or run as that user, where plain ssh uses it).

**Commands:**

| Command | What |
|---------|------|
| `just disk-monitor-check` | Run one check now. Prints an alert if there is one, and appends to the history CSV either way |
| `just disk-monitor-status` | Show recent history and current trend |

**Alert delivery:** stdout, for whatever scheduler runs it to forward.

**History file:** `~/.local/state/picklehome/disk-monitor.csv`

## Why

On 2026-07-03 `/srv` hit 100% and wedged second-brain-agent. The `disk-hygiene` service prevents future buildup with weekly docker pruning, but this service gives you **visibility** — you'll know before it's critical.

## Design

**Lofi approach:**
- Simple Python script, no external dependencies
- CSV for history (human-readable, survives restarts)
- Rate calculation over last 24 hours
- Alerts include diagnostic context (top paths, rate, ETA to full)

**Phase 2 (if useful):**
- Smarter trending (linear regression over 7 days)
- Separate alerts for sudden spikes vs slow creep
- Auto-remediation (trigger `docker-prune-now` at 85%)

## Related

- `disk-hygiene/` — Automated docker pruning + `disk-report` diagnostic
- `docs/plans/2026-07-03-docker-prune-and-disk-tooling.md` — Original incident
