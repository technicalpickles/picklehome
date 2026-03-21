# CLAUDE.md — climate/blueair/

## BlueAir API overview

All communication goes through the BlueAir cloud — there is no local API. The library (`blueair-api` on PyPI, source cloned to `~/github.com/technicalpickles/blueair_api/`) wraps two API backends; our devices use the AWS path.

### Authentication (AWS path)

Three-step flow, all handled by the library:
1. **Gigya login** — username + password → session token (Gigya API keys are hardcoded per-region in the library, not user-supplied)
2. **JWT exchange** — session token → JWT
3. **AWS access token** — JWT → access token used for all subsequent calls

Credentials: email + password + region (`us`, `eu`, `cn`, `au`). No API key option exists. We store these in macOS Keychain under service `picklehome-blueair`.

The library re-authenticates on every session (no persistent tokens to manage). Each CLI invocation does 3 HTTP round-trips before any real work.

### Device discovery

`get_aws_devices()` returns devices with only `uuid`, `name_api`, `mac`, and `type_name`. All other fields (`name`, `sku`, `model`, sensors, state) require calling `device.refresh()` which hits two additional endpoints.

### Sensor data

- Updates every **5 minutes** — polling faster returns stale data
- Historical data available up to **10 hours** (configurable via `duration` param on `device_sensors`)
- The library uses `NotImplemented` (not `None`) for sensors a device doesn't support

### Async / event loop

The library is fully async (aiohttp). All API work must happen within a **single `asyncio.run()` call** — the aiohttp session is bound to one event loop. Multiple `asyncio.run()` calls will fail with "Event loop is closed".

## Blue Pure 411i Max specifics (SKU 110057)

### Available sensors

Only **PM2.5**. The following are `NotImplemented` on this model:
- PM1, PM10, VOC, total VOC, temperature, humidity

### Available controls

| Property | API method | Value type | Range |
|----------|-----------|------------|-------|
| Fan speed | `set_fan_speed` | int | 0-100 (continuous, not 3 levels) |
| Auto mode | `set_fan_auto_mode` | bool | on/off |
| Night mode | `set_night_mode` | bool | on/off |
| Standby | `set_standby` | bool | on/off (power) |
| LED brightness | `set_brightness` | int | 0-100 |
| Child lock | `set_child_lock` | bool | on/off |

The phone app shows only 3 fan speed levels, but the API accepts any value 0-100. Our observed values from the app: 11 (low/night), 87, 91.

### State values come back as floats

Fan speed, brightness, and filter percentage all return as floats (e.g., `77.0`, `11.0`). The status formatter coerces these to int for display.

### What the API does NOT support

- **No schedules or timers** — any automation must be driven externally (cron, launchd)
- **No firmware updates** — version is read-only
- **No device renaming** — name is read-only
- **No webhooks or push notifications** — polling only
- **No local/LAN API** — cloud only
- **No batch operations** — one device at a time

## CLI commands

```
just blueair status [--json]                           # all managed devices
just blueair discover                                   # find devices, create purifiers.yaml
just blueair auth                                       # store credentials in Keychain
just blueair set <property> <value>                     # all managed devices
just blueair-set "Device Name" <property> <value>       # specific device (handles quoting)
```

## Module structure

- `auth.py` — keychain credential storage (no token management needed)
- `client.py` — async API wrapper, property-to-method mapping
- `devices.py` — purifiers.yaml loader, managed device filtering
- `status.py` — human-readable output formatting
- `../blueair_cli.py` — argparse CLI entry point
- `../config/purifiers.yaml` — device registry (name → UUID, managed flag)
