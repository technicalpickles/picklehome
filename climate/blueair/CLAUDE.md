# CLAUDE.md — climate/blueair/

See @README.md for full API reference, CLI commands, and device specifics.

## Implementation guidance

### Async pattern

All async API work must happen within a **single `asyncio.run()` call**. The aiohttp session is bound to one event loop — multiple `asyncio.run()` calls will fail with "Event loop is closed". In the CLI, each command has an async helper (e.g., `_discover()`, `_status()`) that does all API work including session cleanup.

### NotImplemented sentinel

The `blueair-api` library uses Python's `NotImplemented` singleton (not `None`) for sensors/controls a device doesn't support. Use `_clean_value()` from `client.py` to convert to `None` before exposing data.

### Device refresh requirement

`get_aws_devices()` returns minimal device info. Always call `device.refresh()` before accessing `name`, `sku`, `model`, sensor data, or state — and do it within the same `asyncio.run()` as the discovery call.

### Module responsibilities

- `auth.py` — keychain only, no API calls
- `client.py` — all async API interaction, `SETTABLE_PROPERTIES` mapping, value parsing
- `devices.py` — YAML loading only, no API calls
- `status.py` — formatting only, no API calls
- `blueair_cli.py` — argument parsing + async orchestration, no business logic

### Library source

Local clone at `~/github.com/technicalpickles/blueair_api/` for reference. Key files:
- `src/blueair_api/device_aws.py` — device model, all set_* methods
- `src/blueair_api/http_aws_blueair.py` — API endpoints, auth flow
- `src/blueair_api/model_enum.py` — SKU-to-model mapping
