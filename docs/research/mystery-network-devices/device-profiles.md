# Mystery Device Profiles

Detailed profiles for 8 unidentified WiFi clients on the home network. All are 2.4GHz-only, cloud-connected IoT devices with zero open TCP ports and no local API.

Data collected 2026-03-21 via UniFi API, nmap, mDNS discovery, and OUI lookup.

## Investigation methods exhausted

- OUI vendor lookup (`mac-vendor-lookup`)
- nmap TCP port scan (common IoT ports + full 1-1000 range on ESP32 devices)
- mDNS/Bonjour discovery (`dns-sd`)
- ARP table hostnames
- HTTP probes: Shelly (`/shelly`), Tasmota (`/cm?cmnd=Status`), generic (`/`)
- UniFi DPI data (not available for these devices)

All came back empty. These devices offer no local services whatsoever.

---

## 1. WNC "connect" devices (x4)

**OUI:** Wistron Neweb Corporation: embedded WiFi module manufacturer (not a consumer brand)

| # | MAC | IP | AP | Signal | Lifetime Traffic |
|---|-----|----|----|--------|-----------------|
| 1 | `2c:9f:fb:f8:96:bb` | .100 | Tracy Office AC Pro | -48 dBm | 28.6 MB |
| 2 | `2c:9f:fb:f8:98:dd` | .95 (static) | Living Room AC LR | -34 dBm | 29.3 MB |
| 3 | `2c:9f:fb:f8:99:01` | .101 (static) | Josh Office AC Pro | -51 dBm | 6.0 MB |
| 4 | `2c:9f:fb:f8:99:17` | .97 | Tracy Office AC Pro | -47 dBm | 28.7 MB |

- **First seen:** All on 2021-08-17 (installed together as a batch)
- **Hostname:** "connect" (source: `uap`, AP-reported, not device-provided)
- **MACs:** Sequential-ish, confirming same manufacturing run
- **Traffic pattern:** Three devices (~29 MB each) are similarly active; one (Josh Office, 6 MB) is mostly idle. 29 MB over 4.5 years = tiny status heartbeats, not data transfer.
- **Physical distribution:** Tracy Office (x2), Living Room (x1), Josh Office (x1)

### Top candidates

1. **GE Cync smart plugs (4-pack):** WNC modules, cloud-only, sold heavily in 4-packs at Home Depot/Costco in 2021. Cync = circular button, small LED.
2. **Wyze Plug (4-pack):** confirmed WNC ties, cloud-only, generic hostname behavior. Square button with "W" logo.
3. **TP-Link Kasa:** some runs used WNC, but Kasa usually provides its own hostname like "TP-LINK_xxxx", making this less likely.

### How to identify

- Check phone for Cync, Wyze, or Smart Life/Tuya apps
- Walk Tracy Office and Living Room looking for 4 identical outlet-mounted smart plugs
- DNS capture from .100 (Tracy Office, online): `*.cync.com` = GE, `*.wyze.com` = Wyze

---

## 2. Globalscale Technologies

| Field | Value |
|-------|-------|
| MAC | `f0:ad:4e:17:08:5c` |
| IP | .119 |
| AP | Josh Office AC Pro |
| Signal | -64 dBm (weakest of all mystery devices) |
| First seen | 2021-12-05 |
| Lifetime traffic | 1.7 MB |
| Hostname | None |

Globalscale makes Marvell ARM-based embedded platforms: single-board computers, IoT gateways, powerline adapter chipsets. Not a consumer brand.

1.7 MB over 4+ years is essentially a heartbeat. The weak signal (-64 dBm) suggests it's behind furniture or further from the AP than other office devices.

### Top candidates

1. **Powerline WiFi adapter:** Globalscale supplied Marvell chipsets for HomePlug/powerline products. A forgotten adapter plugged into an outlet would match: always-on, near-zero traffic if nothing is connected to its Ethernet port, no hostname.
2. **IoT bridge/hub:** a smart home gateway using Marvell Armada. The tiny traffic could mean its paired devices communicate over a non-WiFi protocol (Zigbee, Z-Wave).
3. **Travel router left plugged in:** less likely given the UniFi setup, but a GL.iNet or similar in client mode would show this profile.

### How to identify

