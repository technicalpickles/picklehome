# BlueAir Purifier Integration: Design

## Goal

Add read-only BlueAir air purifier management to `climate/`, starting with the Blue Pure 411i Max. Follow the same patterns as the ecobee integration (keychain auth, YAML device registry, CLI with status output).

## Device & API

- **Device:** Blue Pure 411i Max (SKU 110031/110057, `ModelEnum.MAX_411I`)
- **Library:** `blueair-api` (PyPI), async/aiohttp, MIT license
- **API path:** AWS backend (Gigya auth → JWT → AWS API Gateway)
- **Credentials:** username (email) + password + region ("us")
- **No API key option**: Gigya API keys are hardcoded in the library
- **Sensor refresh rate:** 5 minutes (polling faster returns stale data)
- **Library source cloned to:** `~/github.com/technicalpickles/blueair_api/`

## Module Structure

```
climate/
  blueair/
    __init__.py
    auth.py          # keychain storage via keyring (email, password, region)
    client.py        # thin wrapper around blueair-api (discover, refresh)
    devices.py       # purifiers.yaml loader + device registry
    status.py        # format sensor/state data for display
  config/
    purifiers.yaml   # device registry (populated by discover command)
  blueair_cli.py     # click CLI entry point
```

## Auth (`auth.py`)

- Keychain service name: `"picklehome-blueair"`
- Three keys stored: `username`, `password`, `region`
- `get_credentials() -> tuple[str, str, str]`: reads from keychain, raises clear error if not configured
- `store_credentials(username, password, region)`: writes to keychain
- Auth command validates credentials by calling `get_aws_devices()` before storing

## Device Registry (`devices.py`, `config/purifiers.yaml`)

```yaml
purifiers:
  Living Room:
    uuid: "abc123..."
    managed: true
```

- Same pattern as `thermostats.yaml`
- `load_purifiers()` returns only `managed: true` entries
- Discover command populates/updates the file

## CLI Commands (`blueair_cli.py`)

### `climate-blueair auth`
1. Prompt for email, password, region (default "us")
2. Validate via `get_aws_devices()`
3. Store in keychain
4. Print device count as confirmation

### `climate-blueair discover`
1. Read credentials from keychain
2. Call `get_aws_devices()`
3. Print all devices: name, UUID, model, SKU
4. Create `purifiers.yaml` if missing; show diff if exists

### `climate-blueair status`
1. Read credentials + load managed devices
2. For each device: `await device.refresh()`
3. Display sensor + state data (filter out `NotImplemented` fields)
4. `--json` flag for raw JSON output

Output format:
```
Living Room (Blue Pure 411i Max)
  Air Quality: PM2.5 8 ug/m3, VOC 120
  Environment: 72°F, 45% humidity
  Fan: Auto, speed 42%
  Filter: 78% remaining
  LED: off, Child Lock: off
```

## Dependencies

Add to `pyproject.toml`:
```toml
"blueair-api>=1.48",
```

## Justfile Tasks

```
climate-blueair-auth     := uv run python climate/blueair_cli.py auth
climate-blueair-discover := uv run python climate/blueair_cli.py discover
climate-blueair-status   := uv run python climate/blueair_cli.py status
```

## Future (not v1)

- Fan speed/mode profiles in YAML (like comfort modes)
- Schedule sync (auto/night modes by time of day)
- Filter life monitoring with alerts
- Top-level `climate` CLI composing ecobee + blueair subcommands
