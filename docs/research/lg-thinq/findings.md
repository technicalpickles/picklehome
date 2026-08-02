# LG appliance + TV integration (ThinQ, webOS)

Research into integration points for the LG devices in the house: refrigerator, TV, washer, and
dryer. Goal is read-oriented status, specifically fridge temperature and washer/dryer progress
(time remaining, time since a cycle finished).

**Context:** cloud APIs are acceptable, matching the Ecobee/Nest/Yale/BlueAir pattern. No
local-control requirement for the appliances. Research only, nothing built yet.

## TL;DR

The TV and the appliances are unrelated problems with no shared library, protocol, or auth.

- **Appliances:** build on **`thinqconnect`**, LG's own Python SDK for the ThinQ Connect Open API
  (Apache 2.0, published by LG, async/aiohttp, v1.0.13 as of June 2026). Auth is a static Personal
  Access Token, so it slots into the existing "API key (static)" row of the auth table alongside
  UniFi and Cloudflare. Supports MQTT push events, not just polling.
- **TV:** entirely separate. Local network, no cloud, no account. **`aiowebostv`**, maintained under
  the `home-assistant-libs` org.
- **Expectation to set now:** the fridge reports its **setpoint**, not a measured internal
  temperature. Washer/dryer remaining time is real and works well.

## Appliances: two API generations

| Option | What it is | Verdict |
|--------|-----------|---------|
| **ThinQ Connect Open API** + `thinqconnect` | LG's official public API, opened Dec 2024, with a first-party Python SDK. PAT auth, MQTT push. | **Chosen.** Sanctioned, maintained, async, no rate-limit games. |
| `wideq` (ThinQ v1) | Reverse-engineered client for the original SmartThinQ API. Abandoned upstream, many forks. | Legacy. Only if a device predates ThinQ Connect. |
| `thinq2-python` (ThinQ v2) | Reverse-engineered v2 client. Author's own README calls it a work in progress with no tests, docs, or stable API. | Legacy, riskier than wideq. Skip. |

**LG is actively hostile to the reverse-engineered path.** The `ha-smartthinq-sensors` README warns
that polling more often than every 300 seconds gets the account **blocked for 24 hours**, and that
the whole approach breaks if the LG account is a Google/Facebook/Amazon social login. That alone
settles the choice.

## What `thinqconnect` provides

- Install: `pip install thinqconnect`. Requires Python >= 3.10, built on `aiohttp`.
- Repo: `thinq-connect/pythinqconnect`, Apache 2.0, published by LG.
- Auth needs three things: a **Personal Access Token** from https://connect-pat.lgthinq.com, a
  **client ID** (generate a UUID4 once and keep it stable), and a **country code**.
- Covers 24 to 27 appliance profiles including Refrigerator, Washer, Dryer, and the WashTower
  washer/dryer combo units.
- Entry point is `ThinQApi` with `async_get_device_list()`, then per-device status and control calls.
- **Event handling over MQTT (AWS IoT Core)** with callbacks, so device state changes push rather
  than requiring a poll loop.

**Scopes to authorize when creating the PAT** (per the Home Assistant docs, which use the same API):
view all devices, view all device statuses, all device control rights, all device event subscription
rights, all device push notification permissions, and device energy consumption inquiry.

LG also ships `thinq-connect/thinqconnect-mcp`, an MCP server built on the same SDK. Not needed for a
CLI module, but worth knowing it exists if agent-driven appliance control ever comes up.

## What we actually get for the stated goals

### Washer and dryer: good

The API exposes current status, **remaining time**, total time, and cycle count, plus remote-start
capability, a start/pause button, delayed start/end, operation mode selection, and power control.

"Time since finished" is not a field. Derive it by watching the run state and stamping the transition
to finished, then subtracting. The MQTT push path makes this accurate, since the state change arrives
immediately instead of being discovered up to a poll interval late.

### Refrigerator: partial

**Confirmed first-hand against the account on 2026-08-02, from the device profile rather than just
the status payload.** The entire temperature property is:

```json
"targetTemperature": { "mode": ["r","w"], "type": "range",
                       "value": {"r": {"min": 1, "max": 7, "step": 1}} }
```

