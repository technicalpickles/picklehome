# Hisense Ductless HVAC (ConnectLife)

Controls the beach house Hisense ductless mini-split heads via the ConnectLife
cloud, using the [`connectlife`](https://github.com/oyvindwe/connectlife) Python
library (reverse-engineered cloud API). Four indoor heads, one per room.

## Setup

1. **Configure credentials:** the ConnectLife app login goes in the `ConnectLife`
   item in 1Password (`picklehome` vault, fields `username` / `password`), then
   run `just dotenv` to inject `CONNECTLIFE_USERNAME` / `CONNECTLIFE_PASSWORD`.
2. **Check status:** `just hisense status`

There is no discovery step or device registry: units are read live from the
account, using the room/nickname ConnectLife already stores.

## Commands

```
just hisense status [name] [--json]        # all heads (optional name/room filter)
just hisense set <name> [flags]            # control matching head(s)
```

`set` flags (any combination): `--power on/off`, `--mode MODE`, `--temp F`,
`--fan SPEED`. `name` is a case-insensitive substring matched against both unit
name and room, so `just hisense set Bedroom --temp 72` targets every head with
"Bedroom" in its name or room.

```
just hisense set "Master Bedroom" --power on --mode cool --temp 71
just hisense set Downstairs --fan high
```

## Device model

All heads are ConnectLife device type `009` (air conditioner), feature `104`
("冷暖节能无功率" = heat + cool, energy-saving, **no power metering**). Verified
against the account; see `docs/research/hisense-connectlife/findings.md`.

### Control properties

| CLI | ConnectLife property | Values |
|-----|----------------------|--------|
| `--power` | `t_power` | `0` off, `1` on |
| `--mode` | `t_work_mode` | `fan_only` 0, `heat` 1, `cool` 2, `dry` 3, `auto` 4 |
| `--temp` | `t_temp` | 61-90 °F (`t_temp_type=1` ⇒ Fahrenheit) |
| `--fan` | `t_fan_speed` | `auto` 0, `low` 5, `middle_low` 6, `medium` 7, `middle_high` 8, `high` 9 |

### Read-only fields

- `f_temp_in` — current room temperature (shown as "current")
- `f_humidity` — raw humidity; values above 100 are a "no reading" sentinel and
  are hidden
- `f_e_*` — fault flags; any nonzero flag surfaces in the status "Faults:" line
- **No energy data.** The `104` feature has no power metering, so `f_electricity`
  and the `air_duct_energy` endpoint are unreliable/empty and are not used.

## API notes

- **Auth:** ConnectLife login flows through SAP/Gigya (`accounts.eu1.gigya.com`)
  → OAuth (`oauth.hijuconn.com`) → the EU gateway (`clife-eu-gateway.hijuconn.com`).
  A US account authenticates through the EU gateway with no region flag.
- **Tokens are not persisted.** The library holds them in memory and re-auths per
  session, so each CLI invocation logs in fresh (no token cache file, like BlueAir).
- **`offlineState` is not an availability signal.** It reads `1` on every head
  regardless of power state, including one verified physically on and reporting live
  (a setpoint change made at the unit synced back through the API). So the CLI keeps
  the raw value in `--json` but never renders "offline". Reads are live: `f_temp_in`
  and setpoints track the physical units on a slow poll cycle.
- **Bidirectional sync works.** Writes (`t_power`, `t_temp`, ...) reach the cloud and
  the unit; changes made at the physical head show up in the next API read.
- **Sandbox:** the library builds its own aiohttp session without `trust_env`, so
  `climate/hisense/auth.py` subclasses `ConnectLifeApi` as `SandboxConnectLifeApi`
  and overrides `_client_session()` to pass `trust_env=True`. The ConnectLife
  hosts are allowlisted in `.claude/settings.local.json`.

## Module structure

```
climate/
  hisense/
    auth.py         : env-var credentials + SandboxConnectLifeApi (trust_env)
    client.py       : async wrapper, HisenseUnit decode, control property builders
    status.py       : human-readable output formatting
  hisense_cli.py    : argparse CLI entry point
```
