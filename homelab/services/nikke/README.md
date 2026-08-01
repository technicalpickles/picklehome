# Nikke

Roster dashboard for NIKKE, backed by a SQLite store synced from blablalink.com.
Reachable at `https://nikke.tail2023b7.ts.net`.

## Shape

One image (`nikke:local`, built from `/opt/nikke-roster-scanner`) backing two
Compose services:

| Service | Lifetime | What |
|---------|----------|------|
| `serve` | long-lived, `restart: unless-stopped` | FastAPI dashboard on `127.0.0.1:8770` |
| `sync`  | `run --rm` from a timer | `nikke-scan blablalink sync --headless`, every 6h |

TLS is a Tailscale Service (`svc:nikke`) terminating on the host and proxying to
the loopback binding. No reverse proxy container.

## Data

`/srv/data/nikke/` (uid 1000), holding `roster.db` and `.blablalink-session.json`.
Covered by the nightly restic backup with no registration, since `backup.sh`
snapshots all of `/srv/data`.

## When the roster goes stale

The dashboard shows a staleness banner when the last successful sync is old, or
when the most recent attempt failed with `auth_expired`. Blablalink sessions
expire and re-login needs a real browser, which picklelab doesn't have, so:

```sh
just nikke-login
```

That opens a browser on your Mac, uploads the refreshed session, and runs a
sync to confirm it took.

## Operating

```sh
just deploy-nikke        # full deploy (pull, build, restart, health check)
just nikke-logs          # recent container logs
just nikke-logs-follow   # live logs
just nikke-sync-now      # run a sync instead of waiting for the timer
```

Sync history lives in the `sync_attempts` table:

```sh
ssh picklelab "sudo sqlite3 /srv/data/nikke/roster.db \
  'select started_at, status, error_category, character_count from sync_attempts order by started_at desc limit 10;'"
```

## Gotchas

- **`--db /data/roster.db` is passed explicitly** in both Compose commands. The
  CLI defaults to a cwd-relative `roster.db` with no env-var override, so
  dropping the flag silently writes into the container.
- **`nikke.service` runs `up -d --build serve`**, naming the service. A bare
  `up -d` would also start `sync`, firing a full blablalink sync on every deploy
  and every boot.
- **Chromium lives at `/ms-playwright`**, not in the build user's home, so uid
  1000 can read it. Changing the Dockerfile's `USER` without keeping
  `PLAYWRIGHT_BROWSERS_PATH` breaks sync but not serve, so it fails 6 hours
  later rather than at deploy.
- **First deploy needs the Tailscale Service approved** at
  `login.tailscale.com/admin/services`, and then re-advertised by hand.
  `deploy.sh` prints the exact commands when its tailnet check fails.
