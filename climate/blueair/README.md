# BlueAir Purifier Integration

Manages BlueAir air purifiers via the BlueAir cloud API, using the [`blueair-api`](https://github.com/dahlb/blueair_api) Python library.

## Setup

1. **Configure credentials:** add BlueAir email, password, and region to the `BlueAir` item in 1Password, then run `just dotenv`
2. **Discover devices:** `just blueair discover` finds devices, creates `config/purifiers.yaml`
3. **Check status:** `just blueair status`

Credentials are stored in 1Password (vault: `picklehome`, item: `BlueAir`) and injected into `.env` via `just dotenv`.

## Commands

```
just blueair status [--json]                           # all managed devices
just blueair discover                                  # find devices, create purifiers.yaml
just blueair auth                                      # credential setup guidance (1Password + .env)
just blueair set <property> <value>                    # set property on all managed devices
just blueair-set "Device Name" <property> <value>      # set property on one device
```

### Settable properties

| Property | Values | Notes |
|----------|--------|-------|
| `fan-speed` | 0-100 | Continuous range; app shows 3 levels but API accepts any value |
| `auto-mode` | on/off | Auto-adjusts fan speed to air quality |
| `night-mode` | on/off | Quiet operation + dim LED |
| `standby` | on/off | Power on/off |
| `brightness` | 0-100 | LED brightness |
| `child-lock` | on/off | Physical button lock |

## Device registry

`config/purifiers.yaml` maps device names to UUIDs:

```yaml
purifiers:
  Bedroom Purifier:
    uuid: "abc123..."
    managed: true    # included in status and set commands
  Guest Room:
    uuid: "def456..."
    managed: false   # excluded from automation
```

Created by `just blueair discover`. Edit manually to rename devices or change managed status.

## API overview

All communication goes through the BlueAir cloud; there is no local/LAN API. The library wraps two API backends; our devices (Blue Pure 411i Max) use the AWS path.

### Authentication

Three-step flow handled transparently by the library:
1. Gigya login (username + password → session token)
2. JWT exchange (session token → JWT)
3. AWS access token (JWT → access token for API calls)

No API key option exists. Gigya API keys are hardcoded per-region in the library. The library re-authenticates on every session: no tokens to persist or refresh.

### Device discovery

`get_aws_devices()` returns minimal device info (UUID, name, MAC, type). Full details (sensors, state, model) require a separate `device.refresh()` call that hits two additional endpoints.

### Sensor data

- Refreshes every **5 minutes**: polling faster returns stale data
- Historical data available up to **10 hours** via `device_sensors` endpoint

### API limitations

- **No schedules or timers**: automation must be driven externally (cron, launchd)
- **No firmware updates**: version is read-only
- **No device renaming**: name is read-only from the cloud
- **No webhooks or push**: polling only
- **No batch operations**: one device at a time

## Blue Pure 411i Max specifics

**SKU:** 110057

### Sensors

Only **PM2.5**. The following are not available on this model: PM1, PM10, VOC, total VOC, temperature, humidity.

### Fan speed

The phone app shows 3 levels, but the API accepts any integer 0-100. Observed values from the app: 11 (low/night), 87, 91. Whether all 100 values produce meaningfully different airflow is unknown; the motor likely quantizes internally.

### State value types

Fan speed, brightness, and filter percentage return as **floats** from the API (e.g., `77.0`, `11.0`). The CLI coerces these to integers for display.

## Module structure

```
climate/
  blueair/
    auth.py        : env var credential loading (1Password via .env)
    client.py      : async API wrapper, property-to-method mapping
    devices.py     : purifiers.yaml loader, managed device filtering
    status.py      : human-readable output formatting
  blueair_cli.py   : argparse CLI entry point
  config/
    purifiers.yaml : device registry
```
