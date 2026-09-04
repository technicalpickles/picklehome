# Moen Flo water module design

Design for a `water/` module giving read-only status for the Moen Flo smart shutoff valve, plus a
`scripts/secret-entry` helper that unblocks credential entry from a phone while 1Password is
unreachable.

The valve is already physically installed and on the Moen account. Everything here is software.

## Goals

- `just water status` answers "is the water on, is anything leaking, what's the pressure" in one
  glance
- `just water device --raw` gives a permanent unmassaged API dump, the first thing to reach for
  when Moen changes a field
- Credentials can be entered from a phone, over the tailnet, without a desktop 1Password session
  and without the password appearing in a terminal, a log, or an agent transcript

## Non-goals for v1

- **Any write path.** No valve open/close, no system-mode changes (home/away/sleep). The valve is
  the house's water supply; a bug means no water. Control is a deliberate later decision, not an
  oversight.
- **Alerting.** The Moen app already does push notifications for leaks. A picklelab watcher
  duplicating that earns its place only if the app's notifications prove inadequate.
- **Usage history and trends.** `aioflo` exposes `water.get_consumption_info` and
  `water.get_metrics`; v1 does not call them. The `lg/`-style `observations.jsonl` pattern is the
  obvious v2 and nothing here forecloses it.
- **Location mapping.** One valve, one Flo location, main house. Wiring into
  `picklehome/locations.py` the way `locks/` and `nest/` do is premature until a second Flo
  location exists.
- **Smart Water Detector pucks.** None on the account. The `--raw` dump will show them if any get
  added later.

## Phase 0: `scripts/secret-entry`

### Why it exists

`op` cannot reach the 1Password desktop app from a phone-driven session, and the sandbox blocks the
socket regardless (see CLAUDE.md, Sandbox). The alternative is typing a password into an agent
transcript. This is a small, temporary bridge that avoids both.

It is generic in its interface because the situation will recur, and deliberately unambitious
otherwise: no 1Password write-back, no multi-file support, no persistence beyond the env file.

### Shape

A single-file stdlib-only Python script (`http.server`), no new dependencies. Invoked as
`just secret-entry FLO_USERNAME FLO_PASSWORD`.

1. Bind a plain-HTTP listener on `127.0.0.1:<random high port>`.
2. Run `tailscale serve --https=8443 http://127.0.0.1:<port>` and print
   `https://joshs-macbook-air.tail2023b7.ts.net:8443/<random-token>`.
3. Serve one form, a `type=password` field per requested var.
4. On POST: validate the token, upsert each `KEY=value` into the target env file preserving every
   other line, `chmod 600`.
5. Print a **masked** confirmation (`FLO_PASSWORD=•••••••• (14 chars)`), tear down the serve route,
   exit.
6. Self-destruct on a timeout if nobody submits.

### Why port 8443, not 443

`tailscale serve` on `joshs-macbook-air` is already occupied:

```
https://joshs-macbook-air.tail2023b7.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:52131
```

That route is in active use. `--https=8443` is a separate route that leaves it untouched. Do not
serve on a subpath of 443; a more-specific path would take precedence over `/` and risks disturbing
the existing proxy.

### Security posture

| Decision | Reason |
|---|---|
| Tailnet-only, **never Funnel** | Funnel would put a password form on the public internet |
| Random token in the URL path | Tailnet-only is not the same as you-only |
| One-shot, plus an idle timeout | Minimizes the window the form is reachable |
| Values never printed, logged, or echoed | This is the actual advantage over typing them at an agent |
| Plaintext lands in `.env` (gitignored) | Same exposure class as every other credential in this repo already; no new risk introduced |

### Interaction with `scripts/dotenv`

`scripts/dotenv` snapshots the keys in the existing `.env` and hard-errors if a regenerated `.env`
would drop any of them. So a later `just dotenv`, run before the 1Password item exists, fails with:

```
ERROR: these keys were in .env but are missing from the new one:
FLO_PASSWORD
FLO_USERNAME
```

This is the desired behavior: a loud reminder to create the vault item, not a silent credential
loss. No extra code needed.

### Risks, and what a live dry run settled

Serving this design doc to a phone via `crit` on 2026-09-04 exercised the exact mechanism Phase 0
needs, so two of these are now evidence rather than inference:

- **`tailscale serve --https=8443` works without `sudo`.** Confirmed. Operator permissions are set
  on this node.
- **8443 coexists cleanly with the existing `/` route on 443.** Confirmed: both appear in
  `tailscale serve status` and the 443 bridge route was undisturbed.
- **The tailnet path reaches a loopback listener end-to-end.** Confirmed by `curl` from picklelab
  (a *different* tailnet node -- self-curl from the serving host can hairpin-hang and gives false
  negatives): `HTTP 200`.
- **Still open: whether the sandbox permits binding a loopback listener.** The crit run died before
  binding, on a *filesystem* denial (`~/.crit/sessions/*.lock: operation not permitted`), so it
  never tested the network question. Assume `scripts/secret-entry` may need to run sandbox-off, as
  the `tailscale` calls must anyway.

### Environment gotchas

The Tailscale binary is **not on `$PATH`** (GUI app install). Use
`/Applications/Tailscale.app/Contents/MacOS/Tailscale`. The sandbox SIGTRAPs it (exit 133), so any
`tailscale` invocation runs with the sandbox disabled. See the `tailscale-cli` skill.

## Phase 1: the `water/` module

### Layout

`<domain>/<vendor>/`, matching `locks/yale/`, `garage/aladdin/`, `lg/thinq/`:

