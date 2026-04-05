# locks

Yale Access / August cloud integration. Authenticates against the August
cloud via [yalexs](https://github.com/bdraco/yalexs) and reports lock and
bridge status across all homes on the account.

## Commands

```
just locks auth            # login, cache tokens at ~/.local/state/picklehome/yale-tokens.json
just locks status          # one-line summary per lock, grouped by home
just locks status <name>   # detailed view (substring match; shows all matches)
```

Credentials come from 1Password (`picklehome` vault, `Yale Access` item) via
`YALE_EMAIL` and `YALE_PASSWORD` in `.env`. See the project README for how
`.env` is generated.

## Module layout

```
locks/
├── locks_cli.py        # CLI: auth + status commands
└── yale/
    ├── auth.py         # login flow, API key patch, token cache
    └── client.py       # data model (YaleLock, BridgeStatus) and API calls
```

## Findings

Things learned by integrating with the August API that you cannot derive by
reading the code. If you are about to debug this module, read this section
first.

### "Bridge offline" often means "dead lock battery", not "dead bridge"

This is the most important finding in this module. The August Connect bridge
reports itself as `"offline"` to the cloud whenever it cannot maintain its
Bluetooth Low Energy pairing with the lock it is bonded to. The bridge's
power, radio, and WiFi can all be working fine; if the lock stops answering
over BLE, the bridge still goes dark from the cloud's perspective.

This means:

- **A dead lock battery presents as "bridge offline" in the API.** The API
  gives no direct signal that the underlying problem is the lock, not the
  bridge.
- **The bridge's `status.lastOnline` timestamp is a reasonable estimate of
  when the lock's battery died**, because that is the last time the bridge
  successfully talked to its lock.
- **When multiple locks in one home go "bridge offline" in a narrow window,
  it is almost always a synchronized lock-battery cluster** (locks installed
  as one batch wear down together), not multiple bridges failing
  simultaneously.

Diagnostic order when a lock shows "bridge offline":

1. If `lastOnline` is several days ago and the `status_datetime` on the lock
   matches roughly the same staleness, replace the lock's 4x AA batteries
   first.
2. If batteries are fresh and the bridge still shows offline, power-cycle
   the bridge and watch its LED. See LED reference below.
3. If the bridge is still offline after a clean power-cycle, verify the
   bridge's WiFi connectivity directly (UniFi client list by MAC) to
   distinguish a dead bridge from a bridge that is on WiFi but cannot reach
   August's cloud.

The AUG-MDY1 (Smart Lock Pro 3rd Generation) takes 4x AA batteries per lock.
To avoid future synchronized failure clusters, stagger battery replacements
across locks in the same home by a few weeks rather than replacing them all
at once.

### WiFi RSSI and SSID are not populated by the API

The `wifiData` field on the raw lock detail payload is `null` on every lock
observed so far (AUG-MDY1 locks with august-connect bridges, firmware 2.3.1).
The `yalexs` library exposes wifi fields on its objects, but the August API
does not populate them for this hardware. The liveness signals to use
instead are:

- `bridge.status.current` (`"online"` / `"offline"`)
- `bridge.status.lastOnline` / `lastOffline`
- `bridge.enhancedStatus.WifiModuleConnectionIssueCount`

For real per-lock WiFi signal diagnostics, correlate the bridge's MAC address
against the UniFi client list.

### Stale API key in yalexs BRAND_CONFIG

`yalexs` ships with a stale API key in `BRAND_CONFIG[Brand.AUGUST]` that
returns 403 "API key is not valid". The older `HEADER_VALUE_API_KEY_OLD`
constant exported by the same library still works. `locks/yale/auth.py`
patches `BRAND_CONFIG` at import time to use the old key and clears
`_get_brand_config`'s `lru_cache`.

### Unbridged locks show placeholder values

Locks with no `Bridge` field and no `module` field in the raw payload have no
path to the cloud at all. The API returns placeholder values for them:
battery `-100%`, lock status `unknown`, door state `unknown`. The CLI
distinguishes this case from "bridge offline" by rendering `no bridge`
explicitly.

## August Connect LED reference

Useful for on-site diagnostics when power-cycling a bridge. Source:
[August support](https://support.august.com/troubleshooting-the-led-indicator-on-august-connect-HJLa0NZDS).

| LED | Meaning |
|---|---|
| Solid / blinking green | Normal. Ready to set up, actively talking to the lock, or handling a remote operation. |
| Blinking red | Communication problem between the Connect and the lock, or between the Connect and the internet. Usually temporary. |
| Solid red | Connect needs to be re-set up: 30-minute setup window expired, bridge is on WiFi but not paired with a lock, or bridge cannot join the local WiFi network. |
| No LED at all | No power. Check the USB cable, wall outlet, and USB power brick before assuming the bridge is dead. |
