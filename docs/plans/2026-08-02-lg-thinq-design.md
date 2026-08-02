# LG ThinQ appliance module design

Design for an `lg/` module giving read-only status for the LG appliances in the house: washer,
dryer, and refrigerator. The LG TV is explicitly out of scope (different stack entirely, see
`docs/research/lg-thinq/findings.md`).

**Research:** `docs/research/lg-thinq/findings.md` covers the API landscape and why the official
ThinQ Connect Open API is the chosen path over the reverse-engineered alternatives.

## Goals

- `just lg status` answers "is the dryer done yet" in one glance
- Fridge door state and setpoints, with the setpoint caveat surfaced in the output itself
- Washer/dryer run state and time remaining, plus time since the last cycle finished
- Structured so an always-on watcher can be added later without reworking the client

## Non-goals for v1

Any write path (remote start, setpoint changes, express freeze). The MQTT push watcher and
notifications. The TV. Energy consumption data.

The PAT still gets minted with control and event scopes so adding these later does not require a
new token.

## Architecture

### The observation log

The API reports current state. It does not report when that state changed, and a CLI process that
lives for under a second cannot know that a cycle ended two hours ago.

**Every CLI invocation appends what it observed to a JSONL log** at
`~/.local/state/picklehome/lg-observations.jsonl`. One record per device per run: timestamp, device
id, run state, remaining time, and cycle count where available. "Finished 2h 14m ago" is derived by
scanning back for the most recent completion.

### Completion detection, and why the dryer does not get it in v1

**`END` is not usable on either appliance. Confirmed empirically, not assumed.** Full cycles on both
machines were polled at 60 second intervals on 2026-08-02:

```
dryer:   POWER_OFF -> RUNNING -> COOLING  -> POWER_OFF
washer:  POWER_OFF -> DETECTING -> RUNNING -> RINSING -> SPINNING -> POWER_OFF
```

`END` never appeared in a single sample on either machine. It is in both profiles' run-state enums
and fires on neither. **Any completion logic built on `END` would silently never trigger**, which is
the failure mode that looks like working code.

The active-state sets still matter, and still differ per appliance:

| | Active states declared | Actually observed |
|---|---|---|
| Washer | `INITIAL` `DETECTING` `RUNNING` `SOAKING` `RINSING` `SPINNING` | all but `INITIAL`, `SOAKING` |
| Dryer | `INITIAL` `RUNNING` `COOLING` `WRINKLE_CARE` | `RUNNING`, `COOLING` |

Declared states that never appear are the norm here, not the exception. Treat the enum as the set of
values that *may* arrive, never as a sequence that *will*.

`PAUSE` is neither active nor complete. `ERROR`, `RESERVED`, and `FIRMWARE` are their own thing.
`INITIAL` was never observed either, so it must not be treated as a reliable cycle-start marker.
These sets are per-device-type constants in `client.py`, not a shared list.

That leaves two usable signals, with different reach:

*The active-to-`POWER_OFF` transition.* This is what completion actually looks like on the dryer. It
is a real, detectable event, but only for an observer that is sampling continuously. A CLI that runs
when you happen to type a command will nearly always see `POWER_OFF` with no idea when it arrived.

*The washer's `cycle.cycleCount`.* A monotonic counter. A value higher than the last observation
proves a cycle completed regardless of sampling gaps, which is exactly the weakness the transition
signal has. **The dryer profile has no equivalent property.**

**Verified working.** The counter incremented 48 to 49 in the same sample the washer dropped to
`POWER_OFF`:

```
19:08:40  SPINNING   remain=0h01m  cycleCount=48
19:09:41  POWER_OFF  remain=0h00m  cycleCount=49
```

This is the one completion signal in the whole integration that survives sparse sampling, and it is
the only reason the washer keeps a "finished N ago" line while the dryer does not.

