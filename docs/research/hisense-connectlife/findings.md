# Hisense ductless HVAC integration via ConnectLife

Research into integration points for the beach house Hisense ductless mini-split, to get a
unified beach house climate view (Hisense for cooling/AC alongside Nest for heat).

**Context:** the unit is controlled today via the **ConnectLife** app (Hisense/Gorenje cloud).
Cloud API is acceptable (matches the Ecobee/Nest/Yale pattern). No local-control requirement.

## TL;DR

Build `climate/hisense/` on the **`oyvindwe/connectlife`** Python library (reverse-engineered
ConnectLife cloud API, GPLv3, ~10k weekly PyPI downloads, actively maintained). It does full
**read + write** control, not just status. Home Assistant's `oyvindwe/connectlife-ha` is the
reference for mapping raw ConnectLife properties onto a climate entity.

## Integration options

| Option | What it is | Verdict |
|--------|-----------|---------|
| **`oyvindwe/connectlife`** (lib) + **`connectlife-ha`** (HA) | Community reverse-engineered cloud API. Library on PyPI, HA integration on GitHub/HACS. Actively maintained (v0.43+). | **Chosen.** Clean async Python lib, cloud user/pass, maps onto existing cloud-integration pattern. |
| **`Connectlife-LLC/*`** (official) | Connectlife the company shipped an official HA plugin + `connectlife-cloud` PyPI lib. OAuth2. v1.0.1, Oct 2025. | Newer, less battle-tested, heavier OAuth flow. Fallback if community auth breaks. |
| **`bilan/connectlife-api-connector`** | Older MQTT proxy approach. | Superseded. Skip. |
| `hisense_aehw4a1` / deiger `AirCon` | Local control of the older **AEH-W4A1 wifi dongle**. | Not applicable — that's for pre-ConnectLife modules, not ConnectLife-app devices. |

## What the `oyvindwe/connectlife` library provides

Confirmed from source (`connectlife/api.py`):

**Auth flow** (username/password → tokens):
- Gigya / SAP CDC login: `accounts.eu1.gigya.com/accounts.login` → `accounts.getJWT`
- OAuth2 token exchange at `oauth.hijuconn.com`
- Gateway host: `clife-eu-gateway.hijuconn.com` (EU gateway used even for US accounts — ConnectLife
  is a global platform run out of Gorenje/EU. Only China and Russia/CIS are flagged as special;
  US is expected to work through the EU gateway. Verify on first login.)

**Key methods:**
- `authenticate()` / `login()`
- `get_appliances()` → `Sequence[ConnectLifeAppliance]` (typed); `get_appliances_json()` (raw)
- **`update_appliance(puid, properties: dict[str, str])`** → the write/control path.
  `POST /device/pu/property/set`.
- `get_air_duct_energy(...)`, `get_energy_consumption_curve(...)` → daily kWh + power draw
- `query_static_data(puid)`, `get_property_list(...)` → discover what a device supports

**Discovery tool** (run once against the account before writing any module code):
```
python -m connectlife.dump --username <user> --password <pass>
```
Dumps every property each appliance reports as JSON. Maintainer caveat: **devices report
properties they don't actually support**, so the dump is a starting point, confirmed by poking.

## How Home Assistant maps it to a climate entity (reference)

`connectlife-ha` doesn't hardcode Hisense. It uses per-device-type YAML **data dictionaries**
(`custom_components/connectlife/data_dictionaries/NNN.yaml`) mapping raw ConnectLife properties to
climate features.

Relevant device-type codes:
- `006` portable AC · `008` window AC · `009` air conditioner (multi-zone/ducted variant, has
  `aus_zoneN_*` props) · `016` heat pump

The climate entity reads: **target temperature**, **HVAC mode** (raw int ↔ `HVACMode.COOL/HEAT/...`
via a per-device map), **fan mode**, **swing** (vertical + horizontal). Raw property names look
like `t_temp`, `t_work_mode`, `f_temp` (current temp). Known HA gaps: single setpoint only (no
`target_temp_high/low`); heat-pump state setting is limited.

**Polling: every 60 seconds** — the maintainers are explicit that hammering the cloud API risks a
ban. Writes reflect the changed property immediately; side effects appear at the next poll.

## How it slots into picklehome

Mirror of the existing cloud integrations:
- `climate/hisense/` module, `hisense_cli.py` (argparse + async dispatch)
- Creds in 1Password (`picklehome` vault) → `.env.template` → `python-dotenv`
- `connectlife` added to `pyproject.toml` / `uv.lock`
- Token cache at `~/.local/state/picklehome/hisense-tokens.json` (0600) — the "username/password →
  session token" auth row
