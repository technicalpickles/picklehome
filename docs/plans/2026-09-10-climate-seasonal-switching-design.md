# Climate seasonal switching: redesign

**Date:** 2026-09-10
**Status:** design approved, not implemented
**Scope:** the seasonal comfort-mode switcher (`climate-auto-switch`) and the
device settings it writes. Sensor participation (task `3f72e752`) and the
time-of-day Comfort Cool ceiling (task `9d05efc2`) are explicitly out of scope.

Closes tasks `461eea71` (mode never persists) and `c48e156a` (stale
`smart1`/`smart2` comments in `schedule.yaml`).

---

## The problem

`climate-auto-switch` runs on picklelab every 15 minutes via a systemd timer
(`docker compose run --rm`, only `/data` bind-mounted). It decides between
Comfort Heat (`smart2`) and Comfort Cool (`smart1`) from the outdoor
temperature and pushes the resulting weekly schedule to Ecobee.

Three defects, found 2026-09-10 while investigating a "house is too cold"
complaint.

### 1. The guard reads an ephemeral artifact

The switcher encodes the current mode by rewriting `climate/config/schedule.yaml`
in place (`_apply_comfort_mode`, a regex that swaps `smart1`↔`smart2` in
`climate:` value positions). That file is baked into the container image, so
the rewrite is discarded when the container exits and every run starts from
the committed copy again.

The mode *is* already persisted durably — `/data/last-state.json` holds it and
survives the container. The code even reads it:

```python
previous_mode = last_state["mode"] if last_state else None   # durable, then ignored
updated = _apply_comfort_mode(original, mode)                # ephemeral file
if updated == original:
    skipped = True                                           # guard on the ephemeral thing
else:
    schedule_path.write_text(updated)
    switched = True
cmd_sync(sync_args)                                          # runs unconditionally
```

`previous_mode` is logged and never used to decide anything.

Effect, from the run log (2026-03-28 → 2026-06-05): **1,259 `switched` events,
1,220 of which re-applied a mode a previous run had already applied.** 66 on
2026-04-19 alone. `switched: true` means "the file text changed", not "the
thermostat changed".

It looks healthy from June onward only because every decision is `cool` and
the committed default is already `smart1`, so the text comparison short-circuits.
Expect it to resume misbehaving once overnight lows drop below 60°F.

### 2. The decision has no memory

The mode is chosen from a single instantaneous outdoor reading, sampled every
15 minutes, against a 60/65°F hysteresis band. On a shoulder-season day that
spans the band in both directions the decision oscillates all day. Observed
range on 2026-04-19: 49.8–69.6°F.

### 3. It writes device settings unconditionally

Every run ends with `set_hvac_mode(..., "auto")` and, for any thermostat
without an active hold, `resume_program`. Neither is gated on anything having
changed. `set_hvac_mode` does not check the current value before writing.

The user-visible consequence: **a person cannot turn the system off.** Setting
the thermostat to Off, or to heat-only during a cold snap, is reverted to
`auto` within 15 minutes with no message and no trace.

---

## Design

### Mode representation: the thermostat is the source of truth

`schedule.yaml` stops encoding the season. Occupied slots use a virtual
climate ref:

```yaml
_everyday: &downstairs_everyday
  - time: "00:00"
    climate: sleep
  - time: "07:30"
    climate: comfort      # resolves to smart1 or smart2 at push time
```

`away`, `home` and `sleep` remain literal climate refs. Only `comfort` is
virtual, and it never reaches the Ecobee API — it is resolved to a real
climateRef before any push.

Each run:

1. Decide the mode (below).
2. Resolve `comfort` → `smart1` (cool) or `smart2` (heat).
3. Build the desired 7×48 schedule array.
4. Compare against the live program.
5. Push **only if they differ**.

The comparison is over the 7×48 schedule array only. Comfort **setpoints** are
not part of it: `push_schedule` passes the live `program["climates"]` straight
through, and setpoints are owned by a separate path (`comforts.yaml` /
`climate-comforts-sync`). A setpoint edited in the Ecobee app therefore
survives this command untouched.

