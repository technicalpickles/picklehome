# picklehome

Personal home automation and infrastructure tooling — built by vibe coding with AI rather than running a local server.

## The Story

I ran Home Assistant for quite a while, loved it, and even contributed to it. At some point I moved, never got the local server re-established, and by the time I came back to it, Home Assistant had shifted from YAML-based config to a UI-driven model. Nothing wrong with that — it's genuinely better for most people — but I'd never finished the transition and the gap just grew.

So instead of picking up where I left off, I'm taking a different approach: writing small, concrete scripts for specific things I actually want to automate or monitor, and exploring what it feels like to build home tooling agentically — with AI doing a lot of the heavy lifting while I direct what gets built.

No persistent server. No dashboard. Just Python scripts, a task runner, and 1Password for secrets. If a script does something useful, it earns its place.

## What's Here

### `climate/` — HVAC automation

Syncs thermostat schedules and comfort setpoints to Ecobee via their API. Configuration lives in YAML (`schedule.yaml`, `comforts.yaml`) and gets pushed up rather than managed through the app.

The source of truth is [`climate/spec/hvac-spec.md`](climate/spec/hvac-spec.md) — a human-readable document describing the intended HVAC behavior for the home. The workflow: talk through what you want with the agent, let it capture that into the spec, then have it transcribe the spec into the YAML files and push them up.

Comfort mode (heat vs. cool) is driven by outdoor temperature, read from nearby [Ambient Weather Network](https://ambientweather.net) stations. The schedule automatically switches between Comfort Heat and Comfort Cool based on a configurable threshold band.

```bash
just climate-sync               # push schedule.yaml to Ecobee
just climate-validate           # verify live schedule matches schedule.yaml
just climate-comforts-sync      # push comfort setpoint temps
just climate-status             # show current thermostat state
just climate-weather            # show current outdoor temp + comfort recommendation
just climate-comfort-switch auto  # auto-switch comfort mode based on outdoor temp
```

### `network/` — Network diagnostics

Scripts for understanding what's happening on the network — ISP status, WiFi signal quality, UniFi AP stats, connectivity diagnostics. Useful when things feel slow or flaky.

```bash
just network-status        # ISP + CDN health check
just wifi-diag             # client-side WiFi + connectivity diagnostic
just unifi-wifi            # UniFi AP radio stats and per-client signal
```

## Setup

**Prerequisites:** [uv](https://github.com/astral-sh/uv) and [just](https://github.com/casey/just)

```bash
just install   # install Python deps
just dotenv    # pull secrets from 1Password into .env
```

Secrets live in 1Password (picklehome vault) and are injected via `op inject`. See `CLAUDE.md` for details on adding new secrets.

## Network Topology

See [`network/TOPOLOGY.md`](network/TOPOLOGY.md).
