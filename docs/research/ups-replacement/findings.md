# UPS replacement: lab rack + desk

Research (2026-10-04) into replacing both UPSes: the one in the network cabinet
(modem, router, switches, picklelab) and the one under the desk (workstation,
monitor, dock).

## TL;DR

Replace both units; don't re-battery them.

- **Lab:** CyberPower **CP1500PFCRM2U** (~$360). 2U rack, sine wave, all 8
  outlets battery-backed. About 66 min at 100W, so roughly 50-70 min for the
  cabinet's estimated 90-125W.
- **Desk:** CyberPower **CP1500PFCLCD** (~$240). Tower, sine wave, 6 of 12
  outlets battery-backed. About 45 min at an assumed 150W against a 15-min
  target.

## What's there now

| | Lab rack | Desk |
|---|---|---|
| Model | APC BE650G1 | APC BR1000G |
| Bought | 2016-12 | 2017-04 |
| Rating | 650VA / 390W | 1000VA / 600W |
| Outlets | 8 total, 4 on battery | 8 total, 4 on battery |
| Waveform | Stepped approximation | Stepped approximation |
| Battery | RBC17 | APCRBC123 |
| Status | Battery dead | Throws **F02** on power loss |

**F02** is "On-Battery Output Short" (Schneider FA279105). Three causes: a real
short, a weak/old battery, or excessive load. F02 means the UPS drops the load,
so it's protecting nothing. A free test separates the two likely causes: power
off, unplug everything from the battery outlets, power on, pull the wall plug.
If it still faults with nothing attached, the unit is internally dead. If it
only faults under load, it's the battery (the likely answer on a 9-year-old
original).

## Why replace instead of re-battery

- Both chassis are 9-10 years old. The usual guidance is to replace the whole
  unit once the battery is EOL and the chassis is past ~8 years.
- Electrolytic caps are past their 4-8 year replacement window.
- MOVs (3-5 year life) are likely spent, and that fails silently: the surge
  outlets keep passing power but stop protecting.
- Transfer relay wear is **not** the main concern. It scales with transfer
  count, not age, and APC has a separate code (F06) for a welded relay.

## Requirements

- **Lab:** ride through blips, shut down gracefully on long outages, come back
  on once power is stable. Six devices need their own outlet: US-8-150W,
  US-24, USG 3P, BGW320, picklelab NUC, and the Synology once it's powered on.
  The rack already has rack-mounted power strips.
- **Desk:** 15 minutes is enough. The point is to keep working through an
  outage while the internet stays up on the lab UPS.

## Measured load

The UniFi controller reports live per-port PoE draw (`port_table[].poe_power`
in `/stat/device`). Joining that against each device's `uplink.uplink_mac` +
`uplink.uplink_remote_port` maps every PoE port to whatever it powers.
(Tracked as taskwarrior `64f3ba59-1790-4ec8-b65d-a23d5779166a` to surface this
in `just unifi`.)

| US-8-150W port | Watts | Device |
|---|---|---|
| p1 | 4.01 | Josh Office AC Pro |
| p2 | 5.92 | US 8 switch (PoE-fed, needs no outlet) |
| p4 | 3.50 | Living Room AC LR |
| p5 | 6.96 | Upstairs AC HD |
| p7 | 3.71 | Tracy Office AC Pro |
| p8 | 7.08 | Not an adopted device; almost certainly the PoE-fed CloudKey G2+ |
| | **31.18** | Total PoE delivered |

**Nameplate is about 2x actual** (an AC Pro is rated 9W and draws 4W), which is
why UPS vendors' sizing tools oversize.

Still unmeasured: BGW320, USG 3P, US-24, the US-8-150W's own draw, the NUC,
and the whole desk. The cabinet is estimated at 90-125W, and the desk is
assumed to be 120-150W.

## Candidates

All from CyberPower datasheets, not retailer listings (see "Trust datasheets"
below).

| Model | VA/W | Outlets (battery + surge-only) | Battery bank | Waveform | Price (2026-10) |
|---|---|---|---|---|---|
| **CP1500PFCRM2U** | 1500/1000 | 8 (**all 8** battery) | 2x 12V 9Ah | Sine | $359.95 (reg $399.95) |
| **CP1500PFCLCD** | 1500/1000 | 12 (6 + 6) | 2x 12V 9Ah | Sine | $239.95 (MSRP $274.95) |
| CP1350PFCLCD | 1350/880 | 12 (6 + 6) | 2x 12V 7Ah | Sine | - |
| CP1000PFCLCD | 1000/600 | 10 (5 + 5) | 1x 12V 9Ah | Sine | ~$180 (MSRP $199.95) |
| CP900AVR | 900/560 | 8 (4 + 4) | 2x 12V 7.2Ah | Simulated sine | $164.95 |
| OR1500LCDRT2U | 1500/900 | 8 (all 8 battery) | 4x 12V 7Ah | Simulated sine | $545.95-629.95 |

