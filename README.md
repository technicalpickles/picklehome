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

There's also a BlueAir air purifier integration and an outdoor air-quality + pollen check (Google's APIs), for the days when going outside is a mistake.

```bash
just climate-sync               # push schedule.yaml to Ecobee
just climate-validate           # verify live schedule matches schedule.yaml
just climate-comforts-sync      # push comfort setpoint temps
just climate-status             # show current thermostat state
just climate-weather            # show current outdoor temp + comfort recommendation
just climate-comfort-switch auto  # auto-switch comfort mode based on outdoor temp
just climate-air-quality        # outdoor AQI + pollen forecast
```

### `network/` — Network diagnostics

Scripts for understanding what's happening on the network — ISP status, WiFi signal quality, UniFi AP stats, connectivity diagnostics. Useful when things feel slow or flaky.

```bash
just network-status        # ISP + CDN health check
just wifi-diag             # client-side WiFi + connectivity diagnostic
just unifi clients         # UniFi clients, devices, WiFi, gateway diagnostics
```

### `lighting/` — Lights and switches

Lutron Caseta dimmers, switches, and fans over the local bridge (TLS client certs, no cloud), plus Philips Hue lights, motion sensors, and tap buttons. Both talk to their bridges directly on the LAN, so control keeps working even when the internet doesn't.

```bash
just lutron status                 # what's on, at a glance
just lutron set <device> <0-100>   # dim a light or set a fan speed
just hue lights                    # all Hue lights, grouped by room
just hue scene <name>              # activate a scene
```

### `garage/` — Garage door

Status and control for the Genie Aladdin Connect opener. Mostly here so I can answer "did I leave the garage open?" without walking downstairs.

```bash
just garage status         # open/closed, plus fault and signal
just garage open
just garage close
```

### `locks/` — Smart locks

Yale Access / August locks and their bridges, read through the August cloud, reporting status across every home on the account. The findings in [`locks/README.md`](locks/README.md) are worth a read before you trust the status: "bridge offline" usually means a dead lock battery rather than a dead bridge, and that one took a while to untangle.

```bash
just locks status          # one line per lock, grouped by home
just locks status <name>   # detail for one lock
```

### `homelab/` — Always-on services

A single Intel NUC running the stuff that needs to stay up: a self-hosted task manager, nightly restic backups, Obsidian sync, and a couple of small APIs. Docker Compose per service, systemd to keep them running, Tailscale for access, all reproducible from this repo. See [`homelab/README.md`](homelab/README.md) for the service registry and host setup.

## Setup

**Prerequisites:** [uv](https://github.com/astral-sh/uv), [just](https://github.com/casey/just), and [mise](https://mise.jdx.dev) (pins the Python/uv/go versions via `.mise.toml`; run `mise trust` after cloning)

```bash
just install   # install Python deps
just dotenv    # pull secrets from 1Password into .env
```

For a guided first-time walkthrough of the climate tools, see [`docs/climate-setup.md`](docs/climate-setup.md).

Secrets live in 1Password (picklehome vault) and are injected via `op inject`. See `CLAUDE.md` for details on adding new secrets.

## Network Topology

See [`network/TOPOLOGY.md`](network/TOPOLOGY.md).