`diff_schedules` (`climate/ecobee/schedule.py:202`) already produces exactly
this comparison and `cmd_validate` already uses it.

**Why this shape.** There is no local record of the mode to lose, desync, or
consult incorrectly — the question "what mode are we in" is answered by asking
the device. Container ephemerality stops mattering by construction rather than
by being handled. The operation becomes idempotent: run it a thousand times,
it pushes once.

This also dissolves task `c48e156a` instead of fixing it. The trailing
`# Comfort Cool` comments drifted because the mode was stored as a text
mutation and the swapping regex deliberately did not touch comments. A file
that no longer encodes a season has no such comments.

**Rejected alternative — persist `mode.json` in `/data`.** Roughly ten lines:
use `previous_mode` as the guard, make the push conditional. Genuinely cheaper.
Rejected because `last-state.json` records *what the automation believes it
did*, not what is true, and it desyncs silently on a partial push, an app-side
edit, a restored volume, or a manual `climate-sync` from a laptop. Once
desynced, an early return guarantees it never self-corrects: state says `cool`,
device says `heat`, decision is `cool`, return. That trades visible thrashing
for permanent invisible drift.

This codebase has now produced two bugs of that exact shape — `comforts.yaml`
disagreeing with the device about `heatCoolMinDelta` (see
`climate/spec/hvac-spec.md`), and the schedule guard disagreeing with the
device about mode. Both stayed invisible for months because nothing compared
local intent against device reality.

**Rejected alternative — bind-mount the config directory.** Makes the existing
rewrite survive. Fixes persistence that is not actually broken, leaves the
unconditional push and the comment drift in place, and creates a live config
file that silently diverges from git.

### Decision: 24-hour mean outdoor temperature

Source is the existing `/data/run-log.jsonl`. It already carries
`outdoor_temp_f` at 15-minute resolution back to 2026-03-28, needs no
additional API call, and lives on the mounted volume.

Read the tail of the file (256KB comfortably covers 24h at roughly 870
bytes/entry), parse each line, keep entries within the last 24 hours, take the
arithmetic mean. Thresholds are unchanged and stay in `climate/config/weather.yaml`:

| 24h mean | Decision |
|---|---|
| `< heat_below` (60°F) | Comfort Heat (`smart2`) |
| `> cool_above` (65°F) | Comfort Cool (`smart1`) |
| between | no change |

**Why a mean and not the instantaneous reading.** An April day spanning
45–80°F averages near 62°F, landing in the band, which correctly means "leave
it alone" rather than flipping twice a day. One full diurnal cycle is the
natural unit for "what season does it feel like".

**Accepted tradeoff — stickiness.** In a long mild spring the mean can sit in
the band for weeks, so the house holds whatever mode it was in. Given Comfort
Heat is 72–77°F and Comfort Cool 65–73°F downstairs, drifting through mild
weather on either is comfortable and cheap. The flip will happen later than a
person might intuitively expect; this is deliberate.

**The window is fed by the command itself.** Every run continues to fetch the
current outdoor temperature from Ambient Weather and write it to the run log,
regardless of what it decides or whether it pushes. That instantaneous reading
is no longer what the decision is made from, but it is what future windows are
built out of — so the fetch-and-log step must not be optimised away along with
the unconditional push. A run that fails before logging (for example, an Ecobee
fetch error) contributes no sample, which is why gaps are expected and handled.

**Guard — insufficient samples.** A full window is 96 samples. If fewer than
48 are present (cold start, timer outage, restored volume), make no change and
log the reason. The current device mode is always a safe fallback.

Every run logs the mean, the sample count, the window bounds, the decision,
and whether it pushed, so the reasoning is inspectable afterward rather than
reconstructed.

### What the automation may write

This section governs what a household member using only the Ecobee app or the
physical thermostat will experience.

**`hvacMode`: never written by the timer.** `set_hvac_mode` is removed from
the run path. Off stays off. Heat-only stays heat-only. A human choosing a
system mode is making a deliberate choice and outranks the automation. Setting
it moves to an explicit `just climate-hvac-mode <mode>`.

