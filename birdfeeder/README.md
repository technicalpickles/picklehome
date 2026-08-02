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
just birdfeeder status              # device state: battery, WiFi signal, online, firmware
just birdfeeder events [--days N]   # bird detection log, default last 1 day
```

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

### Which device actually shows up

The one device on this account is reported by the API as a general `"Smart Camera"`
(model `CG625-BD2-ST1BQJ`) with `aiBirdDevice.isAiBirdDevice: false` — i.e. not marketed as a
dedicated bird-feeder SKU — yet 100% of its events are bird detections. It's unclear whether this
*is* the Harymor feeder under a generic model label, or a separate VicoHome camera on the same
account that happens to be pointed at bird activity. The Vico Nature app (package
`com.smartaddx.vicohome.nature`) is a distinct Android app from the general VicoHome app
(`com.smartaddx.vicohome`); whether they share this same backend/account scope for feeder-specific
hardware, or Nature-registered devices live on a separate API surface entirely, is unresolved.
This module works against whatever `/device/listuserdevices` returns for the account, whatever
that turns out to be.

## Module structure

```
birdfeeder/
  birdfeeder_cli.py       # CLI entry point (argparse)
  vicohome/
    auth.py               # Env var credential loading, stateless login
    client.py              # HTTP client, Device/BirdEvent dataclasses
```
