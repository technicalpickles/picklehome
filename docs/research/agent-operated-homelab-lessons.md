# Lessons from running a homelab with several agent sessions at once

Written 2026-10-18 after about five days of parallel Claude Code sessions deploying to and operating picklelab. Two patterns cost the most time and generalize beyond this repo: deploy preconditions and services that don't recover on their own.

## Deploy preconditions

Deploy recipes (`just deploy-<service>`) refuse to run unless the checkout is clean, on `main`, and equal to `origin/main`. That is the right guard for a single operator. With several sessions sharing one checkout it breaks in two ways.

**Dirty tree from someone else's work.** One session's uncommitted edits in the main checkout blocked another session's deploy. The deploying session correctly left the edits alone and handed the problem back, which cost a human round trip of roughly 15 minutes. The workaround that worked: deploy from a throwaway worktree of `origin/main`. The guard cares about what gets deployed, not about the state of the shared checkout.

**Concurrent deploys.** Nothing stopped two sessions from deploying at once, and they share state: the same `/opt/homelab` checkout, the same docker daemon, the same unit files. A host-wide `flock` now serializes every deploy on picklelab. It is global, not per service, for that reason.

What I'd do for a new homelab:

- Make deploys build from a clean, disposable checkout of the target ref, not the working copy.
- Serialize on the host, not in the recipe, so hand-run setup scripts take the same lock.
- Keep the "must be on main and pushed" rule. It is cheap and prevents deploying unreviewed code.

## Units that don't recover on their own

The costliest incident in the period was not a bug. After a reboot, a systemd unit wrapping `docker compose` in `op run` failed once because DNS wasn't ready yet. The unit was `Type=oneshot` with no `Restart=`, so it stayed failed. The service was down for six days with nothing alerting. A second unit with the same shape failed the same way; its containers kept running unmanaged, and the next deploy then failed in confusing ways (a stop that was a no-op on a failed unit, and a health-check loop shorter than a cold start).

Patterns that would have prevented it:

- Every unit that depends on the network gets `Restart=on-failure` with a delay, and waits for name resolution before starting (an `ExecStartPre` that polls `getent hosts`).
- A stop step in a deploy script must verify the thing actually stopped (containers gone), not just that `systemctl stop` returned 0.
- Health-check timeouts should be longer than the measured cold start, with headroom.
- Something must alert when a service is down. The repo now has a small watchdog for one service; the same idea applies to the rest.

## Smaller findings

- A merged config change is not a live one. Deploys that render config should be followed by a check that compares the running state to what was intended. A plugin that showed as `loaded` but was never imported (a missing `enabled` key) took a second deploy cycle to find.
- Agent sessions are limited to read-only probes on the host by design. Keep a documented read-only query path (allowlisted commands, redacted output) so diagnosis doesn't need a human, and keep the host-side checkout it reads from fresh.
- Passwordless sudo should cover the exact commands deploys and routine operations need. Each gap becomes a human hand-off.