- **Sandbox:** `aiohttp`-based, so pass `trust_env=True` and allowlist
  `clife-eu-gateway.hijuconn.com`, `oauth.hijuconn.com`, `accounts.eu1.gigya.com` in
  `.claude/settings.local.json`
- Unified beach house view = Hisense (cooling/AC) alongside Nest (heat), keyed on
  `picklehome/locations.py`

## Probe results (verified against the account)

Ran `python -m connectlife.dump` against the real ConnectLife account (creds in 1Password
`op://picklehome/ConnectLife`). Raw dumps live in the session scratchpad, not committed (they
contain `puid`/`deviceId`/`wifiId`).

**All three open questions answered:**

1. **US gateway — works.** The US account authenticated cleanly through the default EU gateway
   (`clife-eu-gateway.hijuconn.com`) with no special flags. No region workaround needed.
2. **Device type — `009-104`, four indoor heads.** Feature `104` = "冷暖节能无功率"
   (heat + cool, energy-saving, **no power metering**). One appliance per room:

   | Nickname | Room | Current mode | Setpoint | Reads |
   |----------|------|--------------|----------|-------|
   | Master Bedroom AC | Master Bedroom | cool | 70°F | current temp, humidity |
   | Kids Room AC | Kids Bedroom | cool | 69°F | " |
   | Office Bedroom AC | Office Bedroom | cool | 75°F | " |
   | Downstairs AC | Downstairs | cool | 72°F | " |

   Most heads were powered off at probe time (house not actively cooling every room), but all are
   **online and reporting live** — `f_temp_in` and setpoints track the physical units on a slow poll
   cycle, and a setpoint change made at a unit synced back through the API.

   > **Correction:** an earlier draft called these "offline" based on `offlineState=1`. Live testing
   > disproved that: `offlineState` reads `1` on every head regardless of power, including one
   > confirmed physically running. It is **not** an availability signal and must not be rendered as
   > "offline". The temps are current, not last-known.
3. **Community lib is enough.** `oyvindwe/connectlife` handled auth + read + control property model
   for this exact device type. No need for the official `connectlife-cloud` fallback.

### Confirmed property model (009-104, decoded from base `009.yaml` data dictionary)

Controllable (`t_` = target/settable):
- `t_power` → on/off (0/1)
- `t_work_mode` → HVAC mode: **0 fan_only · 1 heat · 2 cool · 3 dry · 4 auto** (units are heat+cool)
- `t_temp` → target temp, range **61–90°F** (`t_temp_type=1` ⇒ Fahrenheit)
- `t_fan_speed` → **0 auto · 5 low · 6 middle_low · 7 medium · 8 middle_high · 9 high**
- `t_swing_direction` (horizontal) / `t_up_down` (vertical) → swing
- Presets via `t_eco` / `t_fan_mute` / `t_sleep` / `t_super`: eco, mute, super (turbo), sleep 1–4, combos

Read-only (`f_` = feedback):
- `f_temp_in` → current room temp
- `f_humidity` → raw humidity (needs scaling; value looked like a sentinel when off)
- `f_electricity` → nominally kW (×0.1), but feature is **无功率 = no power metering**, so treat as
  unreliable/absent on these units. **Energy endpoints (`air_duct_energy`) likely return nothing.**
- `f_e_*` → a full set of fault flags (coil temp, eeprom, fan motor, water-full, wifi, etc.) — good
  raw material for a health/diagnostics view

### Design notes for the build

- **Four zones, not one.** The module and CLI should treat each head as its own entity keyed by
  room/nickname (mirrors how `climate/` handles multiple thermostats).
- **These units heat too.** Original framing was "Nest = heat, Hisense = cool," but the heads are
  heat+cool capable. Worth deciding whether Hisense owns zone heating too, or stays cooling-only in
  the unified view. Not a code question — a home-config decision.
- **No energy data.** Skip the energy-consumption sensors for this device type; `f_electricity` and
  the energy endpoints won't give real numbers on a `无功率` unit.
- **Room-level naming already exists** in ConnectLife (`roomName`/`deviceNickName`), so the unified
  beach house view can lean on those instead of inventing a mapping.

## Sources

- oyvindwe/connectlife (Python lib): https://github.com/oyvindwe/connectlife · https://pypi.org/project/connectlife/
- oyvindwe/connectlife-ha (HA integration): https://github.com/oyvindwe/connectlife-ha
- Connectlife-LLC official HA plugin: https://github.com/Connectlife-LLC/HomeAssistantPluginIntegration · https://pypi.org/project/connectlife-cloud/
- HA community thread: https://community.home-assistant.io/t/add-integration-for-hisense-devices-using-connectlife/459082
- bilan/connectlife-api-connector (older MQTT): https://github.com/bilan/connectlife-api-connector
