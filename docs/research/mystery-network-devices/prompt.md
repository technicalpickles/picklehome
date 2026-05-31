# Mystery Network Devices: Identifying Unknown WiFi Clients by OUI and Behavior

I have several unidentified devices on my home network. I've already used OUI vendor lookup, nmap service scanning, mDNS/Bonjour discovery, and ARP table hostnames to identify most of my devices, but these remain mysteries. I'd like help figuring out what they might be based on the clues I have.

## My setup

- UniFi network: 4 APs (AC Pro, AC LR, AC HD), USG gateway
- Residential, suburban, single-family home
- Known smart home ecosystem: Lutron Caseta (RF, not WiFi), Philips Hue Bridge, Sonos, Ecobee thermostats, Nest doorbell/camera, LG smart appliances, Apple TV, Nintendo Switches, various Apple devices

## The mystery devices

### 1. Four identical WNC "connect" devices

- **OUI:** Wistron Neweb Corporation (WNC), `2c:9f:fb:xx:xx:xx`
- **Count:** 4 devices, sequential-ish MACs suggesting same manufacturing batch
- **First seen:** All on 2021-08-17 (same day, installed together?)
- **Band:** All 2.4GHz only
- **Hostname:** "connect" (source: AP-assigned, not device-provided)
- **Ports:** No open TCP ports detected by nmap
- **Traffic:** Low but consistent
- **Location:** Various APs around the house

WNC makes embedded WiFi modules for other brands; they don't sell consumer products directly. The "connect" hostname and same-day appearance of all four suggest a kit of devices installed together.

**What I'd like to know:**
- What consumer products from ~2021 use WNC WiFi modules and come in sets of 4?
- The hostname "connect": do any smart home products use that as a default hostname?
- Could these be smart plugs, sensors, contact sensors, or similar IoT devices sold as a multi-pack?
- Any specific brands known to use WNC modules? (e.g., Wyze, Wemo, TP-Link Kasa, other smart home brands)

### 2. Globalscale Technologies device

- **OUI:** Globalscale Technologies (`f0:ad:4e:xx:xx:xx`)
- **IP:** .119
- **First seen:** December 2021
- **Band:** 2.4GHz, Josh Office AP
- **Traffic:** Very low
- **Ports:** No open TCP ports
- **mDNS:** No name advertised

Globalscale makes embedded ARM platforms (Marvell-based). They're known for single-board computers and IoT modules.

**What I'd like to know:**
- What consumer products use Globalscale Technologies WiFi/networking modules?
- Could this be part of a smart home hub, bridge, or gateway?
- Any known products from 2021 era that use Globalscale chipsets?

### 3. Shenzhen Intellirocks device

- **OUI:** Shenzhen Intellirocks Tech (`d4:ad:fc:xx:xx:xx`)
- **IP:** .155
- **First seen:** November 2022
- **Band:** 2.4GHz, Josh Office AP
- **Traffic:** Low
- **Ports:** No open TCP ports
- **mDNS:** No name advertised

**What I'd like to know:**
- What does Shenzhen Intellirocks manufacture? What consumer products contain their modules?
- Is this likely a smart plug, sensor, camera, or some other IoT device?
- Any known brand-name products that use Intellirocks WiFi modules?

### 4. Two Espressif (ESP32) devices

- **OUI:** Espressif (`d4:d4:da:xx:xx:xx`)
- **IPs:** .251 and .253
- **Band:** 2.4GHz, Living Room AP
- **First seen:** One in 2023, one in 2025
- **Ports:** No open TCP ports
- **mDNS:** No names advertised

ESP32 is an extremely common IoT microcontroller, used in everything from commercial smart home products to DIY projects.

**What I'd like to know:**
- What mass-market consumer products use ESP32 with Espressif's own OUI (vs. products that get their own OUI)?
- Common smart home devices that show up as Espressif on the network: smart plugs, LED controllers, sensors?
- Since these are in the Living Room near known smart home gear, could they be part of existing ecosystems (Hue accessories, smart plugs, etc.)?

## What would help me narrow it down

For each device category, I'd appreciate:

1. **Most likely candidates:** ranked list of consumer products that match the OUI + behavior profile
2. **Distinguishing tests:** anything I can try beyond nmap/mDNS to identify them (specific ports to probe, HTTP endpoints to try, UPnP discovery, SSDP, etc.)
3. **Physical identification tips:** if these are likely smart plugs or sensors, I could do a walk-through of the house looking for devices with indicator lights or labels
4. **Timeline correlation:** products that were commonly sold/installed as sets in the 2021-2022 timeframe

## Context that might help

- I don't recall installing anything as a set of 4 in August 2021, but it was clearly a batch setup
- The Josh Office AP has two mystery devices (Globalscale + Intellirocks), could be related to desk/office accessories
- The Living Room ESP32 devices appeared years apart, so they're probably different products
- All mystery devices are 2.4GHz-only, which is typical for IoT/embedded WiFi
- None advertise mDNS services or have open TCP ports, suggesting they phone home to a cloud service rather than offering local APIs
