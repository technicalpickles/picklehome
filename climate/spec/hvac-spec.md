# HVAC Spec

This document describes the intended HVAC behavior for the home thermostats.
It is the source of truth for schedule and comfort setpoints.
An agent should read this and update `schedule.yaml` and `comforts.yaml` accordingly,
then run `just climate-validate` to confirm the remote matches.

---

## Household context

- **Downstairs**: main living space. Adults work from a home office downstairs during the day.
- **Upstairs**: bedrooms. Not the primary living area during the day, but should stay comfortable enough if someone needs to go up there. Treated as a living area after school ends (2:30pm weekdays).
- Son comes home from school at ~2:30pm on weekdays.
- Cottage thermostat is a separate property and is **not managed by this spec**.

---

## Tracy's office (known comfort problem)

Tracy's office is a converted carport on the downstairs zone: a concrete slab on grade, floor-to-ceiling **east-facing** glass, and a supply register cut into brick that blows directly on her back. It is the worst comfort spot in the house and the two complaints below are seasonal and have **different root causes**, so they need different fixes.

**Summer (cooling season): the room overheats, it does not run cold.** Room-sensor history (`just climate-history`) shows the office tracking the rest of downstairs (~72°F) overnight, then spiking to **77–82°F from ~9am–1pm**, exactly her morning work hours, while the downstairs thermostat sits at 72. The cause is east-facing solar gain (morning sun through the large glass), plus her body and computer load, plus an uninsulated slab/envelope that runs the room ~3°F warm even when empty. The central AC physically cannot beat that solar load in one remote room. What she feels is the paradox of a cold supply draft on her back inside a globally hot room.

**Winter (heating season): the room feels cold and drafty.** This is radiant loss, not air temperature: skin radiates heat toward the cold glass, and the uninsulated slab is a cold radiative floor.

**Strategy: fix the room, not the whole zone.** The historical compensation (bumping the entire downstairs setpoint) is the wrong lever, it over-conditions the main living space to chase one room and, in summer, the cooling-ceiling bump actually makes her overheating *worse*. The intended direction is room-level fixes (block the east sun before the glass, a personal/circulation fan, redirect the register off her back, rug + foot-level heat in winter). Her SmartSensor is used **purely as a data point** (visibility into the room and confirming whether the fixes worked), **not as a temperature-control lever**: neither thermostat control (adding a hot room to the cooling average just overcools the rest of the house) nor driving automations off its reading. Full findings, evidence, and prioritized actions: `docs/plans/2026-06-13-tracy-office-thermal-comfort.md`.

---

## Comfort mode semantics

- **Comfort Heat**: primary occupied mode when it's cold out. Heats toward the floor in the [Comfort setpoints](#comfort-setpoints) table below. Active when the 24-hour mean outdoor temp is below 60°F (threshold configurable in `climate/config/weather.yaml`).
- **Comfort Cool**: primary occupied mode when it's warm out. Cools toward the ceiling in the same table. Active when the 24-hour mean outdoor temp is above 65°F.
- **Home**: neutral mode for mild weather (24-hour mean outdoor temp 60–65°F). The house doesn't need much active heating or cooling in this range; Home is set wide enough (68–73°F) to guard against the house getting too hot or cold without running the system much. Also serves as the Ecobee system default if no scheduled mode is active.
- **Eco** (`smart3` climateRef): moderate setback mode. Looser band than Comfort modes but not as aggressive as Away. Used when the space is partially or temporarily unoccupied and full setback isn't warranted.
- **Away** (`away` climateRef): wide temperature range for extended absence (travel, multi-day trips) or genuinely unoccupied zones. Used in the upstairs schedule during school hours, and set manually for the whole house on longer trips.
- **Sleep**: nighttime. Used for downstairs only; upstairs overnight uses Comfort Heat instead. Downstairs Sleep allows the main living space to run cooler at night since no one is actively using it, saving on heating/cooling while keeping the swing modest enough that it doesn't take long or cost much to come back up to temperature in the morning.