- Look around Josh Office for a plug-in device with an Ethernet port, coax connector, or small antenna nub
- SSDP/UPnP probe (requires root for UDP scan): `nmap -sU -p 1900 192.168.1.119`. Gateways and powerline adapters often respond to SSDP even without TCP services

---

## 3. Shenzhen Intellirocks

| Field | Value |
|-------|-------|
| MAC | `d4:ad:fc:ac:9b:16` |
| IP | .155 |
| AP | Josh Office AC Pro |
| Signal | -51 dBm |
| First seen | 2022-11-30 |
| Lifetime traffic | 3.1 MB |
| Hostname | None |
| UniFi OUI | "Private" (Intellirocks not in UniFi's own DB) |

Shenzhen Intellirocks is a Shenzhen ODM that white-labels smart plugs and power strips for Amazon house brands, Govee, and others.

Also in Josh Office alongside the Globalscale device. Slightly more talkative (3.1 MB vs 1.7 MB) but still very quiet.

### Top candidates

1. **Smart power strip at desk:** Intellirocks' primary product category. Often sold as rebranded Amazon/Walmart house brand products with app control.
2. **USB charging hub with WiFi:** some "smart" USB charging stations in the 2022 era added WiFi monitoring.
3. **Smart desk lamp:** Govee and similar brands used various Shenzhen ODM modules for WiFi-connected desk lamps.

### How to identify

- Check desk area for a power strip or outlet with an app indicator light or WiFi symbol
- DNS capture: phone-home domain identifies the brand
- Try HTTP on non-standard ports: `curl http://192.168.1.155:4096/` (some Intellirocks products used port 4096)

---

## 4. Espressif ESP32 devices (x2)

| # | MAC | IP | First Seen | Signal |
|---|-----|-----|-----------|--------|
| 1 | `d4:d4:da:74:14:ec` | .251 | 2023-08-24 | -53 dBm |
| 2 | `d4:d4:da:73:ec:cc` | .253 | 2025-06-02 | -48 dBm |

- **AP:** Both on Living Room AC LR, 2.4GHz
- **Hostname:** "espressif" (source: `usw`, reported by the UniFi *switch*, not the AP, which is unusual)
- **Traffic:** Both at 3.5 MB, nearly identical despite 2-year age gap
- **Ports:** Not Shelly, not Tasmota, no HTTP at all

ESP32 is the most common IoT microcontroller, used in hundreds of commercial products and DIY projects. The Espressif OUI means the product vendor didn't register their own MAC range (common for smaller brands).

The `hostname_source: usw` (switch) is a distinctive clue: most WiFi clients get their hostname from the AP (`uap`) or DHCP. This could mean these devices are associated with a wired segment via the switch, or the switch is the DHCP relay that first saw them.

The 2-year gap between first-seen dates means these are almost certainly different products.

### Top candidates (2023 device)

1. **Govee LED strip controller:** Govee extensively uses ESP32, shows up as Espressif, cloud-only, 2.4GHz. Very common in living rooms.
2. **Smart plug** (Meross, generic Tuya): many ESP32-based plugs keep Espressif OUI.
3. **Matter/Thread accessory:** ESP32-S3/C3 used for bridging near the Apple TV (Thread border router).

### Top candidates (2025 device)

1. **Newer Matter-native device:** ESP32-C6 with native Thread/Matter is standard in 2025-era smart home products.
2. **Another Govee or Meross product:** a second controller or plug added later.

### How to identify

- Walk the living room area looking for LED strip controllers, smart plugs, or small devices near the TV/entertainment center
- Check phone for Govee, Meross, or Smart Life/Tuya apps
- The `usw` hostname source might mean they're near the switch, so check devices near the media cabinet

---

## Next steps

The fastest path to identifying all of these:

1. **Check phone apps:** Cync/C by GE, Wyze, Govee, Meross, Smart Life/Tuya, or any "smart home" app would immediately identify a batch of devices
2. **Physical walkthrough:** three rooms to check:
   - **Tracy Office:** 2 WNC plugs
   - **Living Room:** 1 WNC plug + 2 ESP32 devices
   - **Josh Office:** 1 WNC plug + Globalscale + Intellirocks
3. **UniFi UI** → Clients → any online device → Activity tab for phone-home DNS domains
4. **DNS interception:** mirror traffic from one device and capture DNS queries; a single domain like `api.cync.com` or `api.wyze.com` identifies the entire product line
