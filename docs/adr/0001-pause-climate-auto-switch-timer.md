# 1. pause-climate-auto-switch-timer

Date: 2026-10-18

## Status

Accepted. Temporary: revisit by 2026-10-25 (taskwarrior project `picklehome.climate.ecobee`, due that date).

## Context

The house still isn't comfortable. Comfort is being tuned by hand on the thermostats (Eco+ was turned off, plus manual holds and customizations), and `climate-auto-switch` fights that: every 15 minutes it can switch Comfort Heat/Cool and, with `--clear-holds`, resume the program.

Two things made a plain "stop the timer" insufficient:

- `climate-auto-switch.timer` was `enabled` on picklelab, so a reboot would restart it.
- `deploy.sh` ran `systemctl enable` and `systemctl restart` on every deploy, so any `just deploy-climate` (for an unrelated climate change) would silently resume automation.
- Disabling the unit needs a sudo password on picklelab (the passwordless allowlist covers `enable`/`start`/`stop`/`restart` but not `disable`), so it can't be done from an agent session.

## Decision

1. Stop and disable the timer on picklelab. `stop` is passwordless; `disable` needed an interactive sudo password. Because the unit was installed as a symlink into `/etc/systemd/system` (by `deploy.sh`'s `ln -sf`), `disable` also removed that symlink, so `systemctl` now reports the unit as `not-found`.
2. Add a `TIMER_PAUSED=1` guard in `homelab/services/climate-auto-switch/deploy.sh` so deploys still build the image, link units, and `daemon-reload`, but skip `enable` and `restart` of the timer.
3. Leave the thermostats as they are. No holds are cleared and no schedule is pushed.

## Consequences

### Positive

- Manual holds and tuning stick; nothing writes to the Ecobees on a timer.
- Climate code changes can still be deployed without resuming automation.

### Negative

- Resuming is not just `enable --now`: the unit symlink is gone, so it takes a deploy (which re-links it) first.
- The pause lives in a script constant, so it is easy to forget. Mitigation: the taskwarrior reminder due 2026-10-25.

### Resuming

1. Set `TIMER_PAUSED=0` (or delete the guard) in `deploy.sh`, commit, push to `main`.
2. `just deploy-climate`. It re-links the unit, enables, and restarts the timer.
3. Consider `--clear-holds` for the first run if leftover holds should be dropped.