There is no `current`, `measure`, `ambient`, `internal`, `actual`, or `sensor` key anywhere in the
profile or status. The setpoint is all there is. For a real internal temperature, use a standalone
sensor.

Note the unit inconsistency: the **profile declares ranges in Celsius** (1 to 7 C fridge, -23 to
-15 C freezer) while the **status reports Fahrenheit**. Any code doing range validation has to
convert.

What the fridge does report:

- Binary sensors: door open/closed, eco mode, power saving, sabbath mode
- Number entities: temperature setpoints (fridge and freezer)
- Switches: express mode, express cool, quick freeze
- Select: fresh air filter
- Sensors: filter and water filter status

Door open/closed is genuinely useful. For real internal temperature, a standalone sensor is the
answer, not an LG integration.

## Confirmed against the account, 2026-08-02

Everything above this point was research. This section is what a read-only discovery dump
(`async_get_device_list` + `async_get_device_profile` + `async_get_device_status`) actually returned.

### Inventory

| Device | Type | Model |
|--------|------|-------|
| Top Load Washer | `DEVICE_WASHER` | `T1789EFH_F` |
| Dryer | `DEVICE_DRYER` | `RV13U6AM8W_D_US_WIFI` |
| Refrigerator | `DEVICE_REFRIGERATOR` | `2REF11EIDG__4` |

**Three separate appliances, no WashTower.** The washer and dryer are independent devices, so none
of the `WASHTOWER*` or `WASHCOMBO*` device types apply here. The one-device-or-two question is
settled.

### Payload shapes are not consistent across device types

Two normalization traps, both of which crash naive code:

1. **Washer status and profile come back as a JSON list; dryer and refrigerator come back as
   dicts.** The washer is location-scoped (its single entry carries
   `location.locationName: "MAIN"`). Any client has to handle both shapes.
2. **Profiles are wrapped.** Top level is `error`, `notification`, and `property`. The actual
   schema lives under `property`.

`deviceInfo.connected` came back `null` for all three, so it is not usable as an availability
signal. `reportable` was `true` for all three.

### Run states differ per appliance

These are the full enums from each profile's `runState.currentState`:

```
washer:  INITIAL DETECTING RUNNING SOAKING RINSING SPINNING
         PAUSE END RESERVED ERROR FIRMWARE POWER_OFF
dryer:   INITIAL RUNNING COOLING WRINKLE_CARE PAUSE END ERROR POWER_OFF
```

**"Running" is a set of states, not one state**, and the set differs between the two machines. Both
share `END` as the completion marker.

### The washer has a cycle counter, the dryer does not

The washer reports `cycle.cycleCount` (read-only number, observed at 48). It is monotonic, so a
higher value than the last observation proves a cycle completed regardless of how sparsely the
appliance was polled. The dryer profile has no equivalent property.

### Observed dryer cycle, polled at 60s

A full cycle on `RV13U6AM8W_D_US_WIFI`, 2026-08-02:

```
17:42  POWER_OFF  remain 0h01m  total 0h01m  remote=False
17:47  RUNNING    remain 0h30m  total 0h30m  remote=True
18:12  COOLING    remain 0h05m  total 0h30m  remote=True
18:17  POWER_OFF  remain 0h01m  total 0h01m  remote=False
```

**`END` never appeared in any sample, and neither did `INITIAL`.** Both are in the profile's enum.
The dryer transitions from `COOLING` straight to `POWER_OFF`. Completion logic that waits for `END`
will never fire on this appliance.

Other confirmations from the same run:

- **Remaining time is accurate while active.** It decremented exactly one minute per minute across
  25 consecutive samples. `total` was set once at cycle start and held.
- **When `POWER_OFF`, the timer reads a fixed `0h01m / 0h01m` placeholder** on this dryer, both
  before and after the cycle. It is not a frozen last-known value, it is meaningless.
- **`remoteControlEnabled` is a live state, not a capability.** `False` at rest, `True` for the
  duration of the cycle, back to `False` at power off. It answers "can this be remote-controlled
  right now", not "does this appliance support remote control".

### Observed washer cycle, polled at 60s

A full cycle on `T1789EFH_F`, 2026-08-02:

