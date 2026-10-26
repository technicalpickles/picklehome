# CLAUDE.md: picklehome

@README.md

The README is the reference: what's here, the integration and auth tables, repo layout, network topology, test commands. This file is only the stuff that changes how you work.

## Connectivity Troubleshooting

When a site or service is slow, timing out, or "broken" (especially Cloudflare-hosted ones: Canva, Claude.ai, Notion, Dropbox), the diagnostics live in `network/`. **Start with the browser profiler `just network-profile <url>`**, then drop to lower layers. See `network/CLAUDE.md` ("When a site or service is slow or broken") for the full top-down order. Past incidents are in `network/investigations/`.

## Tailscale

- **Tailnet suffix:** `tail2023b7.ts.net` (verify with `tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix'`)
- **Service hostnames:** `<service-name>.tail2023b7.ts.net`, fronted by Tailscale Services on picklelab. TLS terminated by `tailscaled`, proxied to a `127.0.0.1:<port>` container binding. No public DNS, no Caddy.
- **Per-service hostname** is stored as `<SERVICE>_HOST` in 1Password (e.g. `op://picklehome/TaskChampion Sync/host`) and surfaced via `.env`.
- **Beach house node:** `seapickle` (Raspberry Pi 3B+) is the Tailscale node and subnet router at the beach house; see `homelab/seapickle/README.md`.

## Python Tooling

Run things via `just` (preferred; `just --list`) or `uv run <script>`. One-off scripts with no project deps: `uv run --with <dep1>,<dep2> <script>`.

## Secrets

The README's Secrets section explains the two paths (local `.env` via `just dotenv`, deploys via `op run` in the systemd unit); they share nothing but `.env.template`. On the host the unit reads a read-only 1Password service-account token at `/etc/opt/homelab/op-token-picklehome`. `homelab/services/README.md` and `homelab/services/CLAUDE.md` own the deploy side; read them before touching a `deploy.sh`, unit, or compose file.

**Adding a new secret (local dev):**
1. Add the value to 1Password (prefer the `picklehome` vault). Do this **before** step 3: `op inject` fails hard on a reference to a nonexistent item, and since the template is one shared file, that breaks `just dotenv` for every module.
2. Look up the exact field name: `op item get "Item Name" --vault picklehome --format json | jq '[.fields[] | {label, id}]'`
3. Add the `{{ op://picklehome/Item/field }}` reference to `.env.template`
4. Run `just dotenv` to regenerate `.env`
5. If a deployed service needs it too, add the var name to that service's `.env.vars` (the deploy side filters `.env.template` by that list)

**Gotcha:** `op inject` scans the *entire* `.env.template`, comments included. Writing a bare `op:` + `//` secret-reference scheme in explanatory prose makes it parse that prose as a real reference and fail the whole run (`invalid secret reference ... too few '/'`). Describe references in words, never by writing the literal scheme in a comment.

**Gotcha:** 1Password field labels feeding `op inject` / `scripts/locations-filter.jq` must have no leading/trailing whitespace. A stray space (e.g. `" yale_houses"`) silently drops the field from the generated `.env` with no error, so a location value just quietly goes missing.

**Gotcha:** `set dotenv-load` in the Justfile walks up parent directories. A worktree created without its own `.env` still gets the main checkout's real `.env` for anything run through `just`, so "no `.env` here" does not mean "no live device access." Direct `uv run` invocations don't walk up, which is why a fresh worktree hits `ECOBEE_API_KEY not set` until you run `just dotenv` there (needs the sandbox off, see below). Tracked as taskwarrior `f6948c15` for whether to scope it down.

## Sandbox

Scripts run inside the Claude Code sandbox. Design code to work within it rather than bypassing it.

The sandbox enforces network access via a local HTTP proxy and `HTTP_PROXY`/`HTTPS_PROXY` env vars, not OS firewall rules. Tools that respect proxy env vars (`curl`, `requests`) work automatically. Tools that don't get `Operation not permitted` on `connect()` even if the domain is in `allowedDomains`.

