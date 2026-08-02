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

The API's temperature field is **`targetTemperature`**, the setpoint, not a measured air
temperature. Multiple people working against the raw JSON have looked for actual sensor readings and
found none for any appliance. Plan for this rather than discovering it mid-build.

What the fridge does report:

- Binary sensors: door open/closed, eco mode, power saving, sabbath mode
- Number entities: temperature setpoints (fridge and freezer)
- Switches: express mode, express cool, quick freeze
- Select: fresh air filter
- Sensors: filter and water filter status

Door open/closed is genuinely useful. For real internal temperature, a standalone sensor is the
answer, not an LG integration.

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
