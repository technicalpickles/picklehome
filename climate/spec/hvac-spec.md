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

- **Comfort Heat**: primary occupied mode when it's cold out. Target ~70°F by heating. Active when outdoor temp < 60°F (threshold configurable in `climate/config/weather.yaml`).
- **Comfort Cool**: primary occupied mode when it's warm out. Target ~70°F by cooling. Active when outdoor temp > 65°F.
- **Home**: neutral mode for mild weather (outdoor temp 60–65°F). The house doesn't need much active heating or cooling in this range; Home is set wide enough (68–73°F) to guard against the house getting too hot or cold without running the system much. Also serves as the Ecobee system default if no scheduled mode is active.
- **Eco** (`smart3` climateRef): moderate setback mode. Looser band than Comfort modes but not as aggressive as Away. Used when the space is partially or temporarily unoccupied and full setback isn't warranted.
- **Away** (`away` climateRef): wide temperature range for extended absence (travel, multi-day trips) or genuinely unoccupied zones. Used in the upstairs schedule during school hours, and set manually for the whole house on longer trips.
- **Sleep**: nighttime. Used for downstairs only; upstairs overnight uses Comfort Heat instead. Downstairs Sleep allows the main living space to run cooler at night since no one is actively using it, saving on heating/cooling while keeping the swing modest enough that it doesn't take long or cost much to come back up to temperature in the morning.

The general goal is to hold ~70°F whenever anyone is in a space, regardless of season. The schedule and comfort mode in use determines *how* we get there (heating vs. cooling).

Thermostats require separate heat and cool setpoints with a minimum spread between them, so hitting "exactly 70°F" means defining a heat setpoint (floor) and a cool setpoint (ceiling) that bracket 70°F. Comfort Heat and Comfort Cool are functionally the same target temperature; they just differ in which side of 70°F the thermostat is working from, depending on the season.

The spread between heat and cool setpoints is intentional beyond just satisfying the thermostat minimum. A narrow spread would cause the system to alternate between heating and cooling as the temperature drifts by a degree or two, wearing out equipment and wasting energy. The wider band (5°F at the tightest, 8–9°F for Comfort Cool and the setback modes) gives the house room to breathe without triggering a mode switch.

### Seasonal switching

The schedule uses either Comfort Heat (`smart2`) or Comfort Cool (`smart1`) in every occupied slot; they represent the same 70°F target, just via heating vs. cooling. Run `just climate-comfort-switch auto` to swap between them based on the current outdoor temp. The command uses a hysteresis band (60–65°F): below 60°F it switches to Comfort Heat, above 65°F to Comfort Cool, and in between it makes no change. When outdoor temps are mild (60–65°F), the schedule can be left on whichever mode is currently set; in that range the house doesn't need much active conditioning, and Home mode (68–73°F) acts as a comfortable fallback if neither heating nor cooling is needed. Thresholds are configured in `climate/config/weather.yaml`; station MACs are stored in 1Password and injected via `AMBIENT_STATION_MACS` in `.env`.

**Known defect as of 2026-09-10: the auto-switch does not persist its comfort mode.**
`climate-auto-switch` runs on picklelab as `docker compose run --rm`, and only
`/data` is mounted, so the `schedule.yaml` that `comfort-switch` rewrites lives
in a throwaway container and is discarded when it exits. Every run starts from
the copy baked into the image. Between 2026-03-28 and 2026-06-05 the run log
records 1,259 "switched" events of which 1,220 re-applied a mode a previous run
had already applied, re-pushing a full schedule sync to Ecobee every 15 minutes
(66 of them on 2026-04-19 alone). It only looks healthy in midsummer because
every decision is `cool` and the committed default is already `smart1`, so the
run short-circuits. Expect it to misbehave again the moment overnight lows drop
below 60°F, because the decision also keys off a single instantaneous outdoor
reading with no memory: nights decide `heat`, afternoons decide `cool`, and
neither sticks. Redesign is tracked separately; until it lands, treat the
committed value of `schedule.yaml` as the real seasonal mode.

If someone has manually adjusted a thermostat (creating an Ecobee "hold"), that hold overrides the schedule, so a comfort-switch may have no visible effect until the hold expires or is cleared. Pass `--clear-holds` to clear all active holds on managed thermostats before switching, so the new schedule takes effect immediately. This is opt-in because comfort-switch is run manually and people may have intentionally adjusted the temperature.

### HVAC mode