The general goal is a comfortable temperature whenever anyone is in a space, regardless of season — not a fixed number. The [Comfort setpoints](#comfort-setpoints) table below is the source of truth for what that means in practice: after months of tuning it's settled in the low-to-mid 70s (Comfort Cool's 73°F ceiling both zones; Comfort Heat's floor is 72°F downstairs, 70°F upstairs), not a symmetric ~70°F target. The schedule and comfort mode in use determines *how* we get there (heating vs. cooling).

Thermostats require separate heat and cool setpoints with a minimum spread between them (see below), so each comfort mode is defined by a heat setpoint (floor) and a cool setpoint (ceiling) rather than a single number. Comfort Heat and Comfort Cool aren't calibrated to a shared target temperature — each floor/ceiling pair has been tuned independently against how the rooms actually feel; see the per-zone notes in the setpoints table.

The spread between heat and cool setpoints is intentional beyond just satisfying the thermostat minimum. A narrow spread would cause the system to alternate between heating and cooling as the temperature drifts by a degree or two, wearing out equipment and wasting energy. The wider band (5°F at the tightest, 8–9°F for Comfort Cool and the setback modes) gives the house room to breathe without triggering a mode switch.

### Seasonal switching

Every occupied slot resolves to either Comfort Heat (`smart2`) or Comfort Cool (`smart1`) in the thermostat's live program; which one is active depends on season, not a shared target temperature — see the setpoints table for what each actually holds. `schedule.yaml` itself holds neither: occupied slots use the virtual ref `comfort`, resolved to one or the other at push time (see below). Run `just climate-comfort-switch auto` to decide which. The command uses a hysteresis band (60–65°F) applied to the mean outdoor temperature described below, not a live reading: below 60°F it decides Comfort Heat, above 65°F Comfort Cool, and in between it makes no change. When the mean sits in that mild range, the schedule is left on whichever mode is currently set; in that range the house doesn't need much active conditioning, and Home mode (68–73°F) acts as a comfortable fallback if neither heating nor cooling is needed. Thresholds are configured in `climate/config/weather.yaml`; station MACs are stored in 1Password and injected via `AMBIENT_STATION_MACS` in `.env`.

The mode is decided from a **24-hour mean** of outdoor temperature, not a single
reading. Samples come from the run log, which records outdoor temperature every
15 minutes. A full window is 96 samples; below 48 the run makes no change and
logs why.

A mean is used because a shoulder-season day genuinely spans the band — an April
day running 45–80°F would otherwise flip the mode twice daily. Its mean lands
near 62°F, inside the band, which correctly means "leave it alone". The
tradeoff is stickiness: through a long mild spring the mean can sit in the band
for weeks and the house holds whichever mode it was in. That is deliberate and
comfortable, but the seasonal flip happens later than intuition suggests.

**The thermostat is the source of truth for the current mode.** `schedule.yaml`
does not encode a season: occupied slots use the virtual ref `comfort`, resolved
to `smart1` or `smart2` immediately before a push. Each run builds the desired
schedule, compares it to the live program, and pushes **only if they differ**.
No local file records the mode, so there is nothing to desync.

A manual adjustment creates an Ecobee **hold**, which overrides the schedule.
Holds last **4 hours** (`holdAction: useEndTime4hour`) and are never cleared by
the automation. Pass `--clear-holds` to clear them explicitly.

The fixed duration is deliberate. `holdAction: nextPeriod` made a hold last
until the next schedule transition, so the same gesture behaved wildly
differently by zone and time of day: downstairs has transitions at 00:00 and
07:30, so a bump at 8am held for sixteen hours, while upstairs on a weekday has
one at 10:00, so a bump at 9:50am expired in ten minutes. Four hours is
predictable, covers a work block or an evening, and self-clears if forgotten.

After an actual mode change, thermostats with **no** active hold are resumed so
the new schedule applies immediately rather than waiting up to 16 hours for the
next downstairs transition. Thermostats with an active hold are left alone.

### HVAC mode

The thermostat's HVAC mode (`auto`, `heat`, `cool`, `off`) controls which
equipment may run, independent of the schedule's comfort modes.

**The automation never writes it.** A person setting the thermostat to Off, or
to heat-only during a cold snap, is making a deliberate choice that outranks
the schedule. Previously `comfort-switch` forced `auto` on every run, which
meant a household member could not turn the system off — it reverted within 15
minutes with no message and no trace.

The tradeoff is that an HVAC mode can now contradict the active comfort mode:
heat-only left set into June means Comfort Cool cannot cool. This is surfaced,
never corrected. When the current HVAC mode cannot deliver the active comfort
mode, `climate-status` and the run log both say so.

To change it deliberately: `just climate-hvac-mode auto|heat|cool|off`.

---

## Downstairs schedule

Same every day of the week.

| Time     | Mode                      | Reason                        |
|----------|---------------------------|-------------------------------|
| 12:00 am | Sleep                     | Everyone asleep               |
| 7:30 am  | Comfort (`comfort`) | Start warming/cooling before people are up; the seasonal decision resolves it to Comfort Heat or Comfort Cool |

Moved from 6:00 am on 2026-09-10. Sleep's ceiling now sits above Comfort Cool's, so
the flip relaxes into the day instead of tightening it. Flipping at 6:00 am used to
pull the ceiling *down* a degree during the coolest hours of the morning, which had
the AC running at dawn and was a direct contributor to the "house is freezing"
complaint.

Occupied slots are written as `comfort` in `schedule.yaml`. It is a virtual ref
resolved to Comfort Cool (`smart1`) or Comfort Heat (`smart2`) at push time; it
is never sent to Ecobee.

---

## Upstairs schedule

### Weekdays (Monday–Friday)

| Time     | Mode                      | Reason                              |
|----------|---------------------------|-------------------------------------|
| 12:00 am | Comfort (`comfort`) | Bedrooms; the seasonal decision resolves it to Comfort Heat or Comfort Cool |
| 10:00 am | Away                      | Upstairs unoccupied; adults working downstairs, son at school |
| 2:30 pm  | Comfort (`comfort`) | Son home from school; upstairs becomes active living area; the seasonal decision resolves it to Comfort Heat or Comfort Cool |

### Weekends (Saturday–Sunday)

| Time     | Mode                      | Reason              |
|----------|---------------------------|---------------------|
| 12:00 am | Comfort (`comfort`) | Home all day; the seasonal decision resolves it to Comfort Heat or Comfort Cool |

Occupied slots are written as `comfort` in `schedule.yaml`. It is a virtual ref
resolved to Comfort Cool (`smart1`) or Comfort Heat (`smart2`) at push time; it
is never sent to Ecobee.

---

## Comfort setpoints

Temperatures in °F.

**Every setpoint pair here must be at least 5°F apart.** This is not advisory:
the thermostats report `settings.heatCoolMinDelta: 50` (5.0°F), and Ecobee
silently widens anything narrower on write. It splits the difference around the
midpoint, so a too-narrow pair comes back with *both* numbers moved and the
floor you actually cared about quietly lowered. `comforts.yaml` keeps reading
the way you wrote it, and `just climate-comforts-sync --dry-run` prints what it
*would* push rather than a diff against live, so the rewrite is invisible from
the repo side. It went unnoticed for months: Comfort Heat downstairs was written
as 73/72 and the device was actually running 75/70, a 70°F floor instead of the
intended 72°F.

To check for drift, fetch the live program and compare against this table
directly, rather than trusting the dry run.

### Downstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 73   | 68   | Primary occupied mode: 24-hour mean outdoor temp above 65°F. Raised 71→73 on 2026-09-10. **Heat floor raised 65→68 on 2026-09-10**, after the 24-hour-mean switch made it load-bearing: the band can hold Comfort Cool for weeks, so on a 45°F autumn night the old 65 floor let the house fall to 65 before anything heated. Under the previous instantaneous switcher any cold night flipped to Comfort Heat and its 70–72 floor, so 65 was harmless; it stopped being harmless when the flip got slower. 73/68 is exactly Ecobee's 5°F minimum spread, and the floor is inert in summer. The 70/71/72 churn through Aug 2026 was partly chasing a different bug: the auto-switch was never persisting its comfort mode, so setpoints were being tuned to compensate for an automation that kept reverting. 71 still left both offices cold and the household was manually holding at 73 most days, so this codifies the hold instead of fighting it. Room-level fixes for Tracy's office (fan/screen/deflector, still pending) remain the real fix. |
| Comfort Heat | 77   | 72   | Primary occupied mode: 24-hour mean outdoor temp below 60°F. **The 72°F floor is the whole point** — it compensates for the Ecobee reading cooler than the Nest and for the remote offices feeling cold in winter (radiant loss, see Tracy's office). Previously written as 73/72, a 1°F spread, so Ecobee silently ran it as 75/70 and the real floor was 70. The cool side is 77 purely to buy a legal 5°F spread; in heating season that ceiling is inert. |
| Eco          | 75   | 66   | Moderate setback: allow drift without full Away range. Was 71/68, which Ecobee ran as 72/67, close enough to Comfort Cool that it was not really a setback. Widened so it behaves like one. |
| Sleep        | 74   | 65   | Nighttime energy saving: wide enough to save, narrow enough for quick recovery. Raised 72→74 on 2026-09-10 so it sits above Comfort Cool's ceiling and the 7:30 am flip relaxes rather than tightens. Downstairs is unoccupied overnight (bedrooms are upstairs) and recovering 1°F by morning costs nothing. |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 73   | 68   | Mild weather neutral: minimal active conditioning needed. Was 71/68, a 3°F spread, which Ecobee ran as 72/67. |

### Upstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 73   | 68   | Primary occupied mode: 24-hour mean outdoor temp above 65°F. Raised 71→73 on 2026-09-10 alongside downstairs. **Heat floor raised 65→68 on 2026-09-10**, after the 24-hour-mean switch made it load-bearing: the band can hold Comfort Cool for weeks, so on a 45°F autumn night the old 65 floor let the house fall to 65 before anything heated. Under the previous instantaneous switcher any cold night flipped to Comfort Heat and its 70–72 floor, so 65 was harmless; it stopped being harmless when the flip got slower. 73/68 is exactly Ecobee's 5°F minimum spread, and the floor is inert in summer. **Watch the Bedroom sensor:** it runs 4–6°F colder than the upstairs thermostat (thermostat 71–74°F while Bedroom reads 66–69°F over the same week), so a 73 ceiling still leaves the bedroom near 68–69 overnight. The fix for that gap is enrolling the Bedroom sensor into the upstairs climates (task `3f72e752`), not another ceiling bump — only the thermostat's own sensor participates in any climate today. |
| Comfort Heat | 75   | 70   | Primary occupied mode: 24-hour mean outdoor temp below 60°F. Was 73/70, a 3°F spread, which Ecobee ran as 74/69. |
| Eco          | 75   | 66   | Moderate setback: allow drift without full Away range. Was 71/68, which Ecobee ran as 72/67. |
| Sleep        | 71   | 66   | Not used in schedule: upstairs uses Comfort Heat overnight |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 73   | 68   | Mild weather neutral: minimal active conditioning needed. Was 71/68, a 3°F spread, which Ecobee ran as 72/67. |