**Consequence for v1: the dryer gets no "finished N ago" line.** The CLI cannot honestly produce it,
and an approximation would be worse than silence for something you actively rely on. The washer
gets it via `cycleCount`. The dryer gets it when the watcher exists, since continuous sampling makes
the active-to-`POWER_OFF` transition catchable.

This is a deliberate scope cut against the original mockup, which showed
`Last cycle: finished 2h 14m ago` under the dryer. That line does not ship in v1.

This has to degrade honestly. For the washer, where `cycleCount` makes completion provable:

| Log state | Output |
|-----------|--------|
| Counter incremented between two close observations | `finished 2h 14m ago` |
| Counter incremented, but the surrounding gap is wide | `finished sometime in the last 6h` |
| No log, or counter unchanged since the last entry | Line omitted entirely |

Never invent precision the log cannot support. `cycleCount` proves *that* a cycle finished; only the
spacing of surrounding observations bounds *when*. Those are different claims and the output has to
reflect which one it can make.

The same file is what a future watcher writes, just at higher resolution. When the service exists it
backfills the same log and the CLI reading code is unchanged. JSONL run logging already has
precedent in the repo via `climate-auto-switch`.

### Module layout

Follows `birdfeeder/`, the most recent cloud-API integration with comparable quirks.

```
lg/
  __init__.py
  lg_cli.py              # argparse: status | laundry | fridge | devices
  thinq/
    __init__.py
    auth.py              # PAT + client id + country from env, session factory
    client.py            # dataclasses + fetch/normalize, only module touching thinqconnect
    observations.py      # JSONL append + transition queries
  README.md
```

Boundaries:

- **`client.py`** is the only place that imports `thinqconnect`. It returns dataclasses (`Laundry`,
  `Refrigerator`) consumed by both the CLI and, later, the watcher. Swapping the SDK means touching
  one file. It also absorbs the payload-shape inconsistencies described below, so nothing downstream
  ever sees a raw LG response.
- **`observations.py`** knows nothing about LG. Append a record, query when a field last changed.
  Pure logic over a file, trivially testable.
- **`lg_cli.py`** formats. No API calls, no business logic.

### Confirmed device model

The discovery dump ran against the real account on 2026-08-02. Full schema detail is in
`docs/research/lg-thinq/findings.md`; what the module has to handle:

| Device | Type | Model |
|--------|------|-------|
| Top Load Washer | `DEVICE_WASHER` | `T1789EFH_F` |
| Dryer | `DEVICE_DRYER` | `RV13U6AM8W_D_US_WIFI` |
| Refrigerator | `DEVICE_REFRIGERATOR` | `2REF11EIDG__4` |

**Three separate appliances, no WashTower.** The `WASHTOWER*` and `WASHCOMBO*` device types are not
relevant here and should not be handled speculatively.

`client.py` normalizes three inconsistencies at the boundary:

1. **Washer status and profile are JSON lists; dryer and refrigerator are dicts.** The washer is
   location-scoped, carrying `location.locationName: "MAIN"` in its single entry.
2. **Profiles are wrapped** in `error` / `notification` / `property`. The schema is under `property`.
3. **Refrigerator units disagree between layers.** The profile declares setpoint ranges in Celsius
   (1 to 7 fridge, -23 to -15 freezer) while status reports Fahrenheit.

Two things not to trust:

- **`deviceInfo.connected` is `null`** on all three devices. It is not an availability signal and
  must not be rendered as online/offline. (`reportable` was `true` for all three.)
- **Timer values persist after a cycle ends.** Both machines read `POWER_OFF` with non-zero leftover
  timer values from a prior cycle. Remaining time is only meaningful when the run state says the
  appliance is active.

Sequencing note, kept because it paid off: dumping before writing the client is what surfaced the
list-vs-dict split and killed the WashTower branch before it was written. Same approach the hisense
integration used, same kind of result.

## Configuration

Three values in `.env` from 1Password. Static token, no refresh, no token file. Matches the "API key
(static)" row of the auth table alongside UniFi and Cloudflare Radar.

