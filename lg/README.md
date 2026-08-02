# LG Appliances: ThinQ Connect

Read-only status for the LG washer, dryer, and refrigerator via LG's official ThinQ Connect Open
API (`thinqconnect`). The LG TV is out of scope -- it uses a completely separate local webOS
protocol, not this API. See `docs/research/lg-thinq/findings.md` for the full research behind this
choice, and `docs/plans/2026-08-02-lg-thinq-design.md` for the design this module implements.

## Setup

1. Mint a Personal Access Token at https://connect-pat.lgthinq.com, authorizing all scopes (view
   devices/statuses, control, event subscription, push notifications, energy). The control/event
   scopes aren't used by this read-only module, but including them now avoids re-minting a token
   later if a watcher gets built.
2. Generate a client id: any UUID4 works. **LG does not issue or validate this value** -- see
   "The client id is self-assigned" below.
3. Store the PAT, client id, and country code in the `LG ThinQ` item in the `picklehome` 1Password
   vault. The PAT goes in the `credential` field (1Password's default field name for the API
   Credential item type).
4. Run `just dotenv` to inject `LG_THINQ_PAT` / `LG_THINQ_CLIENT_ID` / `LG_THINQ_COUNTRY` into
   `.env` (see `.env.template`).
5. Check status: `just lg status`

## Commands

```
just lg status              # one line per device: state, time remaining
just lg laundry [--json]    # washer + dryer detail: state, remaining, ends-at, remote, cycles
just lg fridge [--json]     # refrigerator detail: setpoints, door, modes
just lg devices [--json]    # device inventory: alias, type, model
just lg devices --raw       # unmassaged API JSON (profile + status) per device
```

`devices --raw` is the discovery dump from the initial build, kept permanently. It's the first
thing to reach for when LG changes a field or a new appliance shows up on the account.

**Filter fields in `--raw` output are unpopulated placeholders, not measurements.** Unlike the
massaged commands (which drop these fields entirely, see below), `--raw` prints
`refrigeration.freshAirFilterRemainPercent` and `waterFilterInfo.waterFilter1RemainPercent` as-is --
by design, it's an unmassaged dump. Both always read `0` on this account despite neither filter ever
being replaced; don't mistake that `0` for "filter needs changing."

## Architecture

### Auth

Static PAT, no refresh -- same shape as UniFi and Cloudflare Radar (`lg/thinq/auth.py`). Every
invocation builds a fresh `ThinQApi` client from `LG_THINQ_PAT` / `LG_THINQ_CLIENT_ID` /
`LG_THINQ_COUNTRY`. `auth.py` validates all three are present and non-empty before building
anything, since the client id in particular is silently accepted as a blank header otherwise (see
below).

**Auth-related API errors are distinguished from ordinary failures.** `thinqconnect`'s
`ThinQAPIException` carries LG's own error code rather than the raw HTTP status, so
`lg/thinq/client.py` classifies on that code: `INVALID_TOKEN`, `INVALID_TOKEN_AGAIN`, and
`NOT_FOUND_TOKEN` raise `LGThinQAuthError` with a message pointing at the 1Password item and naming
expiry/revocation as the likely cause. `EXCEEDED_API_CALLS` raises `LGThinQRateLimitError`, worded
as transient rather than a hard failure. Everything else raises the base `LGThinQError` with which
device/call/response failed.

### The client id is self-assigned

**LG does not issue the client id** -- it isn't shown anywhere in the PAT creation flow, and
nothing on LG's end validates it. The caller invents it (a UUID4 is fine). Confirmed by reading the
SDK: it's used only as the `x-client-id` HTTP header and as the MQTT client id for the (unused in
v1) push-event path.

**It must stay fixed once chosen.** AWS IoT permits one live MQTT connection per client id and
drops the existing connection when a second one claims the same id. Regenerating it per invocation
would be harmless for this read-only HTTP-only module, but would silently break a future MQTT
watcher. It's stored in 1Password alongside the PAT for that reason, even though it isn't itself a
secret.

