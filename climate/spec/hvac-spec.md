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
- **Home**: neutral mode for mild weather (outdoor temp 60–65°F). The house doesn't need much active heating or cooling in this range; Home is set wide enough (68–71°F) to guard against the house getting too hot or cold without running the system much. Also serves as the Ecobee system default if no scheduled mode is active.
- **Eco** (`smart3` climateRef): moderate setback mode. Looser band than Comfort modes but not as aggressive as Away. Used when the space is partially or temporarily unoccupied and full setback isn't warranted.
- **Away** (`away` climateRef): wide temperature range for extended absence (travel, multi-day trips) or genuinely unoccupied zones. Used in the upstairs schedule during school hours, and set manually for the whole house on longer trips.
- **Sleep**: nighttime. Used for downstairs only; upstairs overnight uses Comfort Heat instead. Downstairs Sleep allows the main living space to run cooler at night since no one is actively using it, saving on heating/cooling while keeping the swing modest enough that it doesn't take long or cost much to come back up to temperature in the morning.

The general goal is to hold ~70°F whenever anyone is in a space, regardless of season. The schedule and comfort mode in use determines *how* we get there (heating vs. cooling).

Thermostats require separate heat and cool setpoints with a minimum spread between them, so hitting "exactly 70°F" means defining a heat setpoint (floor) and a cool setpoint (ceiling) that bracket 70°F. Comfort Heat and Comfort Cool are functionally the same target temperature; they just differ in which side of 70°F the thermostat is working from, depending on the season.

The spread between heat and cool setpoints is intentional beyond just satisfying the thermostat minimum. A narrow spread would cause the system to alternate between heating and cooling as the temperature drifts by a degree or two, wearing out equipment and wasting energy. The wider band (typically 3–5°F) gives the house room to breathe without triggering a mode switch.

### Seasonal switching

The schedule uses either Comfort Heat (`smart2`) or Comfort Cool (`smart1`) in every occupied slot; they represent the same 70°F target, just via heating vs. cooling. Run `just climate-comfort-switch auto` to swap between them based on the current outdoor temp. The command uses a hysteresis band (60–65°F): below 60°F it switches to Comfort Heat, above 65°F to Comfort Cool, and in between it makes no change. When outdoor temps are mild (60–65°F), the schedule can be left on whichever mode is currently set; in that range the house doesn't need much active conditioning, and Home mode (68–71°F) acts as a comfortable fallback if neither heating nor cooling is needed. Thresholds are configured in `climate/config/weather.yaml`; station MACs are stored in 1Password and injected via `AMBIENT_STATION_MACS` in `.env`.

If someone has manually adjusted a thermostat (creating an Ecobee "hold"), that hold overrides the schedule, so a comfort-switch may have no visible effect until the hold expires or is cleared. Pass `--clear-holds` to clear all active holds on managed thermostats before switching, so the new schedule takes effect immediately. This is opt-in because comfort-switch is run manually and people may have intentionally adjusted the temperature.

### HVAC mode

The thermostat's HVAC mode controls which equipment is allowed to run, independent of the schedule's comfort modes. `comfort-switch` sets the HVAC mode to **auto** (both heating and cooling enabled) on all managed thermostats after syncing the schedule. This ensures the thermostat can actually deliver whichever comfort mode is active. Without it, a thermostat set to "heat" mode would ignore Comfort Cool setpoints, and vice versa. Once seasonal switching runs regularly on a schedule, the HVAC mode could be narrowed to match the season (heat-only or cool-only), but until then "auto" is the safe default.

---

## Downstairs schedule

Same every day of the week.

| Time     | Mode                      | Reason                        |
|----------|---------------------------|-------------------------------|
| 12:00 am | Sleep                     | Everyone asleep               |
| 6:00 am  | Comfort Heat / Comfort Cool | Start warming/cooling before people are up; seasonal switch determines which |

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

Temperatures in °F. Minimum 5°F spread required between heat and cool.

### Downstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 70   | 65   | Primary occupied mode: outdoor temp > 65°F. Matches the ~70°F target directly. The former +1°F ceiling (72) meant to offset Tracy's office was dropped 2026-08-09 without waiting on her room-level fixes (fan/screen/deflector, still pending): it was already flagged counterproductive for her actual overheating problem, and the rest of downstairs (e.g. the home office) was running hot during the day as a result (see Tracy's office) |
| Comfort Heat | 73   | 72   | Primary occupied mode: outdoor temp < 60°F; set higher than upstairs to compensate for Ecobee running cooler than Nest and remote offices (Josh's office, Tracy's office) feeling cold in winter (radiant loss, see Tracy's office) |
| Eco          | 71   | 68   | Moderate setback: allow drift without full Away range |
| Sleep        | 72   | 65   | Nighttime energy saving: wide enough to save, narrow enough for quick recovery |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 71   | 68   | Mild weather neutral: minimal active conditioning needed |

### Upstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 71   | 65   | Primary occupied mode: outdoor temp > 65°F |
| Comfort Heat | 73   | 70   | Primary occupied mode: outdoor temp < 60°F |
| Eco          | 71   | 68   | Moderate setback: allow drift without full Away range |
| Sleep        | 71   | 66   | Not used in schedule: upstairs uses Comfort Heat overnight |
| Away         | 82   | 64   | Wide setback for unoccupied zones / extended absence |
| Home         | 71   | 68   | Mild weather neutral: minimal active conditioning needed |
