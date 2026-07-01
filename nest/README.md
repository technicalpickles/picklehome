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
- **Devices:** one `NestDevice` dataclass with a `device_type` discriminator ("THERMOSTAT" / "CAMERA") rather than separate classes per type, since both need to sort into the same location-grouped listing. Thermostat fields (mode, setpoints, humidity) and camera fields (live-stream presence) are just optional on the shared dataclass.
- **Structures vs devices:** the SDM `devices.list` endpoint returns every device across every structure in one flat list; each device's `parentRelations` points at its structure by id. `structures.list` is a separate call needed to resolve that id to a human-readable custom name.
