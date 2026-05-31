# Philips Hue Integration Design

Date: 2026-03-21

## Goal

Add Philips Hue control to the `lighting/` module, matching the Lutron Caseta CLI pattern. Full control: lights, scenes, groups, sensors, buttons.

## Bridge & Auth

- Hue Bridge at `192.168.1.51` (wired, mDNS: `philips-hue.localdomain`)
- Hue v2 API over HTTPS (self-signed cert on bridge, SSL verify disabled)
- API key obtained via one-time button-press pairing flow
- Credentials stored in 1Password (`picklehome` vault, item "Philips Hue"):
  - `bridge_ip` → `HUE_BRIDGE_IP`
  - `api_key` → `HUE_API_KEY`
- Injected into `.env` via `just dotenv`

## Library

`aiohue`: async, Hue v2 API, full resource coverage. Matches the async pattern used by `pylutron-caseta`.

## Module Structure

```
lighting/
├── __init__.py          # Existing: Lutron bridge connection
├── caseta.py            # Existing: Lutron device commands
├── lutron_cli.py        # Existing: Lutron CLI
├── hue.py               # NEW: Hue bridge connection + device commands
├── hue_cli.py           # NEW: Hue CLI entrypoint
└── .certs/              # Existing: Lutron certs
```

## CLI Commands

```
just hue pair                          # One-time bridge pairing
just hue lights                        # List all lights with state
just hue sensors                       # List motion sensors with status
just hue buttons                       # List tap buttons with last event
just hue scenes                        # List scenes by room
just hue groups                        # List rooms/zones with members
just hue on <light>                    # Turn on (partial name match)
just hue off <light>                   # Turn off
just hue set <light> <brightness>      # Set brightness 0-100%
just hue scene <scene>                 # Activate scene by name (partial match)
just hue status                        # Overview: lights, active scenes, recent motion
```

## Output Format

Room-grouped, aligned columns, compact. Matches Lutron CLI style.

```
Living Room
  Floor Lamp              on   80%  warm white
  Light Strip             on  100%  2700K
  Table Lamp             off

Lights: 3/8 on
Active scenes: Living Room → Relax
Recent motion: Hallway (2m ago)
```

## Secrets

1Password item "Philips Hue" in `picklehome` vault:
- `bridge_ip`: bridge IP address
- `api_key`: API key from pairing

`.env.template` additions:
```
HUE_BRIDGE_IP={{ op://picklehome/Philips Hue/bridge_ip }}
HUE_API_KEY={{ op://picklehome/Philips Hue/api_key }}
```

## Dependencies

- Add `aiohue` to `pyproject.toml`

## Devices

- Bulbs (white / white ambiance / color)
- Light strips
- Motion sensors
- Tap buttons (Hue Tap Dial / Friends of Hue switches)
