# 4. keep-climate-auto-switch-paused-to-collect-data

Date: 2026-11-10

## Status

Accepted. Supersedes [ADR 0001](0001-pause-climate-auto-switch-timer.md). Temporary: revisit by 2026-12-01 (taskwarrior `d24bb464`, project `picklehome.climate.ecobee`).

## Context

ADR 0001 paused the `climate-auto-switch` timer on 2026-10-18 so Comfort could be tuned by hand, and set a revisit date of 2026-10-25. That date passed with the timer still paused, on purpose.

Since then:

- The first cold stretch arrived (2026-11-07). Downstairs Comfort Heat went from 75/70 to 77/72 by hand and PR #188. Downstairs control averages Josh Office and Tracy Office, and the two rooms run about 10°F apart, so the cold is a sensor and setpoint problem, not a mode problem.
- `just climate-replay-band` (PR #190) replayed the 60/65 band against 8 months of runtime history. Findings are in [docs/research/comfort-switch-band/findings.md](../research/comfort-switch-band/findings.md). The band sits on the real heating/cooling crossover, and every band tried agrees with the equipment 90-96% of the time.
- The mode is Comfort Heat now and the 24-hour mean is about 56°F, so the replay says the timer would leave it on heat. Re-enabling today would change nothing.
- More history is still being gathered: how the new Comfort Heat floor behaves, and whether downstairs Sleep (`76867cf5`) or upstairs (`d0c60f28`) need to move.

## Decision

1. Keep the timer paused. `TIMER_PAUSED=1` in `homelab/services/climate-auto-switch/deploy.sh` stays, and the resume steps in ADR 0001 ("Resuming") still apply unchanged.
2. Keep the 60/65 band. 58/67 is the only change the replay supports (12 flips instead of 16 over eight months) and is not worth a spec change by itself.
3. Revisit by 2026-12-01, or earlier on a warm spell that pushes the 24-hour mean above 65°F, since that is the first time the timer would change the mode.
4. Do the Bugsink wiring (`c1a96de2`) before or with the re-enable, so Ecobee OAuth expiry shows up as one counted issue and not a silent failure every 15 minutes.

## Alternatives considered

- **Re-enable now**: safe, since the mode would not change, but it adds a writer to the thermostats while setpoints are still being tuned by hand, which is the thing ADR 0001 paused to avoid.
- **Retune to 58/67 first**: saves about four flips in eight months at the same accuracy. Not enough to hold the re-enable for.
- **Require two mornings before flipping**: accuracy dropped to 90% and flips only fell to 12.

## Consequences

### Positive

- Manual holds and tuning keep sticking while the new Comfort Heat floor is observed.
- The pause now has a stated reason, an exit trigger, and a prerequisite, instead of an overdue reminder.

### Negative

- Until the timer is back, nothing flips the mode. A warm spell in a heating season would leave the house on Comfort Heat by hand until someone notices.
- The pause still lives in a script constant. The mitigation is the taskwarrior reminder, now due 2026-12-01.
