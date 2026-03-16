# picklehome

Home automation and infrastructure tooling for a residential AT&T Fiber setup with a UniFi Security Gateway (USG).

## Directories

- **`ecobee/`** — Ecobee thermostat schedule and comfort management. Syncs `schedule.yaml` and `comforts.yaml` to the Ecobee API.
- **`network/`** — Network diagnostic tooling. Scripts for profiling site performance, running diagnostics from the AT&T BGW gateway, and capturing mtr results.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) — Python dependency management
- [just](https://github.com/casey/just) — task runner

```bash
just install
```

## Common Tasks

```bash
# Ecobee
just ecobee-sync          # push schedule.yaml to Ecobee
just ecobee-validate      # verify live schedule matches schedule.yaml
just ecobee-comforts-sync # push comforts.yaml setpoints

# Network
uv run --with requests --with playwright network/bgw.py fiber
uv run --with requests --with playwright network/bgw.py trace 104.16.99.29
```
