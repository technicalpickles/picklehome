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
id, run state, remaining time. "Finished 2h 14m ago" is derived by scanning back for the most recent
running-to-finished transition.

This has to degrade honestly:

| Log state | Output |
|-----------|--------|
| Transition captured | `finished 2h 14m ago` |
| Newest entry older than the transition | `finished sometime in the last 6h` |
| No log, or no transition found | Line omitted entirely |

Never invent precision the log cannot support.

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
  one file.
- **`observations.py`** knows nothing about LG. Append a record, query when a field last changed.
  Pure logic over a file, trivially testable.
- **`lg_cli.py`** formats. No API calls, no business logic.

### Build sequencing

Do not write `client.py` first. The dataclasses are guesswork until we see what these specific
appliances report.

1. Mint the PAT, confirm it works at all (this is the project's single blocker)
2. Dump raw `async_get_device_list()` plus per-device status against the real account
3. Read the JSON together, confirm the fridge setpoint-only finding first-hand, and see whether the
   WashTower reports as one device or two
4. Then write `client.py` against real payloads, keeping them as test fixtures

This mirrors the approach the hisense integration used (`python -m connectlife.dump` before any
module code), which caught a property that every device claimed to support and none actually did.

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
Washer        running    42m left
Dryer         idle
Refrigerator  ok         door closed

$ just lg laundry
Washer (LG WashTower)
  State:      running, Rinse
  Remaining:  42m  (of 1h 58m)
  Ends:       ~3:47 PM
  Remote:     enabled

Dryer (LG WashTower)
  State:      idle
  Last cycle: finished 2h 14m ago

$ just lg fridge
Refrigerator (LG InstaView)
  Fridge:   37 F  (setpoint)
  Freezer:   0 F  (setpoint)
  Door:     closed
  Modes:    eco on, express freeze off
  Filter:   water 62% remaining
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

Remaining, and still a blocker on writing `client.py`:

**Are these specific appliances covered, and what do they actually report?** ThinQ Connect roughly
covers 2019 and newer with no clean published cutoff. The discovery dump answers three things at
once: whether the appliances appear at all, whether the WashTower reports as one device or two (the
SDK defines `WASHTOWER`, `WASHTOWER_WASHER`, `WASHTOWER_DRYER`, `WASHCOMBO_MAIN`, and
`WASHCOMBO_MINI` as distinct types, so both shapes exist in practice), and whether the refrigerator
exposes only `targetTemperature` or something closer to a real measurement.

Filed as `a1cb401b-48d9-46de-9186-4e485bd45766`.

## Future: the watcher

Not built now, but the design should not preclude it. When it happens it is a homelab service on
picklelab following the `homelab/services/` pattern, subscribing to ThinQ's MQTT push, writing the
same observation log at full resolution, and able to notify on cycle completion. Because
`client.py` returns dataclasses and `observations.py` owns the log format, the watcher reuses both
and adds only the subscription loop and the notification path.
