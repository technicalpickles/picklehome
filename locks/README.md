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

### "Online bridge + blank lock identity" means the lock wedged, not a dead battery

The opposite-looking case from the one above, and the diagnosis is different.
Here the bridge stays `"online"` to the cloud the whole time, but the lock
itself has stopped answering it over BLE because the lock's firmware hung. A
power-cycle of the *lock* clears it; the batteries are usually fine.

The tell is in the lock's identity fields, which the cloud reads over BLE and
caches separately from live status. A healthy or merely-stale lock retains its
cached identity (firmware version, `hostLockInfo` serial/manufacturer, last
battery voltage, projected `deathDate`). A wedged lock comes back blank:

- `currentFirmwareVersion` starts with `0.0.0` (lock firmware never read)
- `hostLockInfo` is all `"unknown"` / `0`
- `battery` / `batteryInfo.level` is `-1` with no battery history at all
  (no `infoUpdatedDate`, no `lastChangeVoltage`, no `deathDate`)
- `batteryInfo.warningState` is `"none"` (it dropped off abruptly, never
  recorded a graceful low-battery decline)
- yet the `Bridge` is `operative: true`, `status.current == "online"`

Observed live: a wedged lock reported 97% battery the instant it recovered, so
the blank `-1` reading meant "no read", not "empty". Do not assume dead
batteries from this state.

Recovery (does not require the full app re-registration flow):

1. Pull one battery, wait ~10s, reseat it.
2. The lock reboots and announces "Welcome to Yale Living".
3. Enter the master code followed by the gear button.
4. It re-bonds to the bridge and reappears healthy in the app (and in
   `just locks status`) within a minute, identity fields repopulated.

The August/Yale app surfaces this as a "communication problem" and offers to
walk you through re-registering (power-cycle + master code). The steps above
are the short version of that flow; you rarely need to fully re-register.

Note: `Calibrated: false` is **not** a signal here. Every lock on this account
(Yale retrofit modules) reports `Calibrated: false`, including healthy ones.
Compare against a known-good lock before treating any single field as the
smoking gun.

### A displayed battery percentage can be a years-old cached reading

The battery level the API returns is the last value the bridge successfully
read over BLE, which can be ancient if the lock has been unreachable. A lock
can show a healthy percentage while its batteries are actually flat.

Observed: a lock displayed 97% before and after a battery swap that was in fact
necessary to bring it back. The real tell was `batteryInfo.deathDate` ==
`2022-07-12` (a projected death date already in the past) and an
`infoUpdatedDate` years old. When a lock with an online bridge has gone stale
(old `status_datetime`), do not trust the battery percentage on its own:

- Check `batteryInfo.deathDate` -- if it is in the past, the reading is ancient.
- Check `batteryInfo.infoUpdatedDate` for when the level was last actually read.

Recovery for this case (online bridge, intact identity, stale status, the
"unknown_error_during_connect" reason) was: power-cycle the *bridge* (unplug,
wait, replug) **and** replace the lock's batteries. This is distinct from the
wedged-lock case above (blank identity, lock power-cycle + master code).

Note: `is_stale` keys only off bridge connectivity, so a lock on an online
bridge with a stale `status_datetime` still renders its battery cell as live.
The percentage shown there is the last read, not necessarily current.

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