```
18:29  DETECTING  remain 0h00m  total 0h58m  cc=48  remote=False
18:31  RUNNING    remain 0h38m  total 0h38m  cc=48  remote=False
18:xx  RINSING                  total 0h35m  cc=48  remote=False
19:08  SPINNING   remain 0h01m  total 0h35m  cc=48  remote=False
19:09  POWER_OFF  remain 0h00m  total 0h35m  cc=49  remote=False
```

**`END` never appeared here either**, nor did `INITIAL` or `SOAKING`. The washer goes `SPINNING`
straight to `POWER_OFF`, exactly like the dryer goes `COOLING` straight to `POWER_OFF`. `END` is
declared in both profiles and fires on neither.

**`cycleCount` incremented 48 to 49 in the same sample as the drop to `POWER_OFF`.** This is the
only completion signal confirmed to survive sparse sampling, and only the washer has it.

Two behaviors that differ from the dryer:

- **`total` is a live estimate on the washer, not a constant.** It read `0h58m` during `DETECTING`
  (before the machine sensed the load), `0h38m` at the start of `RUNNING`, then `0h35m` for the rest
  of the cycle. The dryer set `total` once and held it. Do not treat `total` as a stable denominator.
- **`remain: 0` while in an active state means "not yet computed", not "done".** During `DETECTING`
  the washer reported `remain 0h00m` alongside `total 0h58m`. Rendering that literally produces
  "0m left" on a load that has 58 minutes to go.

Also unlike the dryer, the washer **retained `total 0h35m` at `POWER_OFF`** rather than resetting to
a placeholder. Idle timer behavior is per-appliance and cannot be generalized.

`remoteControlEnabled` stayed `False` for this washer's entire cycle, where the dryer's was `True`
throughout its run. Remote availability is per-appliance, not a function of run state.

### Timer shape

Both expose `remainHour` / `remainMinute` / `totalHour` / `totalMinute`. The washer additionally has
`relativeHourToStart` (read **and write**, 0 to 19) and `relativeMinuteToStart` (read-only) for
delayed start.

Observed while both machines were `POWER_OFF`, the timer retained non-zero leftovers from a previous
cycle (dryer read `remain 0h01m / total 0h01m`). **Timer values are not meaningful unless the run
state says they are.**

### Filter percentages are unpopulated, not measurements

Both `refrigeration.freshAirFilterRemainPercent` and `waterFilterInfo.waterFilter1RemainPercent`
return `0`. **These are not real readings. Do not render them.**

The reasoning, since `0` is superficially plausible as "filter expired":

- The refrigerator is relatively new and **neither filter has ever been replaced**. Genuinely
  tracked filters would therefore read near 100%, not 0. Fresh filters cannot be at zero.
- **LG's own ThinQ app does not display filter status for this model anywhere.** Their UI declines
  to render the field, which is a strong signal there is nothing behind it.
- Both fields declare as bare `{"mode": ["r"], "type": "number"}` with no `min`/`max`/`step`, unlike
  `targetTemperature`, which declares a full range. Consistent with a field that is present in the
  schema but not wired to hardware.
- Both reading exactly `0` simultaneously fits "default value for an unset number" better than two
  independent counters coincidentally bottoming out together.

Note this is despite the device declaring `TIME_TO_CHANGE_WATER_FILTER`, `TIME_TO_CHANGE_FILTER`,
`FILTER_RESET_COMPLETE`, and `WATER_FILTER_RESET_COMPLETE` in its push notification list. **A
declared notification type is not evidence that the corresponding status field carries data.** That
inference was made during this investigation and was wrong.

## TV: separate stack entirely

The TV is **not** in the ThinQ Connect device list. TVs use the local webOS SSAP protocol.

- Library: **`aiowebostv`**, maintained under `home-assistant-libs`, which means it tracks Home
  Assistant releases and stays current.
- Home Assistant equivalent: the `webostv` integration, IoT class **Local Push**, on roughly 12% of
  active HA installs.
- Setup: enable "LG Connect Apps" in the TV's network settings, pair once, done. No LG account, no
  cloud round trip.
