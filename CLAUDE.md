# CLAUDE.md: picklehome

@README.md

The README is the reference: what's here, the integration and auth tables, repo layout, network topology, test commands. This file is only the stuff that changes how you work.

## Connectivity Troubleshooting

When a site or service is slow, timing out, or "broken" (especially Cloudflare-hosted ones: Canva, Claude.ai, Notion, Dropbox), the diagnostics live in `network/`. **Start with the browser profiler `just network-profile <url>`**, then drop to lower layers. See `network/CLAUDE.md` ("When a site or service is slow or broken") for the full top-down order. Past incidents are in `network/investigations/`.

Note: the browser profiler and `just bgw *` use a headless browser that can't launch in the sandbox; see the Sandbox section.

## Tailscale

- **Tailnet suffix:** `tail2023b7.ts.net` (verify with `tailscale status --json | jq -r '.CurrentTailnet.MagicDNSSuffix'`)
- **Service hostnames:** `<service-name>.tail2023b7.ts.net`, fronted by Tailscale Services on picklelab. TLS terminated by `tailscaled`, proxied to a `127.0.0.1:<port>` container binding. No public DNS, no Caddy.
- **Per-service hostname** is stored as `<SERVICE>_HOST` in 1Password (e.g. `op://picklehome/TaskChampion Sync/host`) and surfaced via `.env`.
- **Beach house node:** `seapickle` (Raspberry Pi 3B+) is the Tailscale node and subnet router at the beach house; see `homelab/seapickle/README.md`.
- **CLI mechanics** (status looks wrong, `ping` fails, sudo prompts hang, Services vs. node-serve, standing up a new Service): use the `tailscale-cli` skill (`tailscale` plugin) before re-deriving these from scratch.
- **Exposure architecture** (loopback-bind + `serve` vs. binding directly to the tailnet interface, identity-header auth, what's actually reachable): use the `tailscale-serve-patterns` skill.

## Python Tooling

[uv](https://github.com/astral-sh/uv) for deps (`pyproject.toml` / `uv.lock`, `uv sync` or `just install` once). Run things via `just` (preferred) or `uv run <script>`. One-off scripts with no project deps: `uv run --with <dep1>,<dep2> <script>`. `just --list` shows every recipe.

## Secrets

Two paths, and they don't share anything but `.env.template`:

- **Local Mac dev:** `just dotenv` runs `op inject` over `.env.template` to produce a gitignored `.env`. Scripts load it via `python-dotenv`, `just` loads it via `set dotenv-load`.
- **Deploys to picklelab:** no `.env`, no `just dotenv`. `just deploy-<service>` is one ssh call; the service's systemd unit wraps `docker compose` in `op run` against a read-only 1Password service-account token on the host (`/etc/opt/homelab/op-token-picklehome`). Resolved secrets never touch disk on either machine. `homelab/services/README.md` and `homelab/services/CLAUDE.md` own the details; read them before touching a `deploy.sh`, unit, or compose file.

**Adding a new secret (local dev):**
1. Add the value to 1Password (prefer the `picklehome` vault). Do this **before** step 3: `op inject` fails hard on a reference to a nonexistent item, and since the template is one shared file, that breaks `just dotenv` for every module.
2. Look up the exact field name: `op item get "Item Name" --vault picklehome --format json | jq '[.fields[] | {label, id}]'`
3. Add the `{{ op://picklehome/Item/field }}` reference to `.env.template`
4. Run `just dotenv` to regenerate `.env`
5. If a deployed service needs it too, add the var name to that service's `.env.vars` (the deploy side filters `.env.template` by that list)

**If `just dotenv` fails with missing keys:** keys present in the old `.env` are absent from the template. Add them to `.env.template` then re-run. To skip the check and reset from the template unconditionally, use `just dotenv --force`.

**If `just dotenv` fails with a 1Password error:** ensure you're signed in (`op whoami`). Field names in `op://` references must match exactly. Use the `jq` command above to verify.

The logic lives in `scripts/dotenv` (supports `--template`, `--output`, `--force`).

**Gotcha:** `op inject` scans the *entire* `.env.template`, comments included. Writing a bare `op:` + `//` secret-reference scheme in explanatory prose makes it parse that prose as a real reference and fail the whole run (`invalid secret reference ... too few '/'`). Describe references in words, never by writing the literal scheme in a comment.

**Gotcha:** 1Password field labels feeding `op inject` / `scripts/locations-filter.jq` must have no leading/trailing whitespace. A stray space (e.g. `" yale_houses"`) silently drops the field from the generated `.env` with no error, so a location value just quietly goes missing.

**Gotcha:** `set dotenv-load` in the Justfile walks up parent directories. A worktree created without its own `.env` still gets the main checkout's real `.env` for anything run through `just`, so "no `.env` here" does not mean "no live device access." Direct `uv run` invocations don't walk up, which is why a fresh worktree hits `ECOBEE_API_KEY not set` until you run `just dotenv` there (needs the sandbox off, see below). Tracked as taskwarrior `f6948c15` for whether to scope it down.

## Sandbox

Scripts run inside the Claude Code sandbox. Design code to work within it rather than bypassing it.

The sandbox enforces network access via a local HTTP proxy and `HTTP_PROXY`/`HTTPS_PROXY` env vars, not OS firewall rules. Tools that respect proxy env vars (`curl`, `requests`) work automatically. Tools that don't get `Operation not permitted` on `connect()` even if the domain is in `allowedDomains`.

- **Python `aiohttp`**: defaults to `trust_env=False`, so you must pass `trust_env=True` when creating a `ClientSession`, or pass a pre-configured session to libraries that create their own
- **New API integrations**: add the domain to `sandbox.network.allowedDomains` in `.claude/settings.json` (tracked, shared across checkouts), and verify the HTTP client respects the proxy. `.claude/settings.local.json` is gitignored and is for per-machine overrides only, so a domain added there is invisible to everyone else
- **`allowedDomains` applies next session**: a domain just added isn't active in the current session, so run same-session live API tests with the sandbox disabled until the next start
- **1Password (`op`) / `just dotenv`**: the `op` CLI reaches the desktop app over a socket the sandbox blocks (fails with `couldn't connect to the 1Password desktop app` or `account is not signed in`). Run anything backed by `op` (`op read`/`inject`/`item`, `just dotenv`) with the sandbox disabled
- **Keychain access**: requires `~/Library/Keychains/` in `sandbox.filesystem.allowWrite`
- **Headless browser (Playwright/Chromium)**: can't launch in the sandbox (fails with `bootstrap_check_in ... Permission denied`). Scripts that use it (`network/profile.py` / `just network-profile`, `network/bgw.py` / `just bgw *`) must run with the sandbox disabled.
- **curl timing inside the sandbox is meaningless**: requests route through the local proxy, so `time_connect`/`time_appconnect` measure the proxy, not the real path. Run timing probes with the sandbox disabled.
- **Debugging**: if `curl` works but Python doesn't, it's almost certainly a proxy issue, not a domain allowlist issue
- **`git push` to github.com over SSH** sometimes fails once with `Operation not permitted` (port 22) and then succeeds on an immediate retry. Retry once before diagnosing anything.
- **SSH to homelab hosts (e.g. `ssh picklelab`, `just disk-report`, `just deploy-*`)**: the sandbox blocks outbound port 22 directly; SSH from an agent session routes through a local SOCKS5 relay (`com.technicalpickles.agent-ssh-relay`, gost) that only allows destinations listed in `~/github.com/technicalpickles/dotfiles/config/gost/agent-ssh-relay.yml`. A host missing from that allowlist fails with `Ncat: Error: connection not allowed by ruleset.` (not a sandbox error, so `dangerouslyDisableSandbox` doesn't fix it). `picklelab` and `picklelab.tail2023b7.ts.net` are already allowlisted. To add another host: append `<host>:22` to the YAML's `matchers` list, then reload with `launchctl kickstart -k gui/$(id -u)/com.technicalpickles.agent-ssh-relay` (needs `dangerouslyDisableSandbox`, since `launchctl` itself is blocked). See `dotfiles/ssh/CLAUDE.md` for the full design.
- **`sudo` over a non-interactive `ssh host "sudo ..."` almost always needs a password on picklelab.** Only a narrow, specific allowlist runs passwordless (`sudo -n -l` on the host shows the live list; check it before assuming a command will work headlessly, rather than guessing from memory since it changes as new deploy needs come up). Anything outside that list fails immediately with `sudo: a terminal is required to read the password; ... sudo: a password is required`. No hang, no prompt, just a hard fail, because a plain `ssh host "cmd"` allocates no pty for `sudo` to prompt on. Two ways out: (a) prefer a passwordless-allowlisted command over the one you reached for first, e.g. `apt-get install <file>.deb` works where `dpkg -i <file>.deb` doesn't, since only the former is allowlisted; or (b) if a real interactive password entry is actually wanted (a human is at the keyboard, not an agent), add `-t` to the `ssh` call to allocate a pty so the prompt can render at all. `-t` doesn't make an agent's own sudo non-interactive, it just turns the instant hard-fail into an actual prompt for whoever is watching. The allowlist itself is `homelab/config/sudoers-deploy-ops`, installed by `homelab/scripts/setup-deploy-access.sh`; widening it is a sudoers change on a production host, so confirm with the user first rather than doing it silently to unblock a command.

## Homelab

Before changing anything under `homelab/`, read `homelab/services/CLAUDE.md`. The three things that bite agents who skip it:

- Deployed services get secrets from `op run` in their systemd unit, never from a `.env` file. Any doc, script, or compose `env_file:` that assumes otherwise is stale, not a pattern to copy.
- `just deploy-<service>` needs a clean `main` checkout that matches `origin/main`; it pushes and then runs one ssh command. There is no separate scp step.
- A `deploy.sh` can only `sudo` what the allowlist above permits.

## Backlog & Task Tracking

Top-level entry point: `task list project:picklehome`

Projects use a dotted hierarchy: `picklehome.climate.ecobee`, `picklehome.lighting.hue`, `picklehome.homelab.backup`. This lets `task list project:picklehome.climate` match all climate sub-projects.

When touching a module, check the relevant sub-project (e.g. `task list project:picklehome.climate` when working in `climate/`).

## Coding Conventions

- **Don't swallow errors in data-fetching code.** Raise with diagnostic context (what failed, why) and catch at the boundary where you can present it to the user. Returning `None` for every failure mode (network error, stale data, bad input) makes debugging impossible because the caller can't distinguish fixable problems from expected ones. Use `asyncio.gather(return_exceptions=True)` for concurrent fetches so one failure doesn't cancel the rest.
- **Never commit geolocatable identifiers.** Street addresses, coordinates, full MAC addresses and BSSIDs, device serials. Private LAN IPs and OUI prefixes are fine. `tests/test_no_sensitive_identifiers.py` enforces the MAC part; the rest is on you. Real values go in agent memory or 1Password (see `docs/CONVENTIONS.md`).

**When adding a new integration:**
1. Store credentials in 1Password (`picklehome` vault)
2. Add `op://` references to `.env.template`
3. Use `python-dotenv` to load at import time
4. If tokens need refresh, cache them in `~/.local/state/picklehome/<service>-tokens.json` (0600) and honor a `<SERVICE>_TOKEN_PATH` override
5. Model the CLI on existing `*_cli.py` patterns (argparse + async dispatch), add a `just <module> *ARGS` passthrough recipe, and a row in the README's integration and auth tables

## Documentation

See @docs/CONVENTIONS.md for where information belongs (code comments vs README vs CLAUDE.md).

- Code comments: *why* the code works this way
- README.md: setup, commands, API reference, findings, for everyone
- CLAUDE.md: workflow/process guidance for agent context; each one starts with `@README.md` rather than repeating it
- docs/plans/ and docs/superpowers/plans/: point-in-time design documents. A "Status:" header or a checkbox list in one is a snapshot from when it was written, not a claim about today; check the code and `git log` before trusting either.
- `.parkinglot/`: gitignored session handoffs (park/unpark); not documentation
