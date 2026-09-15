# picklehome

Personal home automation and infrastructure tooling, built by vibe coding with AI rather than running a local server.

## The Story

I ran Home Assistant for quite a while, loved it, and even contributed to it. At some point I moved, never got the local server re-established, and by the time I came back to it, Home Assistant had shifted from YAML-based config to a UI-driven model. Nothing wrong with that (it's genuinely better for most people) but I'd never finished the transition and the gap just grew.

So instead of picking up where I left off, I'm taking a different approach: writing small, concrete scripts for specific things I actually want to automate or monitor, and exploring what it feels like to build home tooling agentically, with AI doing a lot of the heavy lifting while I direct what gets built.

No dashboard. Just Python scripts, a task runner, 1Password for secrets, and one NUC in the closet for the handful of things that need to stay up. If a script does something useful, it earns its place.

## What's Here

Every integration is a module with its own README and a `just` wrapper. The table is the index; the sections after it are the tour.

| Integration | Module | Hardware | Protocol | Commands |
|-------------|--------|----------|----------|----------|
| Ecobee | [`climate/ecobee/`](climate/README.md) | Thermostats + room sensors | Cloud API (OAuth) | `just climate-*` |
| Ambient Weather | [`climate/ambient/`](climate/README.md) | Outdoor weather station | Cloud API (API key) | `just climate-weather` |
| BlueAir | [`climate/blueair/`](climate/blueair/README.md) | Air purifiers | Cloud API (user/pass) | `just blueair *` |
| Hisense (ConnectLife) | [`climate/hisense/`](climate/hisense/README.md) | Ductless mini-split HVAC (beach house) | Cloud API (user/pass) | `just hisense *` |
| Google Air Quality | [`climate/outdoor_air/`](climate/README.md) | N/A (API-only) | REST API (API key) | `just climate-air-quality` |
| Lutron Caseta | [`lighting/`](lighting/README.md) | Dimmers, switches, fans | Local TLS (certs) | `just lutron *` |
| Philips Hue | [`lighting/`](lighting/README.md) | Lights, motion sensors, buttons | Local API V2 (app key) | `just hue *` |
| UniFi | [`network/unifi/`](network/README.md) | APs, switches, USG, CloudKey | Local API (API key) | `just unifi *` |
| AT&T BGW | [`network/`](network/README.md) | Fiber gateway | Web scraping (no auth) | `just bgw *` |
| Aladdin Connect | [`garage/`](garage/README.md) | Garage door opener | Cloud API (Cognito) | `just garage *` |
| Yale Access | [`locks/`](locks/README.md) | Smart locks + bridges | Cloud API (user/pass) | `just locks *` |
| Nest | [`nest/`](nest/README.md) | Thermostats + cameras (SDM) | Cloud API (OAuth) | `just nest *` |
| Sonos | [`sonos/`](sonos/README.md) | Speakers | Local UPnP (no auth) | `just sonos *` |
| VicoHome (Harymor) | [`birdfeeder/`](birdfeeder/README.md) | Bird feeder/camera | Cloud API (user/pass, unofficial) | `just birdfeeder *` |
| LG ThinQ | [`lg/`](lg/README.md) | Washer, dryer, refrigerator | Cloud API (static PAT), read-only | `just lg *` |
| Moen Flo | [`water/`](water/README.md) | Smart water shutoff valve | Cloud API (user/pass), read-only | `just water *` |

### `climate/`: HVAC automation

Syncs thermostat schedules and comfort setpoints to Ecobee via their API. Configuration lives in YAML (`schedule.yaml`, `comforts.yaml`) and gets pushed up rather than managed through the app.

The source of truth is [`climate/spec/hvac-spec.md`](climate/spec/hvac-spec.md), a human-readable document describing the intended HVAC behavior for the home. The workflow: talk through what you want with the agent, let it capture that into the spec, then have it transcribe the spec into the YAML files and push them up.

Comfort mode (heat vs. cool) is driven by outdoor temperature, read from nearby [Ambient Weather Network](https://ambientweather.net) stations. A 15-minute timer on the NUC (`climate-auto-switch`, below) does the seasonal switching unattended.

There's also a BlueAir air purifier integration, the Hisense mini-splits at the beach house, and an outdoor air-quality + pollen check (Google's APIs), for the days when going outside is a mistake.

```bash
just climate-sync               # push schedule.yaml to Ecobee
just climate-validate           # verify live schedule matches schedule.yaml
just climate-comforts-sync      # push comfort setpoint temps
just climate-status             # show current thermostat state
just climate-history            # room-sensor temperature + occupancy history
just climate-weather            # show current outdoor temp + comfort recommendation
just climate-comfort-switch auto  # auto-switch comfort mode based on outdoor temp
just climate-air-quality        # outdoor AQI + pollen forecast
```

### `network/`: Network diagnostics

Scripts for understanding what's happening on the network: ISP status, WiFi signal quality, UniFi AP stats, connectivity diagnostics. Useful when things feel slow or flaky. The house floor plan (MagicPlan export turned into GeoJSON with AP and wall-material markup) also lives here, though the generated files sync to the vault rather than git.

```bash
just network-status        # ISP + CDN health check
just wifi-diag             # client-side WiFi + connectivity diagnostic
just unifi clients         # UniFi clients, devices, WiFi, gateway diagnostics
```

### `lighting/`: Lights and switches

Lutron Caseta dimmers, switches, and fans over the local bridge (TLS client certs, no cloud), plus Philips Hue lights, motion sensors, and tap buttons. Both talk to their bridges directly on the LAN, so control keeps working even when the internet doesn't.

```bash
just lutron status                 # what's on, at a glance
just lutron set <device> <0-100>   # dim a light or set a fan speed
just hue lights                    # all Hue lights, grouped by room
just hue scene <name>              # activate a scene
```

### `garage/`: Garage door

Status and control for the Genie Aladdin Connect opener. Mostly here so I can answer "did I leave the garage open?" without walking downstairs.

```bash
just garage status         # open/closed, plus fault and signal
just garage open
just garage close
```

### `locks/`: Smart locks

Yale Access / August locks and their bridges, read through the August cloud, reporting status across every home on the account. The findings in [`locks/README.md`](locks/README.md) are worth a read before you trust the status: "bridge offline" usually means a dead lock battery rather than a dead bridge, and that one took a while to untangle.

```bash
just locks status          # one line per lock, grouped by home
just locks status <name>   # detail for one lock
```

### `nest/`: Nest thermostats and cameras

Google's Smart Device Management API, for the Nest gear that isn't Ecobee. Read-only status today, grouped by location using the same registry climate and locks use.

```bash
just nest status           # every Nest device, grouped by home
```

### `sonos/`: Speakers

Checks that the Sonos speakers are actually online and not sitting there muted. No cloud and no login: it finds them on the local network the same way Home Assistant does, using the `soco` library that HA itself runs under the hood. It keeps an expected list of speakers so a missing one shows up as offline instead of just dropping off the list, which is how I found out the speaker in Alex's room had been unplugged.

```bash
just sonos status   # online/offline and muted state for every speaker
just sonos list     # raw list of whatever's currently on the network
just sonos roster   # print the online speakers as roster YAML
```

### `birdfeeder/`: Bird feeder camera

The Harymor feeder reports through VicoHome's (unofficial) API. Camera state, plus a log of which birds showed up and when.

```bash
just birdfeeder status     # battery, signal, charging
just birdfeeder events     # recent detections, with species
just birdfeeder species    # species tally over the last N days
```

### `lg/`: Laundry and fridge

LG ThinQ, read-only. Washer and dryer cycle state, fridge setpoints, and a local observation log so "did the dryer finish?" has an answer even when the app is being weird.

```bash
just lg status
just lg laundry
just lg fridge
```

### `water/`: Water shutoff

Moen Flo smart valve, read-only. Valve state, pressure, flow, and any pending alerts.

```bash
just water status
```

### `homelab/`: Always-on services

A single Intel NUC (`picklelab`) running the stuff that needs to stay up: two always-on Claude Code sessions, Obsidian sync, a Taskwarrior sync server, self-hosted CI, the OpenClaw chat gateway, nightly restic backups, and the climate timer. Docker Compose per service, systemd to keep them running, Tailscale for access, 1Password service-account tokens on the host for secrets, all reproducible from this repo. See [`homelab/README.md`](homelab/README.md) for the service list and [`homelab/services/README.md`](homelab/services/README.md) for the deployment pattern and per-service registry.

## Setup

**Prerequisites:** [uv](https://github.com/astral-sh/uv), [just](https://github.com/casey/just), and [mise](https://mise.jdx.dev) (pins the Python/uv/go versions via `.mise.toml`; run `mise trust` after cloning)

**Quick install** (if you don't have them yet):
```bash
# Install mise (version manager), then just + uv
curl --proto '=https' --tlsv1.2 -sSf https://mise.run | sh
mise trust  # trust this repo's .mise.toml
mise install

# Or install just standalone (if you don't use mise):
curl --proto '=https' --tlsv1.2 -sSf https://just.systems/install.sh | bash -s -- --to ~/.local/bin
```

```bash
just install   # install Python deps
just dotenv    # pull secrets from 1Password into .env (local dev only)
```

For a guided first-time walkthrough of the climate tools, see [`docs/climate-setup.md`](docs/climate-setup.md).

## Secrets

Everything lives in 1Password (the `picklehome` vault, mostly). There are two ways it gets to code, and they don't overlap:

- **Local dev on the Mac:** `just dotenv` runs `op inject` over `.env.template` to produce a gitignored `.env`, which scripts load via `python-dotenv` (and `just` loads via `set dotenv-load`).
- **Deployed services on picklelab:** no `.env` at all. Each service's systemd unit wraps `docker compose` in `op run` against a read-only service-account token on the host, so secrets resolve at container start and never touch disk. `just dotenv` isn't part of that path.

`CLAUDE.md` has the step-by-step for adding a secret and the gotchas; `homelab/services/README.md` has the deploy side.

### Auth patterns

Every integration follows the same shape: credentials in 1Password, into `.env`, loaded by `python-dotenv` at import time. What differs is what happens after the first login.

| Style | Used by | Token storage | Notes |
|-------|---------|---------------|-------|
| API key (static) | UniFi, Cloudflare Radar, Google APIs, LG ThinQ | `.env` only | No refresh needed |
| OAuth token (refreshable) | Ecobee | `~/.local/state/picklehome/ecobee-tokens.json` | PIN flow, auto-refresh on use |
| OAuth token (refreshable) | Nest | `~/.local/state/picklehome/nest-tokens.json` | Loopback browser flow via Device Access "partner connections"; auto-refresh on use |
| Username/password to session token | Yale, Aladdin, BlueAir | `~/.local/state/picklehome/<service>-tokens.json` | Token cached, re-auth on expiry |
| Username/password (no persistence) | Hisense/ConnectLife, VicoHome, Moen Flo | none (in-memory only) | Re-auths per session; no token file |
| TLS client cert | Lutron Caseta | `lighting/.certs/` (key, cert, CA) | One-time pairing, certs don't expire |

Token files go in `~/.local/state/picklehome/<service>-tokens.json` with 0600 permissions. Most modules also honor a `<SERVICE>_TOKEN_PATH` env var override (used by tests).

## Testing

Tests live in `tests/`, mirroring the source layout (`tests/climate/ecobee/`, `tests/garage/aladdin/`, and so on).

```bash
uv run pytest                              # all tests
uv run pytest tests/climate/ -v            # one module
uv run pytest tests/test_comfort_switch.py -v  # one file
```

How they're written:

- `pytest` with `unittest.mock` (patch, MagicMock). No pytest plugins beyond core.
- No conftest.py: fixtures are per-file, close to the tests that use them.
- API responses are mocked at the client boundary (patch the HTTP call or library method, not internal functions).
- Pure logic tests (config parsing, mode switching) don't need mocking.
- No integration tests that hit real APIs. All tests run offline.
- `tests/test_no_sensitive_identifiers.py` scans tracked files for full MAC addresses, so fixtures use locally-administered ones (`02:...`, `AA:BB:CC:...`).

## Repo layout

- `climate/`: HVAC/climate automation; see `climate/README.md`
  - `climate/ecobee/`: Ecobee thermostat API (auth, schedule, comforts, status, history)
  - `climate/blueair/`: BlueAir air purifier API; see `climate/blueair/README.md`
  - `climate/hisense/`: Hisense ductless HVAC via ConnectLife (beach house); see `climate/hisense/README.md`
  - `climate/ambient/`: Ambient Weather outdoor temp
  - `climate/outdoor_air/`: Google Air Quality + Pollen APIs (AQI, pollutants, pollen UPI)
  - `climate/config/`: YAML config (thermostats, schedule, comforts, weather, purifiers)
  - `climate/spec/`: source of truth for thermostat behavior (hvac-spec.md)
  - `climate/floorplan/`: HVAC floor-plan GeoJSON (gitignored, synced to the vault)
- `lighting/`: Lutron Caseta + Philips Hue control; see `lighting/README.md`
- `network/`: Network diagnostic and profiling scripts, `TOPOLOGY.md`, `investigations/`, and the floor-plan pipeline (`floorplan_dxf_to_geojson.py`, output in gitignored `network/floorplan/`); see `network/README.md`
- `garage/`: Aladdin Connect garage door control; see `garage/README.md`
- `locks/`: Yale Access smart locks; see `locks/README.md`
- `nest/`: Nest thermostats + cameras via Google SDM; see `nest/README.md`
- `sonos/`: Sonos speaker health checks (local, no auth); see `sonos/README.md`
- `birdfeeder/`: VicoHome (Harymor) bird feeder/camera state + bird detection log; see `birdfeeder/README.md`
- `lg/`: LG ThinQ appliances (washer, dryer, refrigerator), read-only; see `lg/README.md`
- `water/`: Moen Flo smart water shutoff (read-only); see `water/README.md`
- `picklehome/`: Shared cross-module code. `locations.py` is the canonical location registry (main house, beach house, ...) consumed by climate, locks, and nest; locations come from 1Password items tagged `picklehome-location`
- `homelab/`: NUC server services and infrastructure; see `homelab/README.md`
  - `homelab/services/<name>/`: one directory per deployed service (systemd unit, `deploy.sh`, compose overrides); registry in `homelab/services/README.md`
  - `homelab/config/`: host-side config applied by deploy scripts (the passwordless-sudo allowlist `sudoers-deploy-ops`, among others)
  - `homelab/scripts/`: host setup helpers (`setup-deploy-access.sh`)
  - `homelab/docs/`: host setup, operations runbook, agent access model
  - `homelab/seapickle/`: beach house Raspberry Pi 3B+ (Tailscale jump box, subnet router, connectivity probes); see `homelab/seapickle/README.md`
- `docs/`: `CONVENTIONS.md` (where information belongs), `plans/` (point-in-time design docs + implementation plans), `superpowers/plans/` (plans written by the superpowers planning skills, same rules), `research/` (deep-dive findings), `climate-setup.md`
- `tests/`: pytest tests, mirroring source layout
- `scripts/`: shared utilities: `dotenv` (builds `.env`), `service-env` (filters `.env.template` per service for `op run`), `quote-env-values`, `locations-filter.jq` (1Password items to the locations registry), `secret_entry.py` (`just secret-entry`, the escape hatch when 1Password is unreachable)
- `.parkinglot/`: gitignored session handoffs for the agent's park/unpark workflow

## Network Topology

```
Client → USG (192.168.1.1) → AT&T BGW (192.168.8.254) → AT&T Fiber → Internet
```

- **LAN:** `192.168.1.x`, gateway USG at `192.168.1.1`
- **AT&T BGW (fiber gateway):** `192.168.8.254`, admin UI at `http://192.168.8.254`
- **ISP:** AT&T Fiber, AS7018, southeastern US (Atlanta area)
- **Double-NAT:** BGW is NOT in IP passthrough mode; USG gets a private WAN IP

The full device inventory, AP placement, and room layout are in [`network/TOPOLOGY.md`](network/TOPOLOGY.md).