```
LG_THINQ_PAT={{ op://picklehome/LG ThinQ/credential }}
LG_THINQ_CLIENT_ID={{ op://picklehome/LG ThinQ/client_id }}
LG_THINQ_COUNTRY={{ op://picklehome/LG ThinQ/country }}
```

The PAT lives in the `credential` field because that is the default field name for 1Password's
API Credential item type. Not worth fighting.

### The client id is self-assigned

**LG does not issue the client id.** It is not shown anywhere in the PAT creation flow, and nothing
on LG's end validates it. The caller invents it. The SDK asks only that each client device use a
unique value and suggests a UUID4.

Confirmed by reading the SDK, where it is used in exactly two places:

- `thinq_api.py` sets it as the `x-client-id` header on every HTTP request
- `mqtt_client.py` passes it as the MQTT client id when connecting to AWS IoT

**It must stay fixed once chosen.** AWS IoT allows one live connection per client id and drops the
existing connection when a second one claims the same id. A value regenerated per invocation would
be harmless for the read-only HTTP path in v1 and actively broken once the watcher exists, which is
the worst kind of bug: invisible until the day it matters.

Storing it in 1Password next to the PAT is a deliberate choice for keeping the credential material
in one place, even though the client id is not itself a secret. The tradeoff is an empty-field
failure mode, so `auth.py` validates that the client id is present and non-empty at load time and
raises with a pointer to the 1Password item rather than letting an empty header reach LG.

## Sandbox

Two known traps from the root CLAUDE.md apply directly:

- **`thinqconnect` creates its own `aiohttp.ClientSession`**, which defaults to `trust_env=False`
  and ignores the sandbox proxy. `auth.py` constructs the session with `trust_env=True` and passes
  it in.
- **`api-aic.lgthinq.com` goes in `sandbox.network.allowedDomains`** in `.claude/settings.local.json`,
  and does not take effect until the next session. First live runs go with the sandbox disabled.

The host is region-derived, not fixed: `thinq_api.py` builds
`https://api-{region}.lgthinq.com/`, where the region comes from mapping the country code through
`DomainPrefix`. There are three regions (`kic` Asia-Pacific, `aic` Americas, `eic` Europe/Africa).
`US` maps to `aic`. `US` is present in the SDK's supported-country list, so the "Aborted: The country
is not supported" error that affects several European countries does not apply here.

## CLI surface

`just lg status` gives a scannable overview, the detail commands give the rest. Quiet by default,
`--json` on every command.

```
$ just lg status
Top Load Washer  rinsing    22m left
Dryer            off
Refrigerator     ok         door closed

$ just lg laundry
Top Load Washer (T1789EFH_F)
  State:      rinsing
  Remaining:  22m  (of 35m)
  Ends:       ~3:47 PM
  Remote:     available now
  Cycles:     48

Dryer (RV13U6AM8W_D_US_WIFI)
  State:      off

$ just lg fridge
Refrigerator (2REF11EIDG__4)
  Fridge:   37 F  (setpoint)
  Freezer:   0 F  (setpoint)
  Door:     closed
  Modes:    power save on, express freeze off
```

`just lg devices --raw` prints unmassaged API JSON. This is the discovery dump from the build
sequencing, kept permanently rather than thrown away. It is the first thing anyone will want when LG
changes a field or a new appliance shows up.

**Fridge temperatures always render with an explicit `(setpoint)` label.** The API exposes
`targetTemperature`, not a measured air temperature. The output has to say so, or someone reads it
as a thermometer six months from now.

`Ends: ~3:47 PM` is derived from remaining time plus current clock, and is rendered with the tilde
to signal it is an estimate.

### Justfile

Shebang plus `"$@"` form, not `{{ARGS}}`, to preserve quoting for multi-word arguments (same fix
applied to `birdfeeder` in 39651ca):

```
# LG appliances: just lg status | laundry | fridge | devices [--raw]
lg *ARGS:
    #!/usr/bin/env bash
    set -euo pipefail
    uv run python lg/lg_cli.py "$@"
```

