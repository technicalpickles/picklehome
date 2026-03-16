# CLAUDE.md — picklehome

## Network Topology

```
Client → USG (192.168.1.1) → AT&T BGW (192.168.8.254) → AT&T Fiber → Internet
```

- **LAN:** `192.168.1.x`, gateway USG at `192.168.1.1`
- **AT&T BGW (fiber gateway):** `192.168.8.254` — admin UI at `http://192.168.8.254`
- **ISP:** AT&T Fiber, AS7018, southeastern US (Atlanta area)
- **Double-NAT:** BGW is NOT in IP passthrough mode; USG gets a private WAN IP

## Python Tooling

This repo uses [uv](https://github.com/astral-sh/uv) for Python dependency management.

- Run scripts with `uv run --with <deps> <script>`
- Project deps defined in `pyproject.toml` / `uv.lock`
- Install project deps once: `uv sync`

## Task Runner

Common workflows are defined in `Justfile` and run with `just <task>`. See `just --list` for all available tasks.

## Directories

- `ecobee/` — Ecobee thermostat automation (schedule + comfort setpoints)
- `network/` — Network diagnostic and profiling scripts; see `network/CLAUDE.md`
