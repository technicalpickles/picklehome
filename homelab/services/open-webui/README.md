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

## Web Search

Enabled, using Brave as the search engine. The Brave API key is entered
directly in Admin Settings → Web Search → Brave Search API Key, not via
`.env`/1Password — it isn't one of the ConfigVars this service seeds from
env (see `.env.vars`), so it only exists in the database.

**Enabling web search for chat is two separate settings, and both have to
be saved explicitly:**

1. Admin Settings → Web Search: turns the feature on globally and sets the
   engine/key. This is the one that's easy to find and easy to assume is
   enough.
2. Admin Panel → Models → **Settings** (the button next to Import/Export/
   Manage on the Models list, not a sidebar item) → **Defaults** tab →
   **Model Capabilities** accordion: a `Web Search` checkbox under
   "Capabilities" (can the model use it at all) and another under "Default
   Features" (is it on automatically for new chats, vs. requiring a
   per-chat toggle click).

The Capabilities/Default Features checkboxes render pre-checked by
default in the UI even when nothing has ever been saved — the form shows
sensible-looking defaults, not the actual persisted state. If nobody has
clicked Save on that modal, `models.default_metadata` in the database is
still `{}` and no model gets the capability, so the web search toggle
never shows up in chat even though global settings look fully configured.
This was the actual root cause the one time this bit us: everything in
Admin Settings → Web Search was correct, but that Models settings modal
had never been saved.

If web search is enabled and showing up in chat but errors when used,
check the actual HTTP response from the search engine before assuming
it's an Open WebUI config problem — a Brave API 422 with
`SUBSCRIPTION_TOKEN_INVALID` means the stored key is wrong/expired/for the
wrong Brave product, which is entirely on Brave's side to fix (regenerate
or re-paste the key from the [Brave Search API dashboard](https://api.search.brave.com/)).

### Inspecting config without re-deriving all this

`just open-webui-inspect-config [prefix]` dumps the `web.search.*`/
`web.loader.*`/`models.default_metadata` config keys plus any per-model
capability overrides, straight from the container's SQLite DB (secrets are
masked as set/unset). Useful background: the image has no `sqlite3` CLI,
so this pipes `inspect_config.py` over SSH into the container via
`docker exec -i ... python3 -`. Also useful background: as of v0.10.2, the
`config` table is `(key, value, updated_at)` per-row, not the single JSON
blob older Open WebUI versions used (there's a leftover `config_old` table
from that migration).

## Open Terminal

[Open Terminal](https://docs.openwebui.com/features/open-terminal/) gives the
chat AI a sandboxed shell/file/package environment it drives via tool calls
— a second container (`open-terminal`, pinned
`ghcr.io/open-webui/open-terminal:0.11.34`) in this same Compose project,
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