### Sandbox

`thinqconnect` builds its own `aiohttp.ClientSession` when one isn't supplied, defaulting to
`trust_env=False` -- it ignores the Claude Code sandbox's proxy-based network allowlisting.
`lg/thinq/auth.py` builds the session itself (`trust_env=True`) and passes it into `ThinQApi`, the
same fix used by `birdfeeder/vicohome` and `climate/hisense`.

`api-aic.lgthinq.com` is in `sandbox.network.allowedDomains` in `.claude/settings.local.json`.
Domain allowlist changes take effect on the *next* session, not the current one -- first live runs
against real credentials should go with the sandbox disabled.

### Payload shapes are not consistent across device types

Confirmed against the real account on 2026-08-02 (`docs/research/lg-thinq/findings.md`):

- **Washer status and profile are JSON lists; dryer and refrigerator are dicts.** The washer is
  location-scoped, its single list entry carrying `location.locationName: "MAIN"`.
  `lg/thinq/client.py`'s `_as_dict` normalizes both shapes to a dict before anything else touches
  them.
- **Profiles are wrapped** in `error` / `notification` / `property`; the actual schema lives under
  `property` (and for the washer, `property` is itself a one-item list).
- **`deviceInfo.connected` is always `null`** on this account. It is not an availability signal and
  is never rendered as online/offline anywhere in this module.

### Completion detection, and why the dryer doesn't get it

`runState.currentState` declares an `END` value in both the washer and dryer profiles. **It fires
on neither appliance** -- confirmed across two full cycles polled at 60-second intervals. Both
machines go straight from their last active state (`SPINNING` / `COOLING`) to `POWER_OFF`. Any
completion logic built on `END` would silently never trigger.

The washer has a second signal the dryer lacks: `cycle.cycleCount`, a monotonic counter. A count
higher than the last observation proves a cycle completed, regardless of how sparsely the appliance
was polled -- confirmed incrementing 48 -> 49 in the same sample the washer dropped to `POWER_OFF`.
**The dryer profile has no equivalent property.** Since a CLI that runs when you happen to type a
command can't otherwise know a state change happened between invocations, the washer gets a
"finished N ago" line derived from this counter and the dryer does not. This is a deliberate v1
scope cut, not an oversight -- see the design doc's "Completion detection" section. A future
MQTT-based watcher, sampling continuously, could catch the dryer's active-to-`POWER_OFF` transition
directly and backfill the same log at higher resolution.

Active-state sets differ per appliance and are declared as constants in `lg/thinq/client.py`
(`WASHER_ACTIVE_STATES`, `DRYER_ACTIVE_STATES`) rather than a shared list. `PAUSE` is deliberately in
neither set -- it's not active, and it's not completion either.

### Timer values are only meaningful while active

`remain == 0` while a run state is active means "not yet computed", not "done": the washer reports
`remain 0h00m` / `total 0h58m` during `DETECTING`, before it has sensed the load. Rendered literally
that's "0m left" on a cycle with 58 minutes to go, so `client.py` treats `remain_minutes` as unknown
(`None`) whenever the reported value is `0` while active.

While *not* active, timer fields are placeholder or stale values, not real data: the dryer reads a
fixed `0h01m` / `0h01m` both before and after a cycle; the washer instead retains its last real
`total` from the previous cycle. Both are equally meaningless, so `Laundry.remain_minutes` and
`.total_minutes` are only populated when `.active` is `True`.

`total` is also not a stable denominator on the washer -- it changes mid-cycle as the machine
refines its estimate (`0h58m` while detecting, down to `0h35m` once spinning). It's rendered as-is
each time (`Remaining: Xm (of Ym)`), it just isn't safe to assume `Ym` stays constant across polls.

### Refrigerator temperatures are setpoints

The refrigerator API exposes `targetTemperature`, not a measured air temperature -- there is no
`current`/`measure`/`ambient`/`sensor` key anywhere in the profile or status for this model. Every
place this module renders a fridge or freezer temperature includes an explicit `(setpoint)` label
(`lg/lg_cli.py`); leaving it off reads as a thermometer to someone six months from now.

