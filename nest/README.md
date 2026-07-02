# Nest / Google Smart Device Management (SDM)

Nest thermostats and cameras across both properties, via Google's Smart
Device Management API. Covers thermostats and cameras only (not generic
Google Home speakers/Chromecast — SDM doesn't expose those).

## Setup

Nest's OAuth setup has more moving parts than the other integrations here
(Ecobee's PIN flow or Yale/BlueAir's username+password), because SDM requires
device sharing to be granted separately from the OAuth consent itself.

### 1. Google Cloud project + enable the API

1. [console.cloud.google.com](https://console.cloud.google.com) → create or reuse a project
2. APIs & Services → Library → enable **Smart Device Management API**

### 2. OAuth client credentials

1. APIs & Services → OAuth consent screen: configure it, add scope `https://www.googleapis.com/auth/sdm.service`
2. APIs & Services → Credentials → Create Credentials → **OAuth client ID**
3. Application type must be **Web application** (SDM specifically requires this, not "Desktop")
4. Authorized redirect URI: a loopback URL matching `NEST_REDIRECT_URI` below (e.g. `http://localhost:13371`) — must match exactly, including port
5. Store the Client ID and Client Secret in 1Password (item: `picklehome nest`, fields `client_id` / `client_secret`)

### 3. Device Access Console registration ($5, one-time)

1. [console.nest.google.com/device-access](https://console.nest.google.com/device-access) — a different console from Cloud Console
2. Accept terms, pay the one-time $5 registration fee
3. Create a new Device Access project, pasting in the OAuth Client ID from step 2. This gets its own **Project ID** (a UUID, distinct from the GCP project) — store it in 1Password (item: `picklehome nest device access console`, field `project_id`)
4. Leave Pub/Sub events off (polling is all this CLI needs)

### 4. `.env` and structure naming

1. Run `just dotenv` to pull the three values above into `.env` as `NEST_CLIENT_ID`, `NEST_CLIENT_SECRET`, `NEST_PROJECT_ID`. `NEST_REDIRECT_URI` is set directly in `.env.template` (not a secret).
2. In the Google Home app, give each structure (house) a clear custom name — that name is what `nest/locations.py` maps onto our canonical slugs (see [Locations](#locations) below).

### 5. Authorize device sharing + run OAuth

`just nest auth` opens a browser to Google's **partner connections** URL — not the standard OAuth authorize endpoint. This is where you pick which structures to share with the Device Access project; skipping it means the API returns zero devices even with valid tokens. It then redirects to `NEST_REDIRECT_URI`, where the CLI is listening locally to catch the authorization code and exchange it for tokens, cached at `~/.local/state/picklehome/nest-tokens.json`.

If the Device Access project is ever recreated, device sharing has to be redone (it's tied to that project's ID, not just the OAuth client).

## Commands

```
just nest auth                       # authorize device access, save tokens
just nest status                     # devices grouped by location
just nest status --location SLUG     # limit to one location
just nest status <name>              # detail view (substring match on name)
```

## Locations

`just nest status` groups devices by our canonical locations (main house,
beachhouse, ...) from the shared [`picklehome/locations.py`](../picklehome/locations.py)
registry, the same one climate and locks use. SDM structures only carry an
opaque id plus whatever custom name you gave them in the Google Home app; to
map those onto our slugs, add a `nest_structures` field (comma-separated
structure custom names) to the location's `picklehome-location` 1Password
item, then run `just dotenv`. See
[climate/README.md](../climate/README.md#locations-multi-address) for the
full location item format.

Mapping is optional and graceful: a structure with no matching location (or
no registry at all) still shows up grouped under its raw custom name, sorted
after the known locations.

## Module layout

```
nest/
├── nest_cli.py         # CLI: auth + status commands
├── locations.py        # map SDM structures onto shared picklehome locations
└── sdm/
    ├── auth.py         # OAuth loopback flow (partner connections + token exchange/refresh)
    └── client.py        # SDM API client: structures, devices, per-trait parsing
```

## Architecture

- **Auth:** OAuth2 authorization-code flow with a loopback redirect (no library dependency — a stdlib `http.server` catches the one redirect, `aiohttp` does the token exchange). Refresh token cached at `~/.local/state/picklehome/nest-tokens.json`; the CLI refreshes the access token on every invocation rather than tracking expiry, since it's cheap and the CLI runs briefly.
- **Devices:** one `NestDevice` dataclass with a `device_type` discriminator ("THERMOSTAT" / "CAMERA" / "DOORBELL") rather than separate classes per type, since all three need to sort into the same location-grouped listing. Thermostat fields (mode, setpoints, humidity) and camera/doorbell fields (live-stream presence) are just optional on the shared dataclass.
- **Structures vs devices:** the SDM `devices.list` endpoint returns every device across every structure in one flat list; each device's `parentRelations` points at its structure through a room (`structures/{id}/rooms/{id}`, not a bare structure path) — pull the structure id out by position, not by taking the last path segment. `structures.list` is a separate call needed to resolve that id to a human-readable custom name.

## Findings

### Cameras and doorbells never report connectivity — this is a real SDM API gap, not a bug

`sdm.devices.traits.Connectivity` is present and reliable for `THERMOSTAT` devices (`status: ONLINE`/`OFFLINE`), but is completely absent from every `CAMERA` and `DOORBELL` device response, confirmed live across 8 devices on 2 structures. `just nest status` shows `unknown` for every camera/doorbell's connectivity — this is the honest state, not a parsing gap.

Google's own published example payloads for [Camera (wired)](https://developers.google.com/nest/device-access/api/camera-wired), [Camera (battery)](https://developers.google.cn/nest/device-access/api/camera-battery), and [Doorbell (battery)](https://developers.google.com/nest/device-access/api/doorbell-battery) never include `Connectivity`, while the thermostat example in the [API overview](https://developers.google.com/nest/device-access/api) does. Per Google's own docs, "the absence of a trait in a GET response indicates that the trait or feature is not currently available for the device" — so this is consistent, documented (if not explicitly called out) behavior, not an account quirk.

The predecessor API (the deprecated "Works with Nest" REST API, sunset 2023) *did* expose a per-camera `is_online` field. SDM dropped it for camera-family devices when it replaced that API (~2019-2020) and never added an equivalent. `python-google-nest-sdm` (the library behind Home Assistant's Nest integration) has the same gap for the same reason — the field isn't in the API response for it to expose. There's no open Google feature request tracking this that we could find; treat it as a stable, likely-permanent limitation, not a pending fix.

**No good substitute exists.** The least-bad option is treating a `FAILED_PRECONDITION`/timeout error from a `GenerateRtspStream`/`GenerateWebRtcStream` command as a possible-offline signal — but only piggybacked on a real stream request a user already made, never polled, since stream generation is rate-limited (Nest cameras throttle to `RESOURCE_EXHAUSTED` after repeated calls). Pub/Sub motion/person events are activity-triggered, not heartbeats, so their absence is too confounded by low-activity locations to use as a liveness signal. Not implemented here — `unknown` stands as the correct, honest status for camera-family devices unless a future need justifies the stream-error proxy.
