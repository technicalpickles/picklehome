# Comfort switch band: what 8 months of history says

Date: 2026-11-10

Question: is the 60/65 band on the 24-hour mean outdoor temperature (`climate/config/weather.yaml`) the right rule for flipping Comfort Heat and Comfort Cool, and what should change before the paused timer comes back ([ADR 0004](../../adr/0004-keep-climate-auto-switch-paused-to-collect-data.md))?

Data: Ecobee runtime history for both thermostats, 2026-03-11 to 2026-11-10 (238 days, 5-minute rows with outdoor temperature and cool/heat/aux/fan runtime). Pulled with `just climate-history --equipment`; replayed with `just climate-replay-band`.

## Where the crossover is

Days binned by daily mean outdoor temperature, minutes per day of running (downstairs):

| Daily mean | Days | Cooling | Heating (heat + aux) |
|------------|------|---------|----------------------|
| 56-59°F | 21 | 2 min | 93 min (18 days) |
| 60-63°F | 16 | 24 min (4 days) | 40 min (8 days) |
| 64-67°F | 27 | 98 min (17 days) | 12 min (6 days) |
| 68-71°F | 37 | 228 min (35 days) | 14 min (6 days) |

Heating dominates up to about 59°F, cooling from about 64°F, and 60-63°F is genuinely mixed. 60/65 sits on that crossover. All heating is reported as `auxHeat1` (the `heat` column is 0 on every day), which is consistent with a furnace on the W1 stage, but the equipment type is not confirmed.

## How much the band matters

Each morning's decision from `comfort_mode.decide_mode`, scored against which direction the equipment ran more that day (226 days with at least 60 minutes of demand: 36 heat, 190 cool; always-cool scores 190):

| Band | Window | Flips | Agreement |
|------|--------|-------|-----------|
| 60/65 | 24h | 16 | 212/224 (95%) |
| 58/67 | 24h | 12 | 213/224 (95%) |
| 62/64 | 24h | 18 | 214/224 (96%) |
| 60/65 | 72h | 10 | 204/224 (91%) |
| 58/67 | 72h | 4 | 207/224 (92%) |

Every band tried lands between 90% and 96%, and the gaps are one to four days out of 224. Accuracy does not separate the bands. Flips do. 60/65 flipped 11 times between 2026-03-22 and 2026-05-06 and four times between 2026-10-31 and 2026-11-08, when daily means sat at 62-66°F. Requiring two mornings in a row before flipping cut accuracy to 90% and flips only to 12.

## Caveats

- The labels come from what ran, which depends on the mode and any holds active at the time. They rank bands, they do not prove one right.
- History before 2026-09-10 ran under the older live-reading rule, so it is not a clean test of the 24-hour-mean rule.
- Nothing here measures how the house felt. A proxy would be counting manual holds from the run log on picklelab, which has not been pulled.
- The 7am mean blends 17 hours of yesterday with 7 of today, so a switch lags the weather by about a day.

## Conclusion

Keep 60/65. 58/67 is the only change the data supports, and it saves about four flips over eight months. A wrong-mode day costs a couple of degrees, since both modes carry a heat and a cool setpoint, and a flip costs one schedule push.