The CP1500PFCRM2U also has a slot for an optional SNMP/remote-management
card, is 10.5" deep, and weighs 26.8 lbs.

Ruled out:

- **CP1000PFCLCD for the desk:** a single battery puts it at ~20 min at 150W,
  and it drops below 15 min around 190W. With the desk load unmeasured, $60
  more for double the battery bank beats going to measure it.
- **CP900AVR:** simulated sine, fewest battery outlets, and its own product page
  and datasheet disagree on outlet count.
- **OR1500LCDRT2U:** all 8 outlets on battery and a bigger bank, but $550+,
  48 lbs, and simulated sine.
- **EcoFlow River 3 Plus:** its edge is extra Wh, which a 15-minute target
  doesn't need.
- **CP1500PFCLCD for the lab** works if rack form factor doesn't matter
  ($120 cheaper), but with 6 battery outlets for 6 devices it has zero spare.

## Runtime

CyberPower publishes runtime only at half and full load on datasheets.
Low-load numbers come from their
[runtime calculator](https://www.cyberpowersystems.com/tools/runtimes/),
read 2026-10-04. Values are minutes. Every curve matches its datasheet's
half/full points.

| Watts | CP1500PFCRM2U | CP1500PFCLCD | CP1000PFCLCD |
|---|---|---|---|
| 50 | - | 100 | 60 |
| 100 | 66.2 | 66 | 30 |
| 200 | 33.5 | 30.8 | 13.5 |
| 300 | 21.4 | 23 | 6 |
| 400 | 14.4 | 14 | 4.5 |
| 500 | 10.2 | 10 | 3 |
| 600 | 7.8 | 8 | 2 |
| 1000 | 3.1 | 2.5 | - |

These assume new, fully charged batteries at room temperature. Expect less as
the batteries age.

## NUT on picklelab

Tracked as taskwarrior `27a08728-8836-4f43-b211-f86f0d11a728`. Findings
that need to survive into that work:

- **Graceful shutdown alone breaks auto-restart.** picklelab's BIOS has
  "auto power-on after power loss" enabled
  (`homelab/docs/homelab_03_host_setup.md`), but that only fires on an AC
  transition. If the NUC halts while the UPS still has charge, it never sees
  one and stays off. The shutdown has to issue `shutdown.return` so the UPS
  cuts its own output and restores it when mains returns.
- **CyberPower firmware restarts output `ups.delay.start` seconds after
  shutdown regardless of mains status.** Set `ondelay=0` in `ups.conf`.
- Test the full plug-pull cycle; don't trust the config.
- CP1500PFCLCD is in NUT's hardware list on `usbhid-ups` (confirmed on 2.7.1
  and 2.7.4), with `shutdown.return` / `shutdown.stayoff` / `shutdown.stop`.
  Reporters note battery voltage isn't really supported, and the low-battery
  threshold resisted changes (possibly only discrete values), which is the
  knob you'd want for shutdown timing.
