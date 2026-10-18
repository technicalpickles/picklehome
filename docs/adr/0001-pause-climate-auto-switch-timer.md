# 1. pause-climate-auto-switch-timer

Date: 2026-10-18

## Status

Accepted. Temporary: revisit by 2026-10-25 (taskwarrior project `picklehome.climate.ecobee`, due that date).

## Context

The house still isn't comfortable. Comfort is being tuned by hand on the thermostats (Eco+ was turned off, plus manual holds and customizations), and `climate-auto-switch` fights that: every 15 minutes it can switch Comfort Heat/Cool and, with `--clear-holds`, resume the program.

Two things made a plain "stop the timer" insufficient:

- `climate-auto-switch.timer` is `enabled` on picklelab, so a reboot restarts it.
- `deploy.sh` ran `systemctl enable` and `systemctl restart` on every deploy, so any `just deploy-climate` (for an unrelated climate change) would silently resume automation.
- Disabling the unit needs a sudo password on picklelab (the passwordless allowlist covers `enable`/`start`/`stop`/`restart` but not `disable`), so it can't be done from an agent session.

## Decision

1. Stop the timer on picklelab (`systemctl stop`, allowlisted). It stays `enabled`.
2. Add a `TIMER_PAUSED=1` guard in `homelab/services/climate-auto-switch/deploy.sh` so deploys still build the image, link units, and `daemon-reload`, but skip `enable` and `restart` of the timer.
3. Leave the thermostats as they are. No holds are cleared and no schedule is pushed.

## Consequences

### Positive

- Manual holds and tuning stick; nothing writes to the Ecobees on a timer.
- Climate code changes can still be deployed without resuming automation.

### Negative

- A picklelab reboot still restarts the timer, since it remains enabled. Closing that needs `sudo systemctl disable` run interactively (`ssh -t`).
- The pause lives in a script constant, so it is easy to forget. Mitigation: the taskwarrior reminder due 2026-10-25.

### Resuming

1. Set `TIMER_PAUSED=0` (or delete the guard) in `deploy.sh`.
2. `ssh -t picklelab sudo systemctl enable --now climate-auto-switch.timer`.
3. Consider `--clear-holds` for the first run if leftover holds should be dropped.
