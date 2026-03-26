# Climate — HVAC & Air Quality Automation

Manages home climate systems: Ecobee thermostats, Ambient Weather outdoor sensors, and BlueAir air purifiers.

## Setup

### Ecobee thermostats

1. Get an API key from the [Ecobee Developer Portal](https://www.ecobee.com/developers/)
2. Store it: `keyring set picklehome-ecobee api_key`
3. Authorize: `just climate-auth` — follows the Ecobee PIN flow
4. Thermostats are registered in `config/thermostats.yaml`

### Ambient Weather

Station MACs are sensitive (geolocatable) — stored in 1Password, injected via `.env`. See `.env.template` for the `AMBIENT_STATION_MACS` variable.

### BlueAir purifiers

See [blueair/README.md](blueair/README.md).

## Commands

### Ecobee

```
just climate-auth                        # PIN auth flow + thermostat discovery
just climate-list                        # list thermostats and climate refs
just climate-status [--json]             # live thermostat state
just climate-sync [--dry-run]            # push schedule.yaml to Ecobee
just climate-validate                    # confirm remote matches local
just climate-comforts-capture            # snapshot current setpoints → comforts.yaml
just climate-comforts-sync [--dry-run]   # push comforts.yaml to Ecobee
just climate-comfort-switch heat|cool|auto [--dry-run] [--clear-holds]  # seasonal mode switch
```

### Weather

```
just climate-weather                     # outdoor temp + comfort mode recommendation
just climate-weather-discover            # find nearby Ambient Weather stations
```

### BlueAir

```
just blueair status [--json]             # purifier sensor data + state
just blueair set <property> <value>      # control all managed purifiers
just blueair-set "Name" <prop> <val>     # control one purifier
just blueair discover                    # find devices, create purifiers.yaml
just blueair auth                        # store credentials in Keychain
```

## Configuration files

All in `config/`:

| File | Purpose |
|------|---------|
| `thermostats.yaml` | Ecobee thermostat registry (name → ID, managed flag) |
| `schedule.yaml` | Weekly schedule (time slots → climate refs) |
| `comforts.yaml` | Temperature setpoints per comfort mode per thermostat |
| `weather.yaml` | Outdoor temp thresholds for seasonal comfort switching |
| `purifiers.yaml` | BlueAir device registry (name → UUID, managed flag) |

## Architecture

### Ecobee API

- **Library:** `python-ecobee-api` (PyPI: `python-ecobee-api`)
- **Auth:** OAuth PIN flow → access + refresh tokens, stored in macOS Keychain (`picklehome-ecobee`)
- **Token refresh:** The `KeychainEcobee` subclass overrides `_write_config()` to persist refreshed tokens back to Keychain automatically
- **Schedule model:** Ecobee thermostats store a weekly program with time slots referencing "climates" (named comfort modes). We define ours in YAML and push them via the API.
- **Comfort modes:** Each thermostat has named climates (Home, Away, Sleep, plus custom smart1/smart2). smart1 and smart2 are swappable for seasonal switching — Comfort Heat targets 70°F from below, Comfort Cool from above.

### Ambient Weather API

- **Library:** `aioambient` (async)
- **Data:** Outdoor temperature, humidity from personal weather stations
- **Used for:** Automated comfort mode switching based on outdoor temp thresholds

### BlueAir API

See [blueair/README.md](blueair/README.md) for full API details.

## Spec-first workflow

`spec/hvac-spec.md` is the source of truth for all thermostat behavior. The workflow:

1. Read the spec to understand intent
2. If desired behavior is changing, update the spec first
3. Derive YAML config changes from the spec
4. Validate with `just climate-validate`

Never change `schedule.yaml` or `comforts.yaml` without the spec as reference.

## Key design principle

The goal is always ~70°F in any actively occupied space. Comfort Heat and Comfort Cool both target 70°F from opposite thermal directions. Season determines which is active; outdoor temperature thresholds trigger the switch.

## Module structure

```
climate/
  sync.py                  # Ecobee CLI entry point (argparse)
  blueair_cli.py           # BlueAir CLI entry point (argparse)
  ecobee/
    auth.py                # Keychain-based OAuth (PIN flow, token refresh)
    schedule.py            # Schedule YAML loading, validation, sync
    comforts.py            # Comfort mode setpoint management
    status.py              # Live thermostat status extraction + formatting
    thermostats.py         # Thermostat registry loader
  ambient/
    client.py              # Outdoor temp fetching via Ambient Weather API
  blueair/
    auth.py                # Keychain credential storage
    client.py              # Async API wrapper, device control
    devices.py             # Purifier registry loader
    status.py              # Purifier status formatting
  config/                  # YAML configuration (see table above)
  spec/
    hvac-spec.md           # Source of truth for thermostat behavior
```
