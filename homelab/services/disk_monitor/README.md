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

**Status:** nothing schedules this yet. It only runs when you run it. The old
note about a "Hermes cron job" delivering to Telegram described the earlier
agent setup, which no longer exists. Where it should run (this Mac, or a
systemd timer on picklelab itself) and how alerts get delivered are both open.

**ssh user:** unset by default, so it runs plain `ssh picklelab.<tailnet>`, which
uses `~/.ssh/config` or your local username. Set `DISK_MONITOR_SSH_USER` to
override. It used to be hardcoded to `kenny`, an account for the earlier agent
that this Mac has no key for.

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
