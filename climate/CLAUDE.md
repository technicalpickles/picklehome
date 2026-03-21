# CLAUDE.md — climate/

See @README.md for command reference, architecture, and module structure.

## Spec-first workflow

`spec/hvac-spec.md` is the source of truth for all thermostat behavior. Before touching any config or pushing to Ecobee:

1. **Read the spec first.** Understand the intent before looking at YAML values.
2. **If the desired behavior is changing**, update the spec first, then derive YAML changes.
3. **If only fixing a drift**, update YAML to match the spec.
4. **Validate** with `just climate-validate` to confirm the remote Ecobee matches.

Never change `schedule.yaml` or `comforts.yaml` without the spec as reference.
