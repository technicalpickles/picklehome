# A journal and a comfort log for picklehome

**Status:** proposal, open questions answered 2026-10-18. Nothing here is built.
**Modeled on:** pickleclaw's `docs/journal/` and its "a session that changes something writes, in the same PR" rule.

## Why

Things that happen to the house system are getting lost, and the loss already cost us once. On 2026-10-18 an analysis of Tracy's office comfort treated the `Tracy Office` sensor as if it had always been on her desk. It hadn't: it spent about three weeks in the living room and media room for diagnostics (2026-09-10 to 2026-10-03), keeping its name the whole time. The moves were recoverable only by digging through two session transcripts, a taskwarrior annotation, and a closed task. Nothing in the repo recorded them.

The same is true of the other evidence this work runs on:

| What happened | Where it lives today |
|---|---|
| Sensor moves | Session transcripts, one closed task |
| IR thermometer readings | A taskwarrior annotation thread, a `.parkinglot/` file |
| "Tracy says it's too cool at her desk" | Chat, and nowhere durable |
| Device-side changes (`tempCorrection`, Eco+ off, automation paused) | The thermostat, plus whatever the session happened to note |
| Setpoint and schedule changes | Git (good), but without the reason it felt wrong |

The complaint we're chasing is a feel report, and the sensor can't see feel. So reports are data here, and we're not capturing them.

## Goals

- Answer "when did X happen, and what did we know then?" without transcript archaeology.
- Make physical-world facts (where a sensor is, what Tracy reported, what an IR gun read) available to analysis, so a script can say "this series was in the office from A to B."
- Make capture a habit that costs seconds, owned by the agent as much as by Josh.

## Non-goals

- Replacing taskwarrior (todos), the spec (intended behavior), or ADRs (decisions).
- A dashboard or a database. Files in git, same as everything else here.
- Journaling every command. Only things that change state or report an observation.

## Anti-goals

- A system that needs Josh to remember a ritual. If capture only works when he's disciplined, it won't survive a busy week.
- Two places that both claim to be the truth for the same fact. The README sensor table and the event log must not drift.

## The shape: two layers

### 1. `docs/journal/YYYY-MM.md` (prose, all modules)

Straight from pickleclaw. One file per month, dated entries, newest at the bottom, one to five lines each, past tense, linking out to wherever the substance lives (a plan, the spec, a README section, a taskwarrior UUID). It answers "what did we do on the 18th?" and works for climate, homelab, and network alike.

Entries start with a module tag, so one timeline stays greppable per area:

```markdown
## 2026-10-18

- [climate] Added a sensor placement log and `climate-history --start/--end/--equipment`. See [PR 132](...).
- [homelab] Paused the climate-auto-switch timer across deploys. See [ADR 0001](../adr/0001-pause-climate-auto-switch-timer.md).
```

Tags to start: `[climate]`, `[homelab]`, `[network]`. Add one when a new area shows up; an untagged entry means cross-cutting. `grep '\[climate\]' docs/journal/*.md` gives the scoped view.

A session that changes something writes a journal line in the same PR. The journal is an index, not an archive: a line that needs more than five lines means the substance belongs somewhere else, written first.

### 2. `climate/log/YYYY-MM.yaml` (structured events, climate only)

Prose can't be joined to temperature history. Events can. One append-only YAML list per month, each entry a single observation or change:

```yaml
- at: 2026-10-03T17:30:00-04:00      # local time with offset; omit the time of day if unknown
  kind: sensor-move
  who: josh
  where: tracy-office
  what: Tracy Office sensor back on her desk after three weeks in other rooms
  refs: [task:8364d4dc, session:a4514908]

- at: 2026-10-16
  kind: report
  who: tracy
  where: tracy-office
  feel: cool                         # cool | cold | warm | hot | drafty
  what: Too cool at her desk during the day
```

Kinds, each there because we've already needed it:

| Kind | Example | Notes |
|---|---|---|
| `sensor-move` | Tracy Office sensor to the living room mantle | `where` is the new location; the previous one closes the interval |
| `report` | Tracy says it's too cool at her desk | `feel` plus an optional `temp_f` if someone measured |
| `reading` | IR thermometer at the thermostat wall: 75.3 | `temp_f`, `device`, and what was pointed at |
| `device-change` | `tempCorrection` 95, Eco+ off, automation paused | Changes made at the thermostat or app that git can't see |
| `intervention` | Vent deflector installed, fan placed | The physical fixes the plan doc lists |
| `note` | Anything else worth a timestamp | Escape hatch, so nothing is blocked on picking a kind |

