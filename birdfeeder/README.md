# Bird Feeder/Camera: VicoHome (Harymor)

Device state and bird detection log via the VicoHome cloud API (the platform behind the Harymor
smart bird feeder and other rebranded VicoHome/Vico Nature hardware).

## Setup

1. Store the VicoHome/Vico Nature app login (email/password) in 1Password. This repo currently
   reads it from a `vicohome` item in the **Personal** vault (not `picklehome`):
   ```bash
   op item create --category=login \
     --title="vicohome" \
     --vault=Personal \
     "username[text]=YOUR_EMAIL" \
     "password=YOUR_PASSWORD"
   ```
2. Run `just dotenv` to inject credentials into `.env` (see `.env.template` for the
   `VICOHOME_EMAIL` / `VICOHOME_PASSWORD` mapping)
3. Check status: `just birdfeeder status`

## Commands

```
just birdfeeder status                              # device state: battery, WiFi signal, online, firmware
just birdfeeder events [--days N]                    # bird detection log, default last 1 day
just birdfeeder events [--days N] --urls             # also print image/video URLs (see note below)
just birdfeeder events [--days N] --json             # structured output, always includes URLs
```

Image/video URLs are omitted from the default `events` output because they're long and noisy.
They're also **not access-controlled beyond the URL itself**: pre-signed cloud storage links
(image) or a JWT embedded in the query string (video), both good for ~48 hours to anyone who has
the link, no VicoHome login required. Use `--urls` or `--json` when you actually need them.

## Architecture

### Auth

Stateless: logs in fresh on every invocation via `POST /account/login`
(`{email, password, loginType: 0}` → bearer token in `data.token.token`). No token persistence,
same approach as the BlueAir module — a short-lived CLI process re-authenticating each run is
simpler than managing a token cache, and VicoHome's API doesn't expose a separate refresh flow.

### API

Direct HTTP calls to `api-{region}.vicohome.io` (region defaults to `us`, override via
`VICOHOME_REGION`). No official public API; endpoints below were reverse-engineered by the
community ([`vico-cli`](https://github.com/dydx/vico-cli),
[`vicohome-ha`](https://github.com/TomTje/vicohome-ha)) and confirmed directly against a live
account.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/account/login` | Auth, returns bearer token |
| POST | `/device/listuserdevices` | All devices: battery, WiFi signal (dBm), online, IP, MAC, firmware |
| POST | `/library/newselectlibrary` | Bird detection events in a time range (species, image/video URLs) |

### Event schema quirks

- The top-level `birdName` field in the raw API response is actually the **Latin/scientific
  name**, not the common name. The common name and per-event confidence live in
  `subcategoryInfoList[0].objectName` / `.confidence`, which is an **empty list** when the AI
  detected "a bird" but couldn't identify the species (no confidence value at all in that case,
  not just a low one).
- Species ID appears to be gated by a VicoHome subscription: on this account, the large majority
  of events come back with an empty `subcategoryInfoList` (`species_name` is `None`) even though
  the top-level `deviceAiEventList` tag correctly says `["bird"]` every time.
- `imageUrl`/`videoUrl` are pre-signed URLs (S3/GCS/Oracle Cloud depending on which backend
  stored that particular clip) that expire after ~48 hours. Don't persist them long-term; refetch
  via `events` if needed later.

### Which device this actually is

Confirmed: the device is the Harymor feeder. The generic `"Smart Camera"` name and
`aiBirdDevice.isAiBirdDevice: false` flag from `/device/listuserdevices` are just an artifact of
the account's own naming, not a signal about hardware type — the device has since been renamed in
the app (now "Fence Birdfeeder"). Whether the Vico Nature app
(`com.smartaddx.vicohome.nature`) shares this same API surface with the general VicoHome app
(`com.smartaddx.vicohome`), or feeder-specific hardware registered there could live on a separate
backend, remains unconfirmed — moot in practice since this module already gets real device state
and bird events through `api-{region}.vicohome.io`.

## Module structure

```
birdfeeder/
  birdfeeder_cli.py       # CLI entry point (argparse)
  vicohome/
    auth.py               # Env var credential loading, stateless login
    client.py              # HTTP client, Device/BirdEvent dataclasses
```