The profile and status also disagree on units: the profile declares setpoint ranges in Celsius (1
to 7 fridge, -23 to -15 freezer) while status has always reported Fahrenheit on this account so far.
Rather than assume that stays true, `client.py` reads the sibling `unit` key that comes with each
`temperature` entry and renders whatever unit the payload actually reports; if a `targetTemperature`
ever showed up without its `unit`, `get_refrigerator` raises rather than guessing "F" (a display-unit
flip to Celsius would otherwise render a setpoint like `3 F`, i.e. an apparently-frozen fridge).

### Filter fields carry no data

Both `refrigeration.freshAirFilterRemainPercent` and `waterFilterInfo.waterFilter1RemainPercent`
read `0` on this account despite neither filter ever having been replaced (a genuinely-tracked
filter would read near 100%, not 0), and LG's own ThinQ app doesn't display filter status for this
model at all. These are unpopulated placeholders, not measurements. `Refrigerator` doesn't expose
filter fields at all, rather than passing through a zero that a caller might render as meaningful.

### `remoteControlEnable` is a live state, not a capability

It answers "can this be remote-controlled right now", not "does this appliance support remote
control" -- confirmed `False` at rest and `True` for the duration of a dryer cycle, back to `False`
at power off (and `False` throughout an entire washer cycle on this account, since availability is
per-appliance and per-moment, not a fixed property). Rendered as "available now" / "not available
now", never as a capability claim.

### The observation log

Every `status` / `laundry` / `fridge` invocation appends what it observed to
`~/.local/state/picklehome/lg-observations.jsonl`: one JSON record per device per run (timestamp,
device id, state, and cycle count where applicable). "Finished 2h 14m ago" for the washer is derived
by scanning this log for the most recent `cycle.cycleCount` increase.

`lg/thinq/observations.py` knows nothing about LG -- it's generic append-a-record /
query-a-numeric-field-increase logic over a JSONL file, reusable by anything with the same "current
state only, no change events" problem. Rather than one estimate, a completion is reported as two
bounds -- `earliest_ago` (time since the counter was first seen at its new value) and `latest_ago`
(time since it was last seen below that value) -- so the output can never claim more precision than
the surrounding observations actually support:

| Log state | Output |
|-----------|--------|
| Counter incremented, first seen on this very invocation | `finished within the last 6h` |
| Counter incremented between two close observations | `finished about 2h 14m ago` |
| Counter incremented, but the surrounding gap is wide | `finished between 7d and 8d ago` |
| No log, or counter unchanged since the last entry | Line omitted entirely |

Log write failures (disk full, bad permissions) print a warning to stderr but never fail the
command -- the status read is the point, the log is a side effect. The same goes for a log *read*
failure (e.g. a permissions problem) when rendering the "Last cycle" line: it warns and omits the
line rather than taking down the whole command.

A washer paused mid-load (`PAUSE`) never gets a "Last cycle" line either, even though `PAUSE` isn't
an active state -- showing "Last cycle: finished ..." directly under "State: pause" would read as if
the load in the machine right now just finished, when it actually describes the previous one.

The same file is what a future MQTT-based watcher would write, just at higher resolution; the CLI's
reading code wouldn't need to change.

## Module structure

```
lg/
  lg_cli.py               # CLI entry point (argparse): status | laundry | fridge | devices
  thinq/
    auth.py               # Env var credentials, ThinQApi + sandbox-safe session factory
    client.py              # The only module touching thinqconnect; dataclasses + normalization
    observations.py        # Generic JSONL append + counter-transition queries (no LG knowledge)
```

## Non-goals (v1)

No write/control paths (remote start, setpoint changes, express freeze) -- only
`async_get_device_list`, `async_get_device_profile`, and `async_get_device_status` are called. No
MQTT push subscription, no notifications, no energy consumption data, no TV. The PAT is minted with
control and event scopes anyway so adding these later doesn't require a new token.
