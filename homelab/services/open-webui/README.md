# open-webui

[Open WebUI](https://openwebui.com/) chat interface, backed by Ollama Cloud
(`https://ollama.com`, bearer `OLLAMA_API_KEY`, same key openclaw uses). No local
models, no GPU use on picklelab.

## Access

`https://openwebui.<tailnet>.ts.net` (Tailscale Services, `svc:openwebui`,
loopback port 8090). Login: single admin account, credentials in the
`Open WebUI` item in the `picklehome` vault. Signup is disabled.

## Deploy

    just dotenv
    just deploy-open-webui

First deploy needs the one-time Tailscale Service definition + approval; the
deploy script prints the exact steps if the tailnet health check fails.

## Config management (read before touching .env values)

Env vars marked as ConfigVars (the Ollama connection, signup toggle, etc.) seed
Open WebUI's database on FIRST BOOT ONLY. After that the admin UI owns them and
the env value is ignored. This is Open WebUI's default `ENABLE_PERSISTENT_CONFIG=true`
behavior; set it `false` in compose if env values should always win over the UI
(not done here -- see plan's Global Constraints for why). To rotate the Ollama
Cloud key or change connections: Admin Settings -> Connections in the UI.
`WEBUI_SECRET_KEY`, `WEBUI_ADMIN_EMAIL`/`WEBUI_ADMIN_PASSWORD` are read from env
at startup (the admin pair only acts on a fresh, user-less database).

## Open Terminal

[Open Terminal](https://docs.openwebui.com/features/open-terminal/) gives the
chat AI a sandboxed shell/file/package environment it drives via tool calls
— a second container (`open-terminal`, pinned
`ghcr.io/open-webui/open-terminal:v0.11.34`) in this same Compose project,
reachable from `open-webui` at `http://open-terminal:8000` (no host port, no
Tailscale Service — nothing outside this Compose project needs to reach it).

`TERMINAL_SERVER_CONNECTIONS` sets this connection as a `ConfigVar`, but that
only seeds a brand-new, user-less database — this instance's database already
existed when the env var was introduced, so it was silently ignored on deploy;
the connection was added by hand via Admin Settings → Integrations → Open
Terminal instead (same fields the env var would have set). See
`docs/plans/2026-07-21-open-terminal-design.md` (Decision 6) for the full story.
To use it in a chat: click the terminal button (cloud icon) in the input
area and select "Open Terminal" under System.

Its data lives in `/srv/data/open-terminal` (the container's `/home/user`)
and is deliberately **excluded from the nightly restic backup** — it's
disposable AI scratch space, not source-of-truth data. The image's `user`
account has passwordless sudo *inside its own container* (that's how it
installs packages on demand); the isolation boundary is the container, not
that account — no Docker socket is mounted, so it cannot reach picklelab's
host Docker daemon.

Full rationale: `docs/plans/2026-07-21-open-terminal-design.md`.

## Upgrades

Bump the pinned tag in the `FROM` line of `Dockerfile` (not `compose.yaml` --
the image is built locally, see "Non-root fix" below), commit,
`just deploy-open-webui`. Data (SQLite `webui.db`, uploads, embedding-model
cache) lives in `/srv/data/open-webui`, backed up nightly by the restic
`/srv/data` job.

## Non-root fix (custom Dockerfile)

The official image ships as root and its own Dockerfile says non-root is
untested. Confirmed on the pinned tag: running it as any non-root UID fails
~19 writes to `/app/backend/open_webui/static` on every boot (root:root,
0755/0644, no group write) -- cosmetic, but noisy and blocks static/branding
overrides. Tracked upstream: [open-webui/open-webui#26662](https://github.com/open-webui/open-webui/issues/26662),
fix PR [#26664](https://github.com/open-webui/open-webui/pull/26664) still
open. `Dockerfile` here wraps the pinned image and chowns that dir at build
time instead. `compose.yaml` points at `open-webui:local`; `compose.picklelab.yaml`
adds the `build:` stanza that produces it (same layering as
`second-brain-agent`/`brineworks-agent`), and `open-webui.service` runs
`docker compose up -d --build`, not `--pull always`.

Once the upstream fix ships and the pin is bumped past it: delete
`Dockerfile`, point `compose.yaml` back at `ghcr.io/open-webui/open-webui:<tag>`
directly, drop the `build:` stanza from `compose.picklelab.yaml`, and switch
`open-webui.service` back to `--pull always`.