The thermostat's HVAC mode controls which equipment is allowed to run, independent of the schedule's comfort modes. `comfort-switch` sets the HVAC mode to **auto** (both heating and cooling enabled) on all managed thermostats after syncing the schedule. This ensures the thermostat can actually deliver whichever comfort mode is active. Without it, a thermostat set to "heat" mode would ignore Comfort Cool setpoints, and vice versa. Once seasonal switching runs regularly on a schedule, the HVAC mode could be narrowed to match the season (heat-only or cool-only), but until then "auto" is the safe default.

---

## Downstairs schedule

Same every day of the week.

| Time     | Mode                      | Reason                        |
|----------|---------------------------|-------------------------------|
| 12:00 am | Sleep                     | Everyone asleep               |
| 7:30 am  | Comfort Heat / Comfort Cool | Start warming/cooling before people are up; seasonal switch determines which |

Moved from 6:00 am on 2026-09-10. Sleep's ceiling now sits above Comfort Cool's, so
the flip relaxes into the day instead of tightening it. Flipping at 6:00 am used to
pull the ceiling *down* a degree during the coolest hours of the morning, which had
the AC running at dawn and was a direct contributor to the "house is freezing"
complaint.

---

## Upstairs schedule

### Weekdays (Monday–Friday)

| Time     | Mode                      | Reason                              |
|----------|---------------------------|-------------------------------------|
| 12:00 am | Comfort Heat / Comfort Cool | Bedrooms; seasonal switch determines which |
| 10:00 am | Away                      | Upstairs unoccupied; adults working downstairs, son at school |
| 2:30 pm  | Comfort Heat / Comfort Cool | Son home from school; upstairs becomes active living area |

### Weekends (Saturday–Sunday)

| Time     | Mode                      | Reason              |
|----------|---------------------------|---------------------|
| 12:00 am | Comfort Heat / Comfort Cool | Home all day; seasonal switch determines which |

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
| Comfort Cool | 73   | 65   | Primary occupied mode: outdoor temp > 65°F. Raised 71→73 on 2026-09-10. The 70/71/72 churn through Aug 2026 was partly chasing a different bug: the auto-switch was never persisting its comfort mode (see Seasonal switching), so setpoints were being tuned to compensate for an automation that kept reverting. 71 still left both offices cold and the household was manually holding at 73 most days, so this codifies the hold instead of fighting it. Room-level fixes for Tracy's office (fan/screen/deflector, still pending) remain the real fix. |
| Comfort Heat | 77   | 72   | Primary occupied mode: outdoor temp < 60°F. **The 72°F floor is the whole point** — it compensates for the Ecobee reading cooler than the Nest and for the remote offices feeling cold in winter (radiant loss, see Tracy's office). Previously written as 73/72, a 1°F spread, so Ecobee silently ran it as 75/70 and the real floor was 70. The cool side is 77 purely to buy a legal 5°F spread; in heating season that ceiling is inert. |
| Eco          | 75   | 66   | Moderate setback: allow drift without full Away range. Was 71/68, which Ecobee ran as 72/67, close enough to Comfort Cool that it was not really a setback. Widened so it behaves like one. |
| Sleep        | 74   | 65   | Nighttime energy saving: wide enough to save, narrow enough for quick recovery. Raised 72→74 on 2026-09-10 so it sits above Comfort Cool's ceiling and the 7:30 am flip relaxes rather than tightens. Downstairs is unoccupied overnight (bedrooms are upstairs) and recovering 1°F by morning costs nothing. |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 73   | 68   | Mild weather neutral: minimal active conditioning needed. Was 71/68, a 3°F spread, which Ecobee ran as 72/67. |

### Upstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 73   | 65   | Primary occupied mode: outdoor temp > 65°F. Raised 71→73 on 2026-09-10 alongside downstairs. **Watch the Bedroom sensor:** it runs 4–6°F colder than the upstairs thermostat (thermostat 71–74°F while Bedroom reads 66–69°F over the same week), so a 73 ceiling still leaves the bedroom near 68–69 overnight. The fix for that gap is enrolling the Bedroom sensor into the upstairs climates (task `3f72e752`), not another ceiling bump — only the thermostat's own sensor participates in any climate today. |
| Comfort Heat | 75   | 70   | Primary occupied mode: outdoor temp < 60°F. Was 73/70, a 3°F spread, which Ecobee ran as 74/69. |
| Eco          | 75   | 66   | Moderate setback: allow drift without full Away range. Was 71/68, which Ecobee ran as 72/67. |
| Sleep        | 71   | 66   | Not used in schedule: upstairs uses Comfort Heat overnight |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 73   | 68   | Mild weather neutral: minimal active conditioning needed. Was 71/68, a 3°F spread, which Ecobee ran as 72/67. |