- **CP1500PFCRM2U isn't individually listed.** Same family, very likely
  fine, but unconfirmed. See also
  [networkupstools/nut#2667](https://github.com/networkupstools/nut/issues/2667)
  for intermittent CyberPower `usbhid-ups` disconnects. If that's a
  dealbreaker, the CP1500PFCLCD tower is the confirmed option.

### What the CP1500PFCRM2U reports

The datasheet lists an HID-compliant USB port, the same interface the
CP1500PFCLCD uses with NUT, so `usbhid-ups` should work even though the
model isn't listed by name (unconfirmed on hardware). Standard HID variables:
`ups.status` (`OL` / `OB` / `LB`), `battery.charge`, `battery.runtime`,
`ups.load`, plus the shutdown commands. It also has a dry-contact port and a
slot for an optional RMCARD205 (SNMP/HTTP) if USB proves flaky.

### Shutdown and restart design

The tension: the NUC's BIOS "power on after AC loss" only fires if its power
actually drops and returns, so the UPS has to cut its own output
(`shutdown.return`). But the modem, router and switches share that UPS, and
the unit can't switch outlets individually. A long `offdelay` resolves it: the
NUC tells the UPS "cut output in N minutes" and halts, and the network gear
keeps running until the timer ends.

1. Power drops, UPS goes on battery. Short blips are ignored.
2. `upssched` timer (about 5 min on battery, cancelled on `ONLINE`) fires, the
   NUC shuts down cleanly and sends `shutdown.return` with a long `offdelay`.
3. The network stays up until the delay ends or the battery dies.
4. Mains returns, the UPS restores output, everything boots, the NUC powers on
   from the BIOS setting.

CyberPower firmware quirks
([usbhid-ups(8)](https://dyn.manpages.debian.org/testing/nut-server/usbhid-ups.8),
[nut-upsuser thread](https://lists.alioth.debian.org/pipermail/nut-upsuser/2015-January/009500.html),
[Netgate forum](https://forum.netgate.com/post/1186028)):

- The restart timer (`ondelay`) counts from the shutdown command, not from
  mains returning, so with defaults the output comes back on its own after
  about 30 s even while on battery. Set `ondelay = 0`, which means "restore
  only when mains returns".
- `offdelay` is divided by 60 and rounded down on many CyberPower models, so
  anything under 60 acts as an immediate cut. Use multiples of 60.
- With `ondelay = 0` there's no "wait for stable power" window. If power
  flickers back and drops again, the NUC can boot on a drained battery. Guard
  with `ignorelb` plus `override.battery.charge.low` (around 50%) so a boot on
  low battery shuts straight back down.

To test, not trust: that this unit accepts a 20-30 min `offdelay`; that a
power return mid-countdown still produces the off-then-on cycle; and as a
backup either way, a Wake-on-LAN to the NUC from the USG or CloudKey on power
restore. The Synology has a built-in NUT client in DSM, so point it at
picklelab.

## Open questions

- ~~**Are the rack's existing power strips plain PDUs or surge-protected?**~~
  **Answered 2026-10-07: surge-protected.** The cabinet strip is a Monoprice
  12-outlet 1U rackmount "PDU" rated 1050 joules. So it doesn't go behind the
  new UPS: plug the cabinet gear straight into the CP1500PFCRM2U's 8 battery
  outlets and leave the strip on wall power for anything that doesn't need
  battery. If more than 8 outlets are ever needed, swap in a plain PDU (no
  joules rating). The 8-outlet math: 6 cabinet devices, 7 if the Hue bridge
  goes on battery too, so one spare.

  Why a surge strip behind a UPS is a bad idea: it voids the UPS's connected-equipment
  warranty, UL 1363 prohibits plugging a power tap into another one (a UPS
  counts), it makes overloading the UPS easy, and on a simulated-sine output
  the strip's MOVs and filter caps run hot. It adds nothing, since the UPS
  already suppresses surges. A plain PDU within the UPS's rating is fine.
  Likely moot, since 8 battery outlets cover all 6 devices.
- **Is the 7.08W device on US-8-150W p8 the CloudKey G2+?** It shows as "not
  adopted" because the CloudKey is the controller itself. That decides whether
  it needs its own outlet.
- **What's the real desk load?** Never measured. Buying the CP1500PFCLCD
  sidesteps needing the answer.

## Research notes

### Trust datasheets, not retailers

Retailer listings disagree with each other and with CyberPower:

- Micro Center lists CP1500PFCLCD as 10 outlets (it's 12).
- Newegg's title says CP1500PFCLCD is 1500VA/900W (it's 1000W).
- CP900AVR's product page says 10 outlets (5 battery); its datasheet says 8 (4).
- CP1000PFCLCD's datasheet contradicts itself: the summary bullet says 8 / 1 min
  half/full, the spec table on the same PDF says 6 / 2 min. The runtime
  calculator agrees with the spec table.

Datasheets and user manuals come from CyberPower's CDN:

```
https://dl4jz3rbrsfum.cloudfront.net/documents/CyberPower_DS_<MODEL>.pdf   # datasheet
https://dl4jz3rbrsfum.cloudfront.net/documents/CyberPower_UM_<MODEL>.pdf   # user manual, no runtime chart
```

`pdftotext -layout` reads them fine.

### Scraping dead ends

- **cyberpowersystems.com product pages:** plain page text renders fine in
  Playwright, but expanding the Specifications tab repeatedly on one page
  tripped their bot check.
- **Runtime calculator:** behind AWS WAF that blocked Playwright both headless
  and headed. Real Chrome (via the Claude in Chrome extension) loads it fine.
  The model picker is select2, so setting the `<select>` with jQuery doesn't
  stick: type into the search box and press Return. Highcharts is bundled (no
  `window.Highcharts`) and the tooltip is an HTML div outside the SVG.
  Dispatching `pointermove` + `mousemove` on the chart `<svg>` at each x-axis
  label's center, then reading the element whose text starts with
  `Estimated Runtime @`, dumps every data point. That beats pixel-mapping the
  x axis, which is categorical (50, 100, 200, ... W), not linear.
- **Retail prices:** Amazon's interstitial and B&H's Cloudflare check beat
  Playwright both headless and headed. Search-result snippets and manufacturer
  MSRP are what actually worked.
