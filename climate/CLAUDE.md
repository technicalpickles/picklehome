# CLAUDE.md — climate/

See @README.md for full command reference, architecture, and module structure.

## Spec-first workflow

`spec/hvac-spec.md` is the source of truth for all thermostat behavior. Before touching any config or pushing to Ecobee:

1. **Read the spec first.** Understand the intent before looking at YAML values.
2. **If the desired behavior is changing**, update the spec first, then derive YAML changes.
3. **If only fixing a drift**, update YAML to match the spec.
4. **Validate** with `just climate-validate` to confirm the remote Ecobee matches.

Never change `schedule.yaml` or `comforts.yaml` without the spec as reference.

## Ecobee implementation notes

### Token management

`KeychainEcobee` subclass overrides `_write_config()` to persist tokens to Keychain on refresh. This means any API call that triggers a token refresh will automatically save the new tokens — no manual token management needed.

### Schedule YAML conventions

- All times must be on 30-minute boundaries (`:00` or `:30`)
- Every day must start with `time: "00:00"`
- All 7 days are required
- YAML anchors (`&name` / `*name`) are used for DRY day templates (`_everyday`, `_weekday`)
- Climate values must be `climateRef` strings from the thermostat (not display names)

### smart1 / smart2 swapping

`smart1` and `smart2` are custom Ecobee climates used for seasonal switching. The `comfort-switch` command swaps which one is active in the schedule. The spec defines the intent; the YAML defines the mapping.

### InvalidTokenError handling

The CLI catches `InvalidTokenError` from `pyecobee` — when this happens, the user needs to re-run `just climate-auth`. Don't try to auto-refresh within the CLI.
