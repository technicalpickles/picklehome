# Climate Auto-Switch: Docker-based Deployment

## Goal

Run the climate comfort-switch timer on picklelab as a Docker container instead of bare `uv run`. Bake the code and dependencies into an image for isolation and reproducibility. Support local testing on macOS.

## Architecture

### Image

- Dockerfile lives in `homelab/services/climate-auto-switch/`
- Build context is the repo root (so it can COPY project files)
- Based on a multi-arch Python base image (arm64 + amd64)
- Installs uv, COPYs `pyproject.toml`, `uv.lock`, and `climate/` package
- Runs `uv sync` at build time to bake in dependencies
- Entrypoint runs `python -m climate.sync comfort-switch auto --clear-holds`

### Compose

- `compose.yaml` in the service directory with defaults for local/Mac testing
- `compose.picklelab.yaml` override with picklelab-specific paths
- Systemd unit uses both: `docker compose -f compose.yaml -f compose.picklelab.yaml run --rm climate-auto-switch`

### Secrets and state

- `env_file:` loads `/opt/homelab/.env` (picklelab) or repo-relative `.env` (local)
- Ecobee token file bind-mounted from `/srv/data/climate-auto-switch/` (picklelab) or a local path
- New `ECOBEE_TOKEN_PATH` env var in `climate/ecobee/auth.py` overrides the default `~/.local/state/picklehome/ecobee-tokens.json`

### Systemd

- Timer unchanged (every 6 hours, persistent, randomized delay)
- Service unit updated to `docker compose run --rm` instead of calling `run.sh`
- `run.sh` removed

### Logging

- Container stdout/stderr captured by journald through the systemd unit
- `--rm` removes the container after each run; journal is the log of record

### Deploy

- `just deploy-climate` task: SSHes to picklelab, runs `git pull` + `docker compose build`
- Manual, intentional deploys

## Code changes

1. **`climate/ecobee/auth.py`**: read `ECOBEE_TOKEN_PATH` env var, use as default when set
2. **`homelab/services/climate-auto-switch/Dockerfile`**: new, slim Python image with deps
3. **`homelab/services/climate-auto-switch/compose.yaml`**: new, local/Mac defaults
4. **`homelab/services/climate-auto-switch/compose.picklelab.yaml`**: new, picklelab paths
5. **`homelab/services/climate-auto-switch/climate-auto-switch.service`**: update ExecStart to docker compose
6. **`homelab/services/climate-auto-switch/run.sh`**: remove
7. **`Justfile`**: add `deploy-climate` task

## Testing

- Build and run the image locally on macOS with `docker compose run --rm climate-auto-switch`
- Verify token refresh writes back through the bind mount
- Verify env vars are loaded correctly

## Follow-ups (not in scope)

- Failure alerting/notifications (dead man's switch or OnFailure= unit)
- Dependency groups in `pyproject.toml` to slim down the climate-only install
