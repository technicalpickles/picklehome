# disk-monitor

Disk usage monitoring with rate-of-change detection and alerting.

**What it does:**
- Checks `/`, `/srv`, `/srv/containerd` and `/srv/ci-docker` on picklelab over ssh.
  A mount that doesn't exist yet (before the Docker split) is skipped, not an error
- Tracks usage history in CSV (rate calculation, trend analysis)
- Alerts when:
  - Usage > 80% (warning) or > 90% (critical)
  - Time to full < 7 days at the 24h fill rate. A fast rate with plenty of
    runway does not alert on its own
- Silent when all is well (no spam). An unchanged alert is sent once, then at
  most daily. A new mount or an escalation to critical sends immediately. State
  lives in `disk-monitor-alert.json` next to the history CSV
- Lists only the breaching mounts, each with a next step. The full
  `disk-report` is attached at critical only
- **Loud when it can't look.** If picklelab is unreachable it prints an alert and
  exits 1, so a broken monitor never looks like a healthy one

**Status:** `just deploy-disk-monitor` installs `disk-monitor.timer` on picklelab,
which runs the monitor every 2 hours as root in local mode
(`DISK_MONITOR_LOCAL=1`, no ssh). Alerts go to Telegram through the `notify`
service, so run `just deploy-notify` first. Run it now with
`just disk-monitor-run-now`. Before that deploy, nothing schedules it. The old
Hermes cron job in the `kenny-chen` OrbStack VM is stale (it ran once on
2026-08-18 and then hit `Too many open files`) and is not part of this.

**ssh user:** unset by default, so it runs plain `ssh picklelab.<tailnet>`, which
uses `~/.ssh/config` or your local username. Set `DISK_MONITOR_SSH_USER` to
override. It used to be hardcoded to `kenny`, the account the VM's Hermes agent
uses; this Mac has no key for it. Anything running this as `kenny` should set
`DISK_MONITOR_SSH_USER=kenny` (or run as that user, where plain ssh uses it).

**Commands:**

| Command | What |
|---------|------|
| `just disk-monitor-check` | Run one check now. Prints an alert if there is one, and appends to the history CSV either way |
| `just disk-monitor-status` | Show recent history and current trend (the Mac's CSV, not picklelab's) |
| `just deploy-disk-monitor` | Install the timer on picklelab |
| `just disk-monitor-run-now` | Start the picklelab service once and show its journal |

**Alert delivery:** stdout. On picklelab, `disk-monitor-run.sh` pipes it to `notify-telegram.sh`.

**History file:** `~/.local/state/picklehome/disk-monitor.csv`, or the path in `DISK_MONITOR_CSV`. On picklelab it is `/var/lib/disk-monitor/disk-monitor.csv`.

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
