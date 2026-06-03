# sonos

Sonos speaker health checks over the local network. Discovers speakers via
[soco](https://github.com/SoCo/SoCo) (UPnP/SSDP, no cloud, no credentials) and
reports whether each expected speaker is online, what it's playing, and whether
anything's muted.

## Commands

```
just sonos status          # health check against the roster; exits non-zero if a speaker is down
just sonos roster          # print currently-online speakers as roster YAML
just sonos list            # raw list of every discovered speaker
```

`status` reads the roster at `sonos/config/speakers.yaml`, compares it against
what's live, and exits `1` when any expected speaker is offline, muted, or
otherwise flagged. That makes it usable as a cron/CI health gate. Override the
roster path with `--roster`.

## The roster

Discovery can only report what answers on the network; it cannot tell you a
speaker is *missing* unless it knows the speaker should exist. `speakers.yaml`
is that expected list. A speaker present in the roster but absent from discovery
is reported `OFFLINE` (this is how "Alex's Room is unplugged" surfaces instead
of silently vanishing).

```yaml
speakers:
  - name: Kitchen
    uid: RINCON_7828CA06736E01400   # stable identity, preferred for matching
  - name: Alex's Room               # offline now: name-only, uid matched once seen
```

Generate the real roster from what's online:

```
just sonos roster > sonos/config/speakers.yaml
```

Then hand-add any speaker that was offline at generation time (name only).

**`speakers.yaml` is gitignored.** A Sonos `uid` is `RINCON_<MAC>01400` and
embeds the device MAC, which is geolocatable (Sonos can broadcast a SonosNet
wireless mesh). `speakers.example.yaml` is checked in with placeholder uids.

## Module layout

```
sonos/
├── sonos_cli.py        # CLI: status / roster / list
├── client.py           # soco I/O: discovery + reading speaker state
├── roster.py           # load the expected-speakers YAML
├── model.py            # pure data model + reconcile (discovered vs expected)
└── config/
    ├── speakers.yaml          # real roster (gitignored)
    └── speakers.example.yaml  # template
```

The logic worth testing (offline detection, mute flagging, uid/name matching)
lives in `model.py` as pure functions; `client.py` is the thin soco boundary.
Tests are in `tests/sonos/`.

## Findings

Things learned integrating with Sonos that you can't derive from the code.

### Read `visible_zones`, not `all_zones`

A bonded set (a 5.1 home theater, a stereo pair) exposes several soco devices
that share one zone name. The Media Room here is a home theater: `all_zones`
shows four devices named "Media Room" (soundbar + sub + two surrounds), three
of them hidden. `visible_zones` collapses them to the one logical speaker. This
matches what the Home Assistant Sonos integration does.

### Identity is the uid, not the name

Match on `uid` (`RINCON_...`), never the zone name. Names duplicate across
runs and people rename rooms; the uid is stable. The roster falls back to
name matching only for speakers whose uid isn't known yet (because they were
offline when the roster was written).

### Volume and mute are per-speaker; "now playing" is per-group

In a group, only the coordinator knows the current track. `client.read_speaker`
reads transport/track info from `zone.group.coordinator` but volume and mute
from the zone itself.

### Discovery is multicast and slightly non-deterministic

`soco.discover()` uses SSDP multicast; successive runs can return a different
set depending on timing. The roster cross-check is what makes the result
trustworthy: a speaker that blips out of one discovery still shows as expected.

### Same library as Home Assistant

HA's Sonos integration uses `soco` too (pinned `0.30.14` in the vendored clone,
`0.31.1` on dev), plus `sonos-websocket` for real-time push and `defusedxml`.
We poll instead of subscribing to events, so we need neither.
