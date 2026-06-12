# Climate: HVAC & Air Quality Automation

Manages home climate systems: Ecobee thermostats, Ambient Weather outdoor sensors, BlueAir air purifiers, and outdoor air quality (Google Air Quality + Pollen).

## Setup

> New to this? [`docs/climate-setup.md`](../docs/climate-setup.md) is a step-by-step first-time
> walkthrough (developer app registration, PIN auth, editing the schedule, troubleshooting).

### Ecobee thermostats

1. Get an API key from the [Ecobee Developer Portal](https://www.ecobee.com/developers/)
2. Store it in 1Password: `op item edit Ecobee --vault=picklehome api_key=<your-key>`
3. Run `just dotenv` to inject it into `.env`
4. Authorize: `just climate-auth` (follows the Ecobee PIN flow, saves tokens to `~/.local/state/picklehome/ecobee-tokens.json`)
5. Thermostats are registered in `config/thermostats.yaml`

### Room sensors (SmartSensor)

Ecobee SmartSensors (the wireless room pucks) only pair through the **mobile app**, not the thermostat screen. The on-device Settings → Sensors menu has no "add" option, so don't waste time looking for one there. In the app, open the thermostat, go to Sensors, and scan the QR code printed under the sensor's battery cover.

If nothing gets detected, force the sensor into pairing mode: pull the battery, wait two full minutes, then reinsert it right next to the thermostat. If that still does nothing, seat the battery upside down (positive side down) for 30 seconds, then flip it back the right way, which forces it to re-advertise. A months-old coin cell is the usual culprit, so try a fresh CR-2032 before assuming the sensor is dead.

Pairing alone doesn't change any temperatures. See the Ecobee API notes below for how sensor participation actually drives behavior.

### Ambient Weather

Station MACs are sensitive (geolocatable), stored in 1Password, injected via `.env`. See `.env.template` for the `AMBIENT_STATION_MACS` variable.

### BlueAir purifiers

See [blueair/README.md](blueair/README.md).

### Outdoor air quality

Uses the Google Air Quality and Pollen APIs.

1. Enable the Air Quality API and Pollen API in the [Google Cloud console](https://console.cloud.google.com)
2. Store the key in 1Password (`Google Air Quality API` item, `api_key` field) and run `just dotenv`; it lands in `.env` as `GOOGLE_POLLEN_API_KEY` (one key covers both APIs)
3. The lookup uses your home coordinates from `HOME_LAT` / `HOME_LON` (also in `.env`, sourced from the `Home` 1Password item)

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

### Air quality

```
just climate-air-quality                 # current AQI, dominant pollutant, health rec + pollen forecast
```

### BlueAir

```
just blueair status [--json]             # purifier sensor data + state
just blueair set <property> <value>      # control all managed purifiers
just blueair-set "Name" <prop> <val>     # control one purifier
just blueair discover                    # find devices, create purifiers.yaml
just blueair auth                        # credential setup guidance
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
- **Auth:** OAuth PIN flow → access + refresh tokens, stored in `~/.local/state/picklehome/ecobee-tokens.json`. API key from `ECOBEE_API_KEY` env var (1Password via `.env`)
- **Token refresh:** The `FileTokenEcobee` subclass overrides `_write_config()` to persist refreshed tokens back to the JSON file automatically
- **Schedule model:** Ecobee thermostats store a weekly program with time slots referencing "climates" (named comfort modes). We define ours in YAML and push them via the API.
- **Comfort modes:** Each thermostat has named climates (Home, Away, Sleep, plus custom smart1/smart2). smart1 and smart2 are swappable for seasonal switching: Comfort Heat targets 70°F from below, Comfort Cool from above.
- **Room sensors:** A SmartSensor pairs to one thermostat and reports temperature and occupancy, but a paired sensor does nothing until it's enrolled in specific comfort settings. Enrollment is per-climate and set in the app, and the pairing wizard only offers Home/Away/Sleep, so custom climates like Comfort Cool (smart1) and Comfort Heat (smart2) have to be enabled separately or the sensor sits idle during the modes the schedule actually runs. When a sensor participates, the thermostat targets the **average** of all participating sensors, so adding a sensor that reads warmer than the thermostat makes the system cool more (and heat more), not less. `climate-status` requests sensor data (`includeSensors`) but the code does not parse it yet; inspect sensors through the API directly until it does.

### Ambient Weather API

- **Library:** `aioambient` (async)
- **Data:** Outdoor temperature, humidity from personal weather stations
- **Used for:** Automated comfort mode switching based on outdoor temp thresholds

### BlueAir API

See [blueair/README.md](blueair/README.md) for full API details.

### Outdoor air quality (Google)

- **APIs:** Google Air Quality (`airquality.googleapis.com`) + Pollen (`pollen.googleapis.com`)
- **Auth:** single API key (`GOOGLE_POLLEN_API_KEY`); location from `HOME_LAT` / `HOME_LON`
- **Data:** current AQI, dominant pollutant + concentrations, general-population health recommendation, and pollen UPI (Universal Pollen Index) forecast by type
- **HTTP client:** `aiohttp` with `trust_env=True` so it respects the sandbox proxy (see root CLAUDE.md). Air quality and pollen are fetched concurrently; a missing or unset pollen key degrades gracefully (air quality still returns, pollen is skipped with a warning).

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
    auth.py                # File-based OAuth (PIN flow, token refresh)
    schedule.py            # Schedule YAML loading, validation, sync
    comforts.py            # Comfort mode setpoint management
    status.py              # Live thermostat status extraction + formatting
    thermostats.py         # Thermostat registry loader
  ambient/
    client.py              # Outdoor temp fetching via Ambient Weather API
  blueair/
    auth.py                # Env var credential loading (1Password via .env)
    client.py              # Async API wrapper, device control
    devices.py             # Purifier registry loader
    status.py              # Purifier status formatting
  outdoor_air/
    client.py              # Google Air Quality API (AQI, pollutants, health rec)
    pollen.py              # Google Pollen API (UPI forecast by type)
  config/                  # YAML configuration (see table above)
  spec/
    hvac-spec.md           # Source of truth for thermostat behavior
```
