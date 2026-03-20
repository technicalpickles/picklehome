# CLAUDE.md — climate/

## Spec-first workflow

`climate/spec/hvac-spec.md` is the source of truth for all thermostat behavior. Before touching any config or pushing to Ecobee:

1. **Read the spec first.** Understand the intent before looking at YAML values.
2. **If the desired behavior is changing**, update the spec first to reflect the new intent, then derive the YAML changes from it.
3. **If only fixing a drift** (YAML diverged from spec without intent changing), update YAML to match the spec.
4. **Apply** changes to `climate/config/schedule.yaml` and/or `climate/config/comforts.yaml`.
5. **Validate** with `just climate-validate` to confirm the remote Ecobee matches.

Never change `schedule.yaml` or `comforts.yaml` without the spec as the reference — the spec exists precisely to avoid values drifting in ways that feel wrong at 2am.

## Key design principle

The goal is always ~70°F in any actively occupied space. The heat/cool setpoint split is a thermostat constraint, not a different intent — Comfort Heat and Comfort Cool both target 70°F, just from opposite sides depending on season.

## Tooling

- `just climate-comforts-sync-dry` — preview what would be pushed for comfort setpoints
- `just climate-comforts-sync` — push `comforts.yaml` to Ecobee
- `just climate-sync-dry` — preview schedule changes
- `just climate-sync` — push `schedule.yaml` to Ecobee
- `just climate-validate` — confirm remote schedule matches local
- `just climate-status` — show live thermostat state
