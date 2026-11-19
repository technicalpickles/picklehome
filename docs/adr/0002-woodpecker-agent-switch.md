# 2. woodpecker-agent-switch

Date: 2026-10-18

## Status

Accepted. Ships disabled; enabled in phases (see the plan).

## Context

A second Woodpecker agent now runs in an OrbStack VM on the laptop (opt-in only: it takes pipelines labeled `host: laptop`, via a `!host` server-side filter). We want CI to prefer it while the laptop is awake and fall back to picklelab when it is not, without toggling anything by hand.

Woodpecker has no agent priority or fallback; labels and filters are hard match rules. It does expose `no_schedule` and `filters` per agent over the API, plus `last_contact`. The server also requeues a task whose agent stops extending its 1 minute lease, so work on a sleeping laptop is rerun, not lost.

The stock server and agent images are `FROM scratch` (no shell, no Python), so the logic cannot run inside them.

## Decision

A small stdlib Python reconcile script, run once a minute by a systemd timer as a profile-gated service in the woodpecker compose (`network_mode: service:ts-woodpecker`, so it calls `localhost:8000`). It flips the laptop agent's filter and picklelab's `no_schedule` from the laptop's `last_contact`, in an order that never leaves no agent able to take unlabeled work, and fails open to picklelab.

Rejected: building it into the agent or server image (scratch images, ties the logic to upstream's release cycle); a long-running sleep-loop sidecar (works, but a timer gives fresh-process isolation and per-run journald logs, matching `climate-auto-switch`); a standalone service outside the woodpecker compose (loses the shared netns, so it would have to reach a loopback-only port through Funnel).

## Consequences

### Positive

- Laptop-first CI with picklelab as the fallback, no manual toggling.
- Stateless, so a failed or skipped tick converges on the next one.
- Fully testable locally: pure `decide()` plus an in-process fake Woodpecker.

### Negative

- Needs an admin API token in 1Password.
- Jobs on a laptop that goes quiet rerun on picklelab after about a minute; side effects repeat.
- The VM is arm64 and picklelab is amd64, so floating unlabeled pipelines between them can surface arch-specific failures.
- A manual `no_schedule` on picklelab's agent is overridden on the next tick.
- Field names are from upstream source until checked against the live server.