- Provides power state, current app, input, volume, media controls, and on-screen toast messages.
- **Gotcha:** the TV cannot be powered on over the network once fully off. The standard workaround is
  Wake-on-LAN or HDMI-CEC.

## Home Assistant, for reference

Not the chosen path here, but useful as a reference implementation of both API generations.

| | `lg_thinq` (HA core) | `ha-smartthinq-sensors` (HACS) |
|---|---|---|
| API | Official ThinQ Connect | Reverse-engineered v1/v2 |
| Auth | PAT | LG username/password |
| IoT class | Cloud Push (MQTT) | Cloud Poll, 300s floor |
| Coverage | Fewer entities | More entities |
| Risk | Sanctioned | Rate-limit bans |

The HACS integration's own README now points users at the native one unless they need the extra
entities. The `lg_thinq` docs are the best available cross-check on which properties each appliance
type actually exposes, since LG's API reference is thinner.

## Elsewhere

- **openHAB:** has an LG ThinQ binding
- **Hubitat:** community `jonozzz/hubitat-thinqconnect`, built on the official API
- **Homey:** LG did an official partnership, ThinQ devices are native
- **Domoticz:** `majki09/domoticz_lg_thinq_plugin`
- **Matter:** a dead end for this. LG's Matter support covers select TVs for local control.
  Appliances are not there.

## Design notes for the build

If this becomes an `lg/` module:

- **PAT is a static token in `.env`** via 1Password, same shape as UniFi and Cloudflare Radar. No
  token file under `~/.local/state/picklehome/`, no refresh logic.
- The client ID must be **stable across runs**. Generate a UUID4 once and store it in 1Password
  alongside the PAT rather than regenerating per invocation.
- **Sandbox: `thinqconnect` creates its own `aiohttp.ClientSession`.** Per the aiohttp gotcha in the
  root CLAUDE.md, that defaults to `trust_env=False` and will ignore the sandbox proxy. Pass a
  pre-configured session in, or run with the sandbox disabled.
- Add LG's API host to `sandbox.network.allowedDomains` in `.claude/settings.local.json`, and
  remember it does not take effect until the next session.
- Model the CLI on `birdfeeder/`, the most recent cloud-API integration with comparable quirks.
- **MQTT push vs. polling** is a real design fork. A one-shot CLI wants polling. A "washer finished"
  notification wants the push path and therefore a long-running process, which is a homelab service,
  not a CLI. Worth deciding before writing code.

## Open questions

Both are blockers, and both are five-minute checks:

1. **Can a PAT actually be minted?** Everything depends on this. There is community chatter about
   people hitting trouble at connect-pat.lgthinq.com, and the HA docs mention an "Aborted: The
   country is not supported" error without publishing a supported-country list. Go to the site and
   confirm before anything else.
2. **Do our specific models show up?** ThinQ Connect roughly covers 2019 and newer, but there is no
   clean published cutoff. `async_get_device_list()` against the account answers this immediately,
   and also confirms the fridge-setpoint-only finding first-hand.

## Sources

- LG ThinQ Connect Python SDK: https://github.com/thinq-connect/pythinqconnect · https://pypi.org/project/thinqconnect/
- ThinQ Connect MCP server: https://github.com/thinq-connect/thinqconnect-mcp
- PAT creation: https://connect-pat.lgthinq.com
- LG ThinQ developer site: https://thinq.developer.lge.com/en/cloud/docs/thinq-connect/
- Home Assistant `lg_thinq`: https://www.home-assistant.io/integrations/lg_thinq/
- ollo69/ha-smartthinq-sensors: https://github.com/ollo69/ha-smartthinq-sensors
- Home Assistant `webostv`: https://www.home-assistant.io/integrations/webostv/
- aiowebostv: https://github.com/home-assistant-libs/aiowebostv
- wideq: https://github.com/sampsyo/wideq · thinq2-python: https://github.com/tinkerborg/thinq2-python
- openHAB LG ThinQ binding: https://www.openhab.org/addons/bindings/lgthinq/
- hubitat-thinqconnect: https://github.com/jonozzz/hubitat-thinqconnect
- LG opens the ThinQ API: https://www.cnx-software.com/2024/12/18/lg-opens-the-thinq-api-for-smart-home-devices/