The accepted risk is someone leaving heat-only set into June. Mitigation is a
warning, not a correction: when the current `hvacMode` cannot deliver the
active comfort mode (`heat` while Comfort Cool is scheduled, `cool` while
Comfort Heat is scheduled, or `off`), surface it in the run log and in
`climate-status`. Loud, never corrective.

**`resume_program`: only after an actual mode change, and only on thermostats
with no active hold.** Today it fires roughly 96×/day; this reduces it to
roughly 2×/year. An active hold is never cleared except by an explicit
`--clear-holds`.

It is kept rather than dropped because a program change does not take effect
until the next schedule transition, and downstairs has only two transitions a
day — a seasonal switch could otherwise wait up to 16 hours, which matters
during a real cold snap.

**`holdAction` → `useEndTime4hour`, pushed once by an explicit command.**

Today `holdAction` is `nextPeriod`, so a walk-up temperature bump lasts until
the next schedule transition. Because that depends on schedule shape, the same
gesture behaves wildly differently: downstairs has transitions at 00:00 and
07:30, so a bump at 8am holds for about sixteen hours; upstairs on a weekday
has one at 10:00, so a bump at 9:50am expires in ten minutes. A fixed four-hour
hold is predictable, identical on both thermostats, long enough to cover a work
block or an evening, and short enough that a forgotten bump self-clears.

This is a device setting affecting everyone's muscle memory, so it is pushed
by a manual `climate-settings-sync`, never by the timer.

**Verify the enum spelling before relying on it.** The device currently reports
`holdAction: nextPeriod`, while pyecobee's `set_hold` uses a *different*
vocabulary for its own `hold_type` parameter (`nextTransition`). The settings
enum is believed to be one of `useEndTime4hour`, `useEndTime2hour`,
`nextPeriod`, `indefinite`, `askMe`, but this must be confirmed empirically:
push the value, read the live program back, and diff. Ecobee is known to accept
and silently rewrite out-of-range values rather than erroring (see the
`heatCoolMinDelta` finding in `climate/spec/hvac-spec.md`), so a successful
HTTP response is not evidence the value took.

### Command surface

| Command | Change |
|---|---|
| `climate-comfort-switch auto` | 24h-mean decision; pushes only when the desired schedule differs from live |
| `climate-sync` | resolves `comfort` from the **live** mode, preserving the current season; `--mode heat\|cool` forces |
| `climate-validate` | validates structure resolved at the live mode, so it no longer reports a false diff merely because the season changed |
| `climate-hvac-mode <mode>` | new; explicit, manual |
| `climate-settings-sync` | new; pushes `holdAction`; manual only |

`climate-sync` defaults to preserving the live mode because a structural sync
(for example, moving a transition time) should not have the side effect of
flipping the season.

**Resolving the live mode when it is not determinable.** "The live mode" means
whichever of `smart1`/`smart2` appears in the live program's occupied slots. If
the live program contains neither (a freshly reset thermostat, or a schedule
hand-edited in the app to use only `home`/`away`/`sleep`), fall back in this
order: decide from the 24-hour window; if the window is also unavailable, fail
with a message naming the thermostat and requiring an explicit
`--mode heat|cool`. Do not guess a default — silently picking a season is how
the original bug stayed invisible.

---

## Testing

`tests/climate/` mirroring the source layout, offline, mocked at the client
boundary, per the repo's existing test conventions.

Cases that matter:

- **Rolling window:** full window, sparse window below the 48-sample floor,
  empty log, entries straddling the 24h boundary, malformed lines skipped.
- **Band decisions:** below `heat_below`, above `cool_above`, inside the band,
  and exactly on each threshold.
- **Ref resolution:** `comfort` → `smart1`/`smart2` both directions;
  `away`/`home`/`sleep` pass through untouched; `comfort` accepted by
  `validate_climate_refs` while genuinely unknown refs still raise.
- **Idempotence (the regression that motivated this):** the same decision run
  twice pushes exactly once.
- **Settings are not written:** a normal run issues no `set_hvac_mode` call and
  no `resume_program` call when the mode is unchanged.

---

## Documentation changes