- **Python `aiohttp`**: defaults to `trust_env=False`, so you must pass `trust_env=True` when creating a `ClientSession`, or pass a pre-configured session to libraries that create their own
- **New API integrations**: add the domain to `sandbox.network.allowedDomains` in `.claude/settings.json` (tracked, shared across checkouts), and verify the HTTP client respects the proxy. `.claude/settings.local.json` is gitignored and is for per-machine overrides only, so a domain added there is invisible to everyone else
- **`allowedDomains` applies next session**: a domain just added isn't active in the current session, so run same-session live API tests with the sandbox disabled until the next start
- **1Password (`op`) / `just dotenv`**: the `op` CLI reaches the desktop app over a socket the sandbox blocks (fails with `couldn't connect to the 1Password desktop app` or `account is not signed in`). Run anything backed by `op` (`op read`/`inject`/`item`, `just dotenv`; needs Josh at the laptop to approve, see "Reaching picklelab and 1Password" below) with the sandbox disabled
- **Keychain access**: requires `~/Library/Keychains/` in `sandbox.filesystem.allowWrite`
- **Headless browser (Playwright/Chromium)**: can't launch in the sandbox (fails with `bootstrap_check_in ... Permission denied`). Scripts that use it (`network/profile.py` / `just network-profile`, `network/bgw.py` / `just bgw *`) must run with the sandbox disabled.
- **curl timing inside the sandbox is meaningless**: requests route through the local proxy, so `time_connect`/`time_appconnect` measure the proxy, not the real path. Run timing probes with the sandbox disabled.
- **`git push` to github.com over SSH** sometimes fails once with `Operation not permitted` (port 22) and then succeeds on an immediate retry. Retry once before diagnosing anything.
- **SSH to homelab hosts (e.g. `ssh picklelab`, `just disk-report`, `just deploy-*`)**: the sandbox blocks outbound port 22 directly; SSH from an agent session routes through a local SOCKS5 relay (`com.technicalpickles.agent-ssh-relay`, gost) that only allows destinations in `~/github.com/technicalpickles/dotfiles/config/gost/agent-ssh-relay.yml`. A host missing from it fails with `Ncat: Error: connection not allowed by ruleset.` (not a sandbox error, so `dangerouslyDisableSandbox` doesn't fix it). `picklelab` and `picklelab.tail2023b7.ts.net` are already allowlisted. To add a host and reload the relay, see `dotfiles/ssh/CLAUDE.md`.
- **`sudo` over a non-interactive `ssh host "sudo ..."` almost always needs a password on picklelab.** Only a narrow allowlist runs passwordless (`sudo -n -l` on the host shows the live list; it changes as deploy needs come up, so check it rather than guessing). Anything else hard-fails at once with `sudo: a terminal is required to read the password`, because a plain `ssh host "cmd"` allocates no pty. Prefer an allowlisted command over the one you reached for first (`apt-get install <file>.deb` is allowlisted, `dpkg -i <file>.deb` is not). `ssh -t` only helps when a human is at the keyboard to type the password. The allowlist is `homelab/config/sudoers-deploy-ops`, installed by `homelab/scripts/setup-deploy-access.sh`; widening it is a sudoers change on a production host, so confirm with the user first.

## Reaching picklelab and 1Password from an agent session

**Don't assume picklelab (or a secret) is out of reach because 1Password is involved. Try it first.**

- **`ssh picklelab` works unattended.** automic-vault is live: `ssh -G picklelab` resolves `IdentityAgent` to `~/.local/share/automic-vault/ssh-agent.sock`, no 1Password prompt. That covers `just deploy-*` and `ssh picklelab docker exec ...`. For read-only probes use pickleclaw's `scripts/openclaw-ro/remote` (the planned `picklelab-ro` was never built). Old notes saying "ssh picklelab needs a 1Password approval, an agent can't run it" are stale; fix them when you find one.
- **`op` is the one that still touches 1Password.** The sandbox blocks its desktop-app socket, so run `op`-backed commands with the sandbox disabled. That is fine **when Josh is at the laptop** (he approves the prompt). If he isn't (phone-driven session), say what's blocked and ask; don't treat it as "can't be done". automic-vault is replacing the `op` path, which will allow approving from anywhere.
- **These are separate walls, unrelated to 1Password:** passwordless sudo is allowlist-only on picklelab (see Sandbox above), the auto-mode classifier denies free-form prod reads (taskwarrior `f54dd775`), and the relay host allowlist. `just deploy-*` is pre-authorized by a `permissions.allow` rule in `.claude/settings.json`, which only loads for sessions started in this repo; from anywhere else the home role's classifier rule (dotfiles `claude/roles/home.jsonc`) allows a deploy Josh asked for in his own message, and a PreToolUse hook there turns `deploy-openclaw` / `deploy-brineworks-server` into a prompt when Brent was active in the last 5 minutes (same check as `just openclaw-quiet`).

## Homelab

Before changing anything under `homelab/`, read `homelab/services/CLAUDE.md`. `just deploy-<service>` needs a clean `main` checkout that matches `origin/main`; it pushes and then runs one ssh command. There is no separate scp step. `just deploy-openclaw` and `just deploy-brineworks-server` refuse (exit 75) if Brent had a non-heartbeat session active in the last 5 minutes, since the restart kills an in-flight turn. Check first with `just openclaw-quiet`; override with `HOMELAB_DEPLOY_EVEN_IF_BUSY=1 just deploy-<service>` only when Josh says to (`docs/adr/0003-refuse-deploys-while-brent-is-active.md`). Deployed services get secrets from `op run` in their systemd unit, never from a `.env` file, so a doc or compose `env_file:` that assumes otherwise is stale.

## Backlog & Task Tracking

Entry point: `task list project:picklehome`. Projects use a dotted hierarchy (`picklehome.climate.ecobee`, `picklehome.lighting.hue`, `picklehome.homelab.backup`), so `project:picklehome.climate` matches all climate sub-projects.

## Coding Conventions

- **Don't swallow errors in data-fetching code.** Raise with diagnostic context (what failed, why) and catch at the boundary where you can present it to the user. Returning `None` for every failure mode (network error, stale data, bad input) makes debugging impossible because the caller can't distinguish fixable problems from expected ones. Use `asyncio.gather(return_exceptions=True)` for concurrent fetches so one failure doesn't cancel the rest.
- **Never commit geolocatable identifiers.** Street addresses, coordinates, full MAC addresses and BSSIDs, device serials. Private LAN IPs and OUI prefixes are fine. `tests/test_no_sensitive_identifiers.py` enforces the MAC part; the rest is on you. Real values go in agent memory or 1Password.

**When adding a new integration:** credentials and `.env.template` references follow "Adding a new secret" above, loaded with `python-dotenv` at import time. Then:
1. If tokens need refresh, cache them in `~/.local/state/picklehome/<service>-tokens.json` (0600) and honor a `<SERVICE>_TOKEN_PATH` override
2. Model the CLI on existing `*_cli.py` patterns (argparse + async dispatch), add a `just <module> *ARGS` passthrough recipe, and a row in the README's integration and auth tables

## Documentation

Before writing docs, read `docs/CONVENTIONS.md` (where a fact belongs: code comments, README, CLAUDE.md, taskwarrior, or agent memory). A module's CLAUDE.md starts with `@README.md` rather than repeating it.

- docs/plans/ and docs/superpowers/plans/: point-in-time design documents. A "Status:" header or a checkbox list in one is a snapshot from when it was written, not a claim about today; check the code and `git log` before trusting either.
- `.parkinglot/`: gitignored session handoffs (park/unpark); not documentation
