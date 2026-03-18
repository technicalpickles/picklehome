# HVAC Spec

This document describes the intended HVAC behavior for the home thermostats.
It is the source of truth for schedule and comfort setpoints.
An agent should read this and update `schedule.yaml` and `comforts.yaml` accordingly,
then run `just ecobee-validate` to confirm the remote matches.

---

## Household context

- **Downstairs** — main living space. Adults work from a home office downstairs during the day.
- **Upstairs** — bedrooms. Not the primary living area during the day, but should stay comfortable enough if someone needs to go up there. Treated as a living area after school ends (3pm weekdays).
- Son comes home from school at ~2:30pm on weekdays.
- Cottage thermostat is a separate property and is **not managed by this spec**.

---

## Comfort mode semantics

- **Comfort Heat** — primary occupied mode when it's cold out. Target ~70°F by heating. Active when outdoor temp < 60°F (threshold configurable in `climate/config/weather.yaml`).
- **Comfort Cool** — primary occupied mode when it's warm out. Target ~70°F by cooling. Active when outdoor temp > 65°F.
- **Eco** (`away` climateRef) — used when away from the house (day trips, errands, etc.). Allows a wider temperature range to save energy. Also used for upstairs during school hours since that zone is genuinely unoccupied even though adults are home downstairs — a dedicated "unoccupied zone" comfort may make more sense here in the future.
- **Away** — extended absence from home (travel, multi-day trips). Wider temperature range than Eco. Not used in the regular schedule.
- **Sleep** — nighttime. Downstairs only in practice; upstairs overnight uses Comfort Heat.

The general goal is to hold ~70°F whenever anyone is in a space, regardless of season. The schedule and comfort mode in use determines *how* we get there (heating vs. cooling).

### Seasonal switching

Run `just climate-comfort-switch auto` to read the current outdoor temp from configured Ambient Weather Network stations and switch the schedule automatically. The command uses a hysteresis band (60–65°F) to avoid unnecessary switching near the threshold. Station MACs and thresholds are configured in `climate/config/weather.yaml`.

---

## Downstairs schedule

Same every day of the week.

| Time     | Mode        | Reason                        |
|----------|-------------|-------------------------------|
| 12:00 am | Sleep       | Everyone asleep               |
| 6:00 am  | Comfort Heat | Start warming up before people are up |

---

## Upstairs schedule

### Weekdays (Monday–Friday)

| Time     | Mode        | Reason                              |
|----------|-------------|-------------------------------------|
| 12:00 am | Comfort Heat | Bedrooms — sleep mode same as Comfort Heat in practice |
| 10:00 am | Away (Eco)  | Upstairs unoccupied — adults working downstairs, son at school |
| 2:30 pm  | Comfort Heat | Son home from school; upstairs becomes active living area |

### Weekends (Saturday–Sunday)

| Time     | Mode        | Reason              |
|----------|-------------|---------------------|
| 12:00 am | Comfort Heat | Home all day        |

---

## Comfort setpoints

Temperatures in °F. Minimum 5°F spread required between heat and cool.

### Downstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 70   | 65   | Primary daytime/occupied temp          |
| Comfort Heat | 73   | 70   | Active when outdoor temp < 60°F        |
| Sleep        | 74   | 61   | Nighttime                              |
| Away         | 82   | 64   | Energy saving when unoccupied          |
| Home         | 70   | 65   | System default, same as Comfort Cool   |

### Upstairs

| Comfort      | Cool | Heat | Notes                                  |
|--------------|------|------|----------------------------------------|
| Comfort Cool | 70   | 65   | Primary temp — same as sleep in practice |
| Comfort Heat | 75   | 45   | Active when outdoor temp < 60°F        |
| Sleep        | 71   | 66   | Same as Comfort Cool effectively       |
| Away         | 82   | 64   | Energy saving when unoccupied          |
| Home         | 75   | 62   | System default, not used in schedule   |