## Error handling

Per the repo convention, data-fetching code raises with diagnostic context and the CLI catches at
the boundary where it can be presented.

- `client.py` raises with which device, which call, and what the API returned. It never returns
  `None` to mean "something went wrong".
- Per-device fetches use `asyncio.gather(return_exceptions=True)` so one failing appliance does not
  cancel the others.
- A device that errors still appears in the output, marked: `Dryer  unavailable (timeout)`. It does
  not silently vanish from the list.
- Observation logging failures (disk full, bad permissions) warn but do not fail the command. The
  status read is the point; the log is a side effect.

**API rate limits** exist on ThinQ Connect and surface as temporary errors that clear on their own.
Surface them as such rather than as a hard failure, so the message does not send someone debugging
their credentials.

## Device identity

Match appliances on the API's device type, not on nickname. Nicknames are user-editable in the
ThinQ app and will drift. Nicknames are display-only.

**Open unknown:** a WashTower may report as a single combined device or as separate washer and dryer
entries. `laundry` handles both shapes. This gets settled by the discovery dump in step 2, not by
guessing now.

## Testing

`tests/lg/thinq/`, mirroring source layout. All offline, no live API calls, consistent with the rest
of the repo.

- **`client.py`:** mock at the `thinqconnect` boundary using real captured payloads as fixtures.
  Cover a running washer, an idle dryer, a fridge, and a device returning an error inside a
  `gather`.
- **`observations.py`:** pure logic over a `tmp_path` JSONL. This is where the real test value is,
  because the transition logic is the part most likely to be subtly wrong. Cover: empty log, no
  transition present, clean running-to-finished transition, log staler than the transition (must
  produce the imprecise phrasing), and back-to-back cycles where only the most recent counts.
- **Formatting:** the setpoint label and the unavailable-device rendering are worth asserting, since
  both are deliberate correctness choices rather than cosmetics.

## Open questions

**Resolved: a PAT can be minted.** Token created 2026-08-02 with all scopes, stored in 1Password
alongside a generated client id and the `US` country code. The country-support concern does not
apply to the US. Whether the token carries an expiry is still unconfirmed; if it does, that needs a
renewal task.

**Resolved: the appliances are covered and their schema is known.** Discovery dump ran 2026-08-02.
Three separate devices, no WashTower, refrigerator confirmed setpoint-only from the profile itself.
See the Confirmed device model section above. Closes
`a1cb401b-48d9-46de-9186-4e485bd45766`.

**Resolved: completion detection.** Full cycles measured on both machines 2026-08-02. `END` fires on
neither. `cycleCount` verified incrementing 48 to 49 on the washer. The washer gets a "finished N
ago" line, the dryer does not. See the completion detection section above.

**Resolved: the filter percentages carry no data.** Both read `0` on a relatively new refrigerator
whose filters have never been replaced, where real counters would read near 100%. LG's own app does
not display filter status for this model. The fields are unpopulated placeholders. **No filter
information ships**, and `client.py` should not expose the fields at all rather than passing through
a zero that downstream code might render.

No open questions remain. The design is ready to implement.
**Resolved, with a caveat: the PAT shows no expiration date.** The creation flow did not display
one. That is not the same as a documented guarantee that it never expires, so the code should not
assume permanence. `auth.py` distinguishes an authentication rejection (401/403) from other failures
and raises a message naming the likely cause ("LG rejected the token; it may have expired or been
revoked") with a pointer to the 1Password item. Cheaper than rediscovering it later from a generic
error.

## Future: the watcher

Not built now, but the design should not preclude it. When it happens it is a homelab service on
picklelab following the `homelab/services/` pattern, subscribing to ThinQ's MQTT push, writing the
same observation log at full resolution, and able to notify on cycle completion. Because
`client.py` returns dataclasses and `observations.py` owns the log format, the watcher reuses both
and adds only the subscription loop and the notification path.
