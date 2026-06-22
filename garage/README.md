# Garage: Aladdin Connect by Genie

Garage door status and control via the Aladdin Connect smart garage door opener.

## Setup

1. Store your Genie app credentials in 1Password:
   ```bash
   op item create --category=login \
     --title="Aladdin Connect" \
     --vault=picklehome \
     --url="https://app.aladdinconnect.net" \
     "email[text]=YOUR_EMAIL" \
     "password=YOUR_PASSWORD"
   ```
2. Run `just dotenv` to inject credentials into `.env` (the `Aladdin Connect` item's `email`/`password` fields map to `ALADDIN_EMAIL` / `ALADDIN_PASSWORD`, which the CLI reads from the environment; see `.env.template`)
3. Authenticate: `just garage auth`

## Commands

```
just garage auth      # login via AWS Cognito, save tokens, list doors
just garage status    # door state, fault, signal, battery, firmware
just garage open      # open the garage door
just garage close     # close the garage door
```

## Architecture

### Auth

Authenticates via AWS Cognito `USER_PASSWORD_AUTH` flow using credentials reverse-engineered from the Genie iOS app (same approach as the homebridge-aladdin-connect community plugin). Tokens stored at `~/.local/state/picklehome/aladdin-tokens.json` with 0600 permissions.

The Cognito client ID and secret are hardcoded constants. If Genie rotates them, check the [homebridge plugin](https://github.com/homebridge-plugins/homebridge-aladdin-connect) for updated values.

### API

Direct HTTP calls to `api.smartgarage.systems` with Bearer token auth. Two endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/devices` | Fetch all devices and doors |
| POST | `/command/devices/{id}/doors/{index}` | Open/close (`OPEN_DOOR` / `CLOSE_DOOR`) |

### Status codes

**Door status** (numeric in API, mapped to strings):

| Code | Meaning |
|------|---------|
| 0 | unknown |
| 1 | open |
| 2 | opening |
| 3 | timeout_opening (failed to open, still closed) |
| 4 | closed |
| 5 | closing |
| 6 | timeout_closing (failed to close, still open) |
| 7 | not_configured |

**Fault codes:**

| Code | Meaning |
|------|---------|
| 0 | none |
| 1 | ul_lockout (safety lockout) |
| 2 | interlock |
| 3 | not_safe |
| 4 | will_not_move |

**Link status** (door sensor connection):

| Code | Meaning |
|------|---------|
| 0 | unknown |
| 1 | not_configured |
| 2 | paired |
| 3 | connected |

### Device identification

The API device ID is the WiFi MAC address (e.g. `F0AD4E17085C` = `F0:AD:4E:17:08:5C`). The OUI is Globalscale Technologies, which manufactures the embedded WiFi module. This MAC can be used to find the device in UniFi client lists.

## Module structure

```
garage/
  garage_cli.py          # CLI entry point (argparse)
  aladdin/
    auth.py              # Cognito auth, token storage, credential loading
    client.py            # HTTP client, door dataclass, status mappings
```