`climate/spec/hvac-spec.md` is the declared source of truth for thermostat
behavior, and `climate/CLAUDE.md` mandates spec-first ordering: *"If the
desired behavior is changing, update the spec first, then derive YAML
changes."* This design is a behavior change, so **the spec is updated before
`schedule.yaml` is touched**, not afterwards. That is an ordering constraint on
the implementation plan, not a cleanup step at the end.

Three of these are not additions but *corrections* — they document behavior
this design removes, so leaving them would make the spec actively wrong rather
than merely incomplete.

### `climate/spec/hvac-spec.md`

| Section | Change | Why |
|---|---|---|
| `### HVAC mode` | **Rewrite.** Currently states `comfort-switch` sets HVAC mode to auto after syncing and calls auto "the safe default". | Becomes false. Replace with: the timer never writes `hvacMode`; a human's choice outranks the automation; a mode that cannot deliver the active comfort mode is warned about, never corrected; `climate-hvac-mode` is the explicit lever. |
| `### Seasonal switching` | **Replace** the "Known defect as of 2026-09-10" paragraph. | That paragraph documents the bug this design fixes. Replace with the new mechanism: 24-hour mean, thermostat as source of truth, push only on difference. |
| Hold behavior paragraph ("If someone has manually adjusted a thermostat...") | **Amend.** | `resume_program` gating changes, and holds now expire on a fixed 4-hour timer rather than at the next transition. |
| Downstairs / Upstairs schedule tables | **Amend** the "Comfort Heat / Comfort Cool" rows. | Intent is unchanged, but the rows should name the `comfort` ref so the spec and `schedule.yaml` use the same vocabulary. |
| *(new)* Hold duration | **Add.** | `holdAction: useEndTime4hour` is household-visible behavior — how long a walk-up bump lasts — and belongs in the source of truth, not only in a design doc. |

### `climate/config/schedule.yaml`

The header comment currently reads *"Climate values must be climateRef strings
from your Ecobee thermostat."* That becomes false — `comfort` is deliberately
not a climateRef. Update it to describe the virtual ref and point at the spec.

### `climate/README.md`

- The Ecobee architecture note ("smart1 and smart2 are swappable for seasonal
  switching") stays true in intent but describes a mechanism that no longer
  exists; reword to the diff-and-push model.
- Command reference gains `climate-hvac-mode` and `climate-settings-sync`.
- The `schedule.yaml` row in the config-file table should mention the virtual
  `comfort` ref, since that is the surprising part for anyone editing it.

Per `docs/CONVENTIONS.md`, this design doc is a point-in-time artifact and does
not get updated as the code evolves — the spec and README are the living
documents, which is exactly why they must be corrected as part of this work
rather than left pointing at the old behavior.

## Rollout

Config change plus `just deploy-climate`, same shape as the 2026-09-10
setpoint deploy. Because `schedule.yaml` must be baked into the image to take
effect, the schedule change and the code change deploy together.

The `comfort` token is repo-side only and never reaches the thermostat, so
nothing changes in the Ecobee app. The first run after deploy should find the
device already matching and do nothing — a boring no-op is the correct outcome
and the first thing to verify in the run log.

`holdAction` and `hvacMode` changes are separate manual steps, deliberately not
part of the deploy.

## Follow-ups not in scope

- **Run log rotation.** 13.9MB after 5.5 months, roughly 30MB/year. Not urgent,
  but reading its tail every 15 minutes makes rotation worth filing.
- **Sensor participation** (`3f72e752`) — the Bedroom sensor reads 4–6°F colder
  than the upstairs thermostat and is enrolled in no climate. Separate axis:
  which sensors feed the control loop, not what the setpoints are.
- **Time-of-day Comfort Cool ceiling** (`9d05efc2`) — note this and sensor
  participation are competing answers to the same complaint, and applying both
  to the same zone would over-correct. Ecobee targets the *average* of
  participating sensors, so enrollment helps upstairs (Bedroom reads cold, pulls
  the average down, AC runs less) and would hurt downstairs (Tracy's office
  reads +6–11°F when occupied, pulls the average up, overcools the main space).
  A time-of-day split also needs a second cool *and* a second heat climate,
  which does not obviously fit within Ecobee's six climate slots — all six are
  currently in use.
