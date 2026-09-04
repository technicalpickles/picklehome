# Water: Moen Flo Smart Shutoff Valve

Read-only status for the Moen Flo smart water shutoff valve (`aioflo`). See
`docs/plans/2026-09-04-moen-flo-design.md` for the design this module implements.

## Setup

1. For now, type credentials straight into `.env` from a phone over the tailnet:
   `just secret-entry FLO_USERNAME FLO_PASSWORD`.
2. Later: create the `Moen Flo` item in the `picklehome` 1Password vault (username + password
   fields), un-comment the `FLO_USERNAME` / `FLO_PASSWORD` lines in `.env.template`, and run
   `just dotenv`. Until that item exists, `op inject` fails hard on a reference to a missing item,
   which would break `just dotenv` for the whole repo -- not just water -- so those lines stay
   commented out on purpose.
3. Check status: `just water status`

## Commands

```
just water status [--json]   # valve state, flow, pressure, temp, mode, wifi, alerts
just water device --raw      # unmassaged API JSON (user + locations + devices)
```

`device --raw` is the discovery dump from the initial build, kept permanently. It's the first
thing to reach for when Moen changes a field or adds a device to the account.

## Findings

### Auth flow: legacy `users/auth`, not SSO

**Determined empirically against the live account on 2026-09-04.** `aioflo` supports two auth
flows: Moen's SSO (Cognito) flow, which the current Smartwater app uses, and a legacy
`users/auth` flow. SSO **fails** on this account; the legacy flow **works**. `use_sso()`
(`water/flo/auth.py`) defaults to `False` accordingly. Set `FLO_USE_SSO=1` to opt back into SSO,
in case a different (e.g. newer) account needs it.

### Telemetry can be hours stale while the device reports connected

`telemetry.current.updated` is the timestamp of the *last telemetry reading*, not "now" --
confirmed on this account: `telemetry.current.updated` read `2026-09-04T11:57:00Z` while
`lastHeardFromTime` (the device's last check-in) read `2026-09-04T17:17:00Z`, over five hours
later. The device was connected and checking in; the flow/pressure numbers it was reporting were
still over five hours old. `just water status` prints this timestamp on the flow line (`as of
...`) specifically so stale numbers never look live.

### Mode lives on the device, not the location

The location payload's `systemMode` carries only `target` (what it's set to go to); the device's
`systemMode` carries both `target` and `lastKnown` (what it actually last reported). `parse_valve`
reads mode from the device for that reason -- it's the only field in the payload with an observed
value rather than just an intent.

### Valve state key is `valve.lastKnown`, not `valve.lastKnownState`

The valve object is `{"target": "open", "lastKnown": "open"}`. There is no `lastKnownState` key
anywhere in the payload.

### `notifications.pending.alarmCount` is a list, not a count

Every other `*Count` field under `notifications.pending` (`infoCount`, `warningCount`,
`criticalCount`) is an int, matching its name. `alarmCount` is a list (empty, `[]`, on this
account) despite the name implying a number. `parse_valve`'s alert-count sum filters to
`isinstance(v, int)` for exactly this reason -- a naive `sum(v for k, v in pending.items() if
k.endswith("Count"))` crashes the moment it hits `alarmCount`.

## Architecture

### Auth

Username/password to a session token (`water/flo/auth.py`), matching the "Username/password to
session token" row of the auth table in root `CLAUDE.md` -- except `aioflo` holds the token in
memory for the life of the process rather than caching it to disk, so there is no
`~/.local/state/picklehome/` token file here. A CLI invocation authenticates once and exits.

`aioflo` collapses every failure into a single untyped `RequestError`, unlike `thinqconnect`
(`lg/thinq/client.py`), which carries a vendor error code to classify on. The only honest signal
available is *when* the failure happened: `connect()` raising means the credentials or the auth
flow are wrong (`MoenFloAuthError`, pointing at both the 1Password item and `FLO_USE_SSO` as
things to check); anything later is an ordinary request failure (`MoenFloError`).

Named `MoenFlo*` rather than `Flo*` because `aioflo` already exports its own `FloError` base
class; sharing the prefix invites an import collision that reads as a subtle bug.

### Sandbox

`aioflo`'s fallback session doesn't honor `HTTP_PROXY`/`HTTPS_PROXY`, which breaks under the
Claude Code sandbox's proxy-based network allowlisting. `water/flo/auth.py` builds the session
itself with `trust_env=True` and passes it in, the same fix used by `lg/thinq/auth.py`,
`birdfeeder/vicohome`, and `climate/hisense`. The Moen Flo API domains are already in
`sandbox.network.allowedDomains` in `.claude/settings.json`.

### Read-only by design

Only `user.get_info`, `location.get_info`, and `device.get_info` are called. `aioflo` also
exposes `open_valve`, `close_valve`, `run_health_test`, and the home/away/sleep system-mode
setters -- none of them are called here, and none should be added without a deliberate decision.
This valve is the house water supply; a bug that closes it, or that runs a health test that
briefly stops flow, is a much worse failure mode than a stale status line.

`--json`/`--raw` output never masks a missing telemetry reading as `0`: `0.0 gpm` means "no water
moving", a missing reading means "no data", and the two are never rendered the same way (see root
`CLAUDE.md`, Coding Conventions).

## Module structure

```
water/
  water_cli.py       # CLI entry point (argparse): status | device
  flo/
    auth.py           # Env var credentials, sandbox-safe session factory, SSO/legacy toggle
    client.py         # The only module touching aioflo; FloValve dataclass + parser
```

## Non-goals (v1)

No write/control paths (open/close valve, health test, mode setters). No usage/consumption
history (`water.get_consumption_info`) -- worth revisiting if trends become interesting. No
away-mode automation -- revisit only if a concrete need appears.
