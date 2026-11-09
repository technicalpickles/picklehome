# Picklelab alerting: disk monitor timer and backup failure hook

Status: design sketch, 2026-11-09. A point-in-time doc; check the code and `git log` before trusting it.

## Problem

Nothing on picklelab tells Josh when something breaks. The disk monitor never ran on a schedule (see `homelab/services/disk_monitor/README.md`), and `backup.service` failed nightly for weeks with nobody notified. Josh made a dedicated Telegram bot, `picklehomealertbot`, and a 1Password item `Picklelab Alerts Telegram` in the `picklehome` vault with fields `credential` (token) and `chat_id`.

Constraints found while grounding:

- Deployed services get secrets from `op run --env-file=<filtered template>` with `EnvironmentFile=/etc/opt/homelab/op-token-picklehome`. The filtered template comes from a service's `.env.vars` list via `scripts/service-env`. The picklelab service account can only read the `picklehome` vault.
- A unit is installed by `deploy.sh`: `sudo ln -sf` into `/etc/systemd/system/`, `daemon-reload`, `enable`, `restart`. Those three sudo commands are on the passwordless list. Anything else needs Josh's password.
- `disk_monitor.py` already prints its alert to stdout and stays silent when healthy. Its ssh transport is wrong for a monitor that runs on the box itself.
- `homelab/scripts/notify_telegram.py` (committed) reads stdin and posts it. It knows nothing about 1Password or systemd.

## Usage (caller's view)

A consumer pipes text into one command and never sees a token, an env file, or an API.

```
# disk-monitor.service
ExecStart=/opt/homelab/homelab/scripts/disk-monitor-run.sh

# disk-monitor-run.sh
python3 disk_monitor.py | notify-telegram

# backup.service, one added line
OnFailure=notify-failure@%n.service

# notify-failure@.service (template, instance = the failed unit)
ExecStart=/bin/bash -c 'journalctl -u %i -n 25 --no-pager | /opt/homelab/homelab/scripts/notify-telegram.sh'
```

A third consumer later adds one `OnFailure=` line.

## Shape

One owner for delivery, and consumers that only pipe.

| Piece | Owns |
|---|---|
| `homelab/scripts/notify_telegram.py` | stdin to Telegram. Plain text, truncation, exit codes, token redaction. Done. |
| `homelab/scripts/notify-telegram.sh` | The secret plumbing. Reads the op service-account token, runs the python notifier under `op run` with the notify service's filtered template. Callers pass nothing but stdin. |
| `homelab/services/notify/` | The single list of alert env vars (`.env.vars`), the `deploy.sh` that writes the filtered template and links `notify-failure@.service`, and its README. |
| `homelab/services/disk_monitor/` | `disk-monitor.service` and `.timer`, `deploy.sh`, and the monitor itself. |
| `backup.service` | One `OnFailure=` line. Nothing else changes. |

Monitor changes: a local mode (`DISK_MONITOR_LOCAL=1`) that runs its two commands with `bash -c` instead of ssh, and `DISK_MONITOR_CSV` to place the history file. The service uses `StateDirectory=disk-monitor`, so history lives in `/var/lib/disk-monitor/` and not in root's home. History is regenerable, so it stays out of restic.

Interface depth. `notify-telegram` hides the token source, the filtered template path, `op run`, the Telegram API, truncation, and failure behavior behind "pipe text in". The caller learns nothing about any of them (per boundary-discipline: the plumbing sits at the edge, and consumers stay pure).

Failure behavior. The run script uses `set -o pipefail`, so the unit goes red if the monitor or the notifier fails. A notifier that cannot send exits non-zero with a message that never contains the token. `OnFailure` also covers crashes and `ExecStartPre` failures that an in-script hook could not see.

Local mode fails the same loud way as ssh mode: a `df` that returns nothing raises, `main()` prints the alert and exits 1.

## Synthesis decision

Arena was skipped. Five model runs (four runners and a cross-judge) buy little when three existing service patterns and the red-flags list already fix the shape. Two structurally different candidates were written and screened by hand. If a reviewer wants the bakeoff anyway, the Alternatives below are the seed.

## Tradeoffs accepted

- We accept one more service directory (`notify/`) in exchange for exactly one list of alert env vars and one place that knows how delivery works.
- We accept that the monitor and the notifier are two processes joined by a pipe, in exchange for the notifier staying reusable by the backup hook.
- We accept running both units as root, in exchange for no sudo plumbing (`disk-report` needs root anyway) and no ACL work for a state dir.
- We accept plain text with no formatting, in exchange for alert text with backticks never breaking Telegram's parser.

## Alternatives considered

- **Monitor-owned delivery.** The monitor posts to Telegram itself, and the backup unit calls curl in its own script. It loses on two red flags. It is two ways to do one task, and the env-var list would be hand-synced across two services. The monitor also becomes an alerting framework, which widens its interface for no gain.
- **Containerized like `climate-auto-switch`.** A Dockerfile, compose files, and `op run` around `docker compose run` for stdlib python the host already runs. It hides nothing and adds a build step.

## Implementation reconciliation

Deviations from the sketch, accepted after review on 2026-11-09. None changes the usage or the module ownership above.

- Both units set `User=root` explicitly. systemd sets `$HOME` only when `User=` is present, and `op` needs it.
- The wrapper sources the op token itself, so neither unit has an `EnvironmentFile=`.
- `disk-monitor.service` orders after `network-online.target`, mirroring `backup.service`.
- `disk-monitor-run.sh` lives in `homelab/scripts/`, next to the notify wrapper, and not in the service dir.
- `deploy-disk-monitor` passes the directory name `disk_monitor` (underscore) to `_deploy-remote`.
- `disk-monitor-run-now` uses `;` and not `&&`, so the journal prints when the oneshot fails.
- The timer is `OnCalendar=*-*-* 0/2:00:00` with `Persistent=true` and 300 seconds of jitter. `systemd-analyze calendar` on picklelab normalizes it to `00/2` and shows the next fire at 20:00 UTC.
- The monitor's failure alert says "could not check picklelab" in both modes, changed from "could not reach" because a failed `df` in local mode is not a network problem.

## Open questions and risks

- Should a failed `notify-failure@` (Telegram down) retry, or only log? The sketch says log and stay quiet, since an alert about a failed alert has nowhere to go.
- The first deploy needs `sudo` for nothing new, but `deploy-notify` must run before `deploy-disk-monitor`, because the monitor's wrapper reads the notify template. Should `deploy-disk-monitor` call it, or should a missing template fail loudly?
- Does the group-chat idea need `message_thread_id` wired through 1Password now, or only the optional env var the script already reads?

## Next implementation step

Write failing tests for the monitor's local mode and `DISK_MONITOR_CSV`, then make them pass.
