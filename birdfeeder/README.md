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
just birdfeeder status                                    # device state: battery, WiFi signal, online, firmware
just birdfeeder events [--days N]                          # bird detection log, default last 1 day
just birdfeeder events [--days N] --species TEXT            # filter to one species (case-insensitive substring)
just birdfeeder events [--days N] --urls                    # also print image/video URLs (see note below)
just birdfeeder events [--days N] --json                    # structured output, always includes URLs
just birdfeeder species [--days N]                          # species seen, with counts + a tip to filter events
just birdfeeder species [--days N] --json                    # structured output
just birdfeeder sync [--days N] [--no-videos]                # mirror events, images, and videos locally, default last 2 days
just birdfeeder skylight-sync [--limit N] [--include-unidentified]  # upload mirrored clips to the Skylight "Birds" album
```

`species` aggregates identified events (unidentified events are excluded) and defaults to a
7-day window rather than `events`'s 1-day default, since species diversity accumulates slower
than raw detections. Each entry prints a ready-to-paste `events --species "..."` command using
the same `--days` value, so going from "what showed up" to "show me every visit from that one"
is a copy-paste away.

## Local mirror

`sync` copies the event log, event images, and event video clips into a local store, because the
API's image and video URLs expire after ~48 hours and nothing else keeps them. It is idempotent (keyed by `trace_id`), so run
it as often as you like: `--days 365` backfills everything the account still has, and the
default `--days 2` is the incremental run.

```
~/.local/state/picklehome/birdfeeder/        # override with BIRDFEEDER_MIRROR_DIR
  mirror.sqlite3                             # one row per event: time, species, confidence, image path
  images/YYYY/MM/DD/<trace_id>.jpg           # UTC date of the event
  videos/YYYY/MM/DD/<trace_id>.mp4           # ~10s clip, h264 + aac, 640x360
```

It walks the range one day at a time and saves after each window, so an interrupted backfill picks
up where it stopped. A failed image or video download keeps the event row, is reported on stderr (exit 1),
and is retried by the next `sync` that covers that day. A species identified after the first fetch
fills in on the existing row, and a later fetch without one never blanks it.

Videos need `ffmpeg` on PATH (`sync` stops up front if it's missing; `--no-videos` skips them). Each
clip is an HLS playlist of ~2s `.ts` segments, which `sync` fetches, joins, and remuxes into one mp4
with `-c copy`, so nothing is re-encoded. The pre-signed segment URLs only work with GET (HEAD returns
403). Clips run ~10s even when the recorded event is shorter, and cost ~0.7MB each.

The first backfill (2026-10-30) found 1,182 events back to 2026-09-10, 52% species-identified,
about 120MB of images and 800MB of videos (about 60MB/day at October's rate). A full
backfill of videos took about 2 minutes. Single wide-window queries behave oddly (a 30-day query returned events only
back to Oct 18 while a 365-day one went back to Sep 10), which is why the sync uses one-day windows.

## Skylight upload

`skylight-sync` uploads mirrored clips to a "Birds" album on the Skylight frame (created if missing).
It reads only the mirror, never the VicoHome API, and shells out to `scripts/skylight` (pinned
pyskylight). Sign in once with `just skylight-login` (Skylight now emails a login code). By default it
uploads species-identified events; `--include-unidentified` adds the rest, captioned "Bird". Captions
look like `Northern Cardinal, Tue Oct 27 2:57pm`, in the frame's timezone. Set `SKYLIGHT_FRAME_ID`
if the account has more than one frame.

Uploads are recorded in `skylight-uploads.jsonl` in the mirror directory, one line per clip with its
Skylight message id, the moment it succeeds. That makes a run resumable (a rerun skips what's there)
and undoable (`just skylight messages-delete --id <message_id>`).

Built for unattended runs, because the API is unofficial and has no documented limits:

- A 429 backs off exponentially (60s up to 30min) and doubles the pause between uploads, which
  relaxes after a long clean streak. pyskylight's CLI output drops the `Retry-After` header, so the
  server's requested delay can't be honored.
- 5xx responses, network errors, and timeouts retry with backoff (30s up to 10min), 8 attempts per call.
- An expired session (re-run `just skylight-login`), a Plus-required error, or any other 4xx stops the
  run immediately with the reason, since retrying can't fix them. Progress is already saved.
- If an upload fails after Skylight created the message anyway, the retry finds it by caption and
  adopts it instead of uploading a duplicate.
- Skylight silently ignores an album add that lands before it finishes processing a new upload (the
  call succeeds and nothing is added), so each batch of adds is checked against the album and retried.
  That check uses `album-message-ids`, which returns only the newest 100, so batches stay small. To
  count a whole album, use its `videos_count`/`photos_count`, not the ids list.

On the frame, uploads don't notify phones (`notify_on_new_photos` is off).

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
- Species ID is spotty: on this account about half of events (52% in the 2026-10-30 backfill) come
  back with an empty `subcategoryInfoList` (`species_name` is `None`) even though the top-level
  `deviceAiEventList` tag correctly says `["bird"]` every time. It may be gated by a VicoHome
  subscription, which is unconfirmed.
- `videoUrl` points at an HLS playlist (`.m3u8`, a few KB), not an mp4. The segment path contains
  `60d`, which may mean a 60-day retention (unconfirmed), so don't leave old clips unmirrored.
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
  mirror.py               # local store + day-window sync (sqlite + images + videos)
  skylight_sync.py        # uploads mirrored clips to a Skylight album (ledger, backoff, dedup)
```