Setpoint and schedule changes are not events: `git log` on `comforts.yaml` is already the record. Events are for what git can't see.

Source of truth rule: the event log owns sensor placement. The README's placement table (added in PR 132) becomes a short pointer plus the table regenerated from the log, or gets replaced by it. One owner, so they can't drift.

## The habit

Written into `climate/CLAUDE.md`, because that's where the agent reads its workflow:

1. **Josh reports something physical** (a feel, a measurement, a move, a change on the device): append an event in the same turn, then continue. The agent does this without asking. If Josh didn't give a time, use now and say so.
2. **A session changes something** (code, config, hardware): a journal line in the same PR, linking to the plan, spec section, or task.
3. **Before analyzing history**, read the month's log for moves and changes that affect how to read the series. This is the step that would have saved the 2026-10-18 analysis.

Capture should be nearly free. A thin `just climate-note` recipe (`just climate-note report tracy-office "too cool at her desk" --feel cool`) appends a correctly formatted entry with the current local time. That's the only tooling in the first cut.

## What this unlocks later (not in scope now)

- `climate-history --events` overlays the log on the daily tables, so a sensor-move boundary shows up next to the numbers it affects.
- An analysis helper that returns "periods where this sensor was in room R", so scripts filter instead of eyeballing.
- A monthly comfort summary: reports against AC runtime and outdoor temperature.

## Decisions I made (flag any you disagree with)

- **One journal for everything, tagged by module.** Josh wants homelab, network, and climate covered but scoped. A single timeline answers "what else changed that week?", and the tag gives the scoped view. The alternative is a journal per module (`climate/journal/`, `homelab/journal/`), which matches how each module already owns its README and CLAUDE.md but loses the cross-module timeline. Easy to switch before there's history.
- **YAML, one file per month.** Readable in a diff, comments allowed, and monthly files keep appends small and merge conflicts unlikely. JSONL would be easier to append to by script but worse for a human to correct. Easy to change before there's history.
- **Climate-only for the structured log.** The journal covers everything, but the event kinds are all thermal-comfort shaped. If lighting or network grow the same need, give them their own log rather than a generic one nobody can query.
- **Reports are first-class.** The point of this exercise is that Tracy's feel is evidence. Treating it as a note would bury it again.
- **No retroactive reconstruction beyond October.** Backfill the moves and device changes we already pinned down (below), and stop there.

## Backfill for the first PR

Facts we already have sources for:

| When | Kind | What |
|---|---|---|
| 2026-09-10 evening | `sensor-move` | Tracy Office sensor to the living room mantle |
| 2026-09-11 evening | `sensor-move` | To the media room (probably the "TV room" of the 10-03 notes) |
| 2026-10-03 ~12:50 | `device-change` | Downstairs `tempCorrection` set to 9.5 F |
| 2026-10-03 afternoon | `sensor-move` | Back on Tracy's desk |
| 2026-10-03 | `reading` | IR vs thermostat and sensors (task `d58603c0`) |
| 2026-10-06 | `device-change` | Remote sensors enrolled in all climates, built-in sensors dropped |
| 2026-10-16 | `device-change` | Follow Me off |
| 2026-10-18 | `device-change` | Eco+ turned off. Eco+ bundles humidity adjustments, Follow Me, and learning the schedule, so one event, with those named in `what` |
| 2026-10-18 | `device-change` | `climate-auto-switch` timer paused, see `docs/adr/0001-pause-climate-auto-switch-timer.md` |

Both the timer pause (ADR 0001) and Eco+ went off on 2026-10-18.

## Answered by Josh (2026-10-18)

1. "All the automation" means the `climate-auto-switch` timer, plus Eco+, which itself includes humidity adjustments, Follow Me, and learning the schedule. All off.
2. Tracy's feel reaches the system through conversation only for now. No form or text front door.
3. The journal covers homelab, network, climate and the rest, scoped by tag (see the decisions above).
