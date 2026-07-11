# disk-monitor

Disk usage monitoring with rate-of-change detection and alerting.

**What it does:**
- Checks `/` and `/srv` disk usage on picklelab every 2 hours
- Tracks usage history in CSV (rate calculation, trend analysis)
- Alerts when:
  - Usage > 80% (warning) or > 90% (critical)
  - Fill rate > 2GB/day or > 5%/week
  - Time to full < 7 days
- Silent when all is well (no spam)

**Commands:**

| Command | What |
|---------|------|
| `just disk-monitor-check` | Run manual check (dry-run, outputs to stdout) |
| `just disk-monitor-status` | Show recent history and current trend |

**Alert delivery:** Via Hermes cron job → Telegram (or configured channel).

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