```
water/
  __init__.py
  water_cli.py      # argparse + async dispatch
  README.md
  flo/
    __init__.py
    auth.py         # env validation → authenticated aioflo API
    client.py       # domain dataclasses + typed errors
```

### Library choice: `aioflo`

`aioflo` (bachya) is the library Home Assistant's Flo integration is built on, and it is actively
maintained: `2026.9.3` shipped 2026-09-04, the third release that month, specifically covering
Moen's SSO migration. A hand-rolled client against `api-gw.meetflo.com` would mean owning exactly
that churn for no gain.

It accepts an injected `aiohttp.ClientSession`, so the sandbox's `trust_env=True` requirement is
satisfied cleanly, matching `locks/yale/`, `garage/aladdin/`, and `climate/hisense/`.

### Auth: which flow is an open empirical question

`aioflo` supports two flows:

- **Legacy** — `POST https://api.meetflo.com/api/v1/users/auth`, the library default
- **Moen SSO (Cognito)** — `use_sso=True`, what the current Moen Smartwater app uses

The library's own comment says legacy still works and SSO is opt-in cover for that endpoint being
retired. But this account is new, and a native Moen SSO account may never have had a legacy Flo
login to work with.

**Resolution: support both behind a `FLO_USE_SSO` env toggle, try SSO first against real
credentials, and let the result pick the default.** This is a fact to discover, not a design to
argue about.

### Endpoints used

Only reads:

- `user.get_info(include_location_info=True)` — discover the location and device ids
- `device.get_info(device_id)` — the live read: valve state, telemetry, connectivity, alerts
- `location.get_info(location_id)` — system mode (home/away/sleep)

### Commands

```
just water status                  # one-screen human summary
just water device --raw [--json]   # unmassaged API dump, kept permanently
```

`--raw` is kept forever for the same reason `just lg devices --raw` is: it is the discovery dump
and the first diagnostic when a field changes.

### Build order

`device --raw` is built **first** and run against real credentials, before `status` exists. Two
things are unknowable from the library source alone: which auth flow the account takes, and what the
device payload actually contains. `status` is then modeled on the captured payload rather than on a
guess at Flo's schema, and that same capture becomes the test fixture.

Expected shape of `status`, to be corrected against reality:

```
Flo — Main Shutoff              open
  flow        0.0 gpm
  pressure    62 psi
  temp        68 °F
  mode        home
  wifi        -54 dBm (connected)
  alerts      none
```

### Error handling

`aioflo` collapses every failure into a single `RequestError`; unlike `thinqconnect` it carries no
vendor error code to classify on. What is honestly available is *position in the call sequence*:

| Condition | Raised | Message content |
|---|---|---|
| `FLO_USERNAME`/`FLO_PASSWORD` missing or blank | `MoenFloConfigError` | Points at `just secret-entry` now, the `Moen Flo` 1Password item later |
| `RequestError` during `async_authenticate()` | `MoenFloAuthError` | Names both likely causes: bad password, or wrong auth flow — try flipping `FLO_USE_SSO` |
| `RequestError` after authentication | `MoenFloError` | Names which call failed |

**The `MoenFlo` prefix is deliberate, not verbosity.** `aioflo` already exports its own base
class named `FloError` (`aioflo/errors.py`). Naming ours `FloError` too would shadow it in any
module that imports both, which reads as a subtle bug rather than a naming choice.

All three are caught at `main()` in `water_cli.py`, printed as a clean message with a nonzero exit
and no traceback. Nothing returns `None` on failure (see CLAUDE.md, Coding Conventions).

### Testing

`tests/water/flo/`, mirroring source layout. Offline, mocked at the `aioflo` boundary (patch the API
object, not internal functions), consistent with the rest of the repo.

- `test_auth.py` — missing var, blank var, both present, `FLO_USE_SSO` parsing
- `test_client.py` — payload → dataclass off the captured `--raw` fixture, tolerance for absent
  optional fields, and the auth-time-vs-later error classification split
- `test_cli.py` — pure status formatting, no I/O

### Integration points

| File | Change |
|---|---|
| `pyproject.toml` | `aioflo>=2026.9.3` under a `# water` comment; `"water"` added to the hatch packages list |
| `Justfile` | `water *ARGS:` → `uv run python water/water_cli.py {{ARGS}}`; `secret-entry *ARGS:` |
| `.claude/settings.json` | `allowedDomains`: `api-gw.meetflo.com`, `api.meetflo.com`, `4j1gkf0vji.execute-api.us-east-2.amazonaws.com` |
| `.env.template` | `FLO_USERNAME` / `FLO_PASSWORD` refs, **commented out** (see below) |
| `CLAUDE.md` | `water/` in Directories; a Moen Flo row in the Integrations table |
| `water/README.md` | Setup, commands, auth-flow finding, device-payload findings |

### Why the `.env.template` refs start commented out

`op inject` fails hard on a reference to an item that does not exist. Adding live
`{{ op://picklehome/Moen Flo/... }}` refs before the vault item is created would break `just dotenv`
for the entire repo, not just for water. They go in commented out, with the README instructing that
they be un-commented once `Moen Flo` exists in the `picklehome` vault.

### Sandbox note

`allowedDomains` additions take effect the *next* session. Any same-session live API test against
Moen runs with the sandbox disabled.

## Follow-ups (Taskwarrior, project `picklehome.water`)

- Create the `Moen Flo` item in the `picklehome` 1Password vault, un-comment the `.env.template`
  refs, and re-run `just dotenv`
- Record which auth flow the account actually takes, in `water/README.md`
- Consider usage history via `water.get_consumption_info` if trends become interesting
- Revisit valve control and away-mode only if a concrete need appears
