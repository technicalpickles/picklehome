# Skylight Calendar 2 API spike

Spike into automation/API options for the newly-added Skylight Calendar 2 frame. Research +
live poke against the real account, done on branch `explore-skylight-api`. Nothing built yet.

## TL;DR

- **No official API.** Skylight has no public developer program. Everything below talks to the
  private app backend (`app.ourskylight.com`) that the iOS/Android/web app itself uses.
- The community has thoroughly reverse-engineered it. **`pyskylight`** (`mcarmody/pyskylight` on
  GitHub, not yet on PyPI) is the pick: a Python client + Typer CLI with ~150 methods, ships an
  OAuth2 + PKCE flow with the client_id/redirect_uri/scope already baked into `constants.py`, so
  there's no separate reverse-engineering step to redo ourselves.
- Confirmed live against the real account: login, frame/device read, calendar event read, and
  device settings **read + write** (sleep schedule) all work today.
- **Sensitivity:** the API returns real geolocatable data by default — the frame's
  `household_name` is a street address, and calendar event `location` fields are addresses pulled
  in from synced Google Calendars. Per this repo's rule (`docs/CONVENTIONS.md`), none of that can
  land in a tracked file, README example, or committed fixture. Keep raw API dumps out of git.

## Other options considered

| Option | What it is | Verdict |
|--------|-----------|---------|
| **pyskylight** | Unofficial Python client + Typer CLI, OAuth2+PKCE baked in, ~150 methods | **Chosen** for any future module — most complete, matches this repo's Python-first tooling |
| [skylight-api](https://github.com/TheEagleByte/skylight-api) | Unofficial OpenAPI 3.0.3 spec reverse-engineered from HAR captures, 38 endpoints documented, Swagger/ReDoc generator | Good as a reference doc / endpoint catalog, not something to build on directly |
| skylight-mcp (multiple: `ryancollier`, `rjhalvorson`, `eaglebyte`) | MCP servers wrapping the same private API for AI-assistant use | Skip for a scripted module; worth revisiting if we ever want Claude driving Skylight directly instead of via `just` commands |
| Home Assistant integrations (`dknowles2/ha-skylight`, `MegaTheLEGEND/skylight_calendar`) | Custom HA components, one uses proper OAuth2+PKCE now | Not applicable — no local Home Assistant instance in this house |

## Auth

OAuth2 Authorization-Code + PKCE against `app.ourskylight.com`:

1. `GET /oauth/authorize` — login form + CSRF token
2. `POST /auth/session` — submit email/password
3. `POST /oauth/token` — exchange code for `access_token` + `refresh_token`

`pyskylight` handles all three steps; from the outside it's just:

```bash
export SKYLIGHT_EMAIL=... SKYLIGHT_PASSWORD=...
skylight login   # caches token, prints subscription status
```

The older plain `POST /api/sessions` email/password endpoint is version-gated and effectively
retired — OAuth+PKCE is required now, not optional.

`pyskylight` caches the token at `${XDG_CACHE_HOME:-~/.cache}/pyskylight/token.json` (mode 0600).
That's a different location than this repo's usual `~/.local/state/picklehome/<service>-tokens.json`
convention — if we vendor a module around this, decide whether to point `pyskylight` at our own
path or just let it use its own cache dir. Fits the existing **"Username/password to session
token"** row of the README's auth table either way.

## Setup notes for next time

- `app.ourskylight.com` is **not yet** in `sandbox.network.allowedDomains` — needs adding to
  `.claude/settings.json` before an agent session can reach it without disabling the sandbox.
- 1Password CLI (`op`) could not be driven non-interactively from an agent session on this
  machine: it needs desktop-app Touch ID/approval per new process, which only an interactive
  terminal can answer. Worked around it with the repo's own escape hatch,
  `just secret-entry SKYLIGHT_EMAIL SKYLIGHT_PASSWORD` (`scripts/secret_entry.py`) — serves a
  one-time tailnet-only form, Josh filled it in from his phone, values landed straight in `.env`.
- Installed `pyskylight` as scratch tooling only: `uv run --with 'git+https://github.com/mcarmody/pyskylight' skylight <command>`. Not added as a project dependency.

## Confirmed against the account, 2026-09-27

- **Frame:** id `5810720`, one frame on the account, `apps: ["calendar"]`, Plus trial active
  (`bundle_name: cal_plus`) until 2027-03-26.
- **Device:** id `6188024`, name "Calendar". Settings surface: `brightness`, `slideshow_speed`,
  `slideshow_style`, `sleeps_at`/`wakes_at`, `sleep_mode` (`screen_off`), `nightlight` +
  `nightlight_brightness` + `nightlight_color`, `show_caption`, `show_heart`, `blur_effect`.
- **Categories:** family-member/color categories already populated from synced Google
  calendars — family members, school PTA calendars, a "Birthdays" category, etc.
- **Connected calendars:** two Gmail accounts synced in, several sub-calendars each (`owner`,
  `editable: true` on all of them — so event writes should work, not just reads).
- **Events:** `GET events --from --to --tz --frame` returned 13 real upcoming events for the next
  7 days, pulled from the synced Google calendars (school pickups, activities, bills, etc.),
  including address-shaped `location` values.
- **Chores/lists:** none configured yet on this account (empty response, not an API limitation —
  the `chores` endpoint 422s if `--after`/`--before` are both blank, that's undocumented but
  confirmed).
- **Sleep schedule read/write confirmed round-trip:** `device-update 6188024 --sleeps-at HH:MM
  --wakes-at HH:MM` PATCHes successfully; re-fetching the device fresh (not just trusting the
  PATCH response echo) showed the change persisted server-side. Currently set to **sleep 23:00,
  wake 06:00** (a real, wanted value, not a throwaway test — no need to revert).

## CLI surface (via `pyskylight`'s Typer app, ~85+ commands)

Rough clusters, for scoping future module work:

- **Device/frame control** — brightness, sleep schedule, nightlight, slideshow, rename, timezone,
  privacy. The one that overlaps with this repo's existing lighting/climate automation pattern.
- **Calendar** — events (CRUD + search), countdowns, connected-calendar management, webcal
  subscriptions, event notification settings.
- **Chores/routines/rewards** — full CRUD, point balances, redemption.
- **Meals** — recipes, meal planning ("sittings"), grocery-list integration.
- **Lists** — shopping/to-do lists and items, sections, reordering.
- **Household** — members, family-member profiles/categories, household config.
- **Photos/messages/albums** — upload, captions, likes, comments, month-in-review.
- **AI intents (Sidekick)** — create calendar items from a natural-language prompt server-side.

## Open questions / next steps

- No documented rate limits anywhere in the ecosystem — worth polling conservatively if a
  scheduled sync job gets built (cf. the LG ThinQ research: reverse-engineered APIs have
  sometimes retaliated against aggressive polling on *other* vendors).
- Decide build-vs-depend: wrap `pyskylight` directly (fast, but we inherit its unofficial-API
  breakage risk) vs. hand-roll a thin client against the `skylight-api` OpenAPI spec (more
  control, more maintenance).
- If we build a real `calendar/skylight/` (or similar) module, it should follow the existing
  per-module pattern: README + `just skylight *` + credentials in 1Password + token cache under
  `~/.local/state/picklehome/`.
- Concrete automation idea from this spike: sync the frame's sleep/wake schedule with the house's
  existing bedtime-adjacent automations (lighting) instead of managing it by hand in the app.
