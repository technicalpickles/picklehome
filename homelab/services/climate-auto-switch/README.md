# climate-auto-switch

Runs `climate comfort-switch auto` on a 15-minute systemd timer. Checks the outdoor
temperature and switches the Ecobee thermostats between Comfort Heat and Comfort Cool when
the configured threshold is crossed. No-op detection skips API writes when the mode hasn't
changed, so most runs are cheap reads.

The climate logic itself lives in [`climate/`](../../../climate/README.md); this service is
just the deployment wrapper that runs it on a schedule on picklelab.

## Architecture

- **Image:** built from the repo root via `Dockerfile`, baking the `climate` package and its
  uv-locked deps into a `python:3.12-slim` image. The entrypoint is
  `python -m climate.sync comfort-switch auto`.
- **Trigger:** `climate-auto-switch.timer` (`OnCalendar=*:0/15`, `Persistent=true`) fires the
  oneshot `climate-auto-switch.service`, which runs `op run -- docker compose run --rm` (see
  "Env vars" below for what `op run` resolves).
- **State:** mounted at `/data` in the container, backed by `/srv/data/climate-auto-switch` on
  the host:
  - `ecobee-tokens.json`: OAuth tokens (refreshed in place on each run)
  - last-run state + JSONL run log (one line per run: mode, temps, thermostats touched)
- **Backup:** the state dir is captured by the nightly [backup service](../backup/README.md).

## First-time setup (from Mac)

```bash
just seed-climate-tokens  # one-time: copy the local ecobee token file onto the host
just deploy-climate       # build image, install systemd units, enable timer
```

`just seed-climate-tokens` matters: the container can't run the interactive Ecobee PIN flow,
so it needs an already-authorized token file seeded from a machine where you've run
`just climate-auth`.

## Deploy updates

```bash
just deploy-climate       # rebuilds the image and restarts the timer
```

Secrets aren't scp'd anymore: `deploy.sh` regenerates a filtered, checked-in-safe
`.env.op.template` (bare `op://` references, never a resolved secret) from the repo's
`.env.template` on every deploy, and the systemd unit resolves it live via `op run` each time
it fires. A secret change in 1Password takes effect on the *next* timer run with no deploy
needed; run `just deploy-climate` only when `.env.vars` itself changes (a var added/removed).

## Monitoring

```bash
just climate-check        # last run state (mode, temps, thermostats)
just climate-log          # recent run log (JSONL, last 10 entries)
just climate-log lines=50 # more history

# Manual trigger and systemd logs
ssh picklelab "sudo systemctl start climate-auto-switch.service"
ssh picklelab "sudo journalctl -u climate-auto-switch.service -n 50"
```

## Env vars

Listed in `.env.vars`: `HOME_LAT`, `HOME_LON`, `AMBIENT_STATION_MACS`, `ECOBEE_API_KEY`,
`BLUEAIR_USERNAME`, `BLUEAIR_PASSWORD`, `BLUEAIR_REGION`, `GOOGLE_POLLEN_API_KEY`. Resolved
from 1Password at run time by `op run` (see `climate-auto-switch.service`'s `ExecStart`), not
from a `.env` file — `compose.yaml` declares each as `environment: ${VAR:?required}`, so a
missing value fails the run loudly instead of starting the container with an empty secret.
