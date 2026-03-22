This is a fun puzzle. Let me go through each device category with ranked candidates, diagnostic ideas, and physical identification strategies.

---

## 1. Four WNC "connect" devices

**Most likely candidates, ranked:**

**① GE Cync (formerly C by GE) smart plugs or bulbs — high confidence**
Cync products were aggressively sold in 4-packs around 2020–2021, use WNC embedded WiFi modules, operate 2.4GHz-only, use purely cloud-based control (no local API, no open ports), and would show a generic AP-assigned hostname rather than advertising their own. The timing aligns perfectly with the 2021 GE rebranding push when Cync was heavily marketed at Home Depot/Costco. Smart plug 4-packs were their flagship bundle.

**② Wyze Plug (4-pack)** — WNC has confirmed ties to Wyze hardware. Wyze Plugs v1 and v2 launched in that era, were sold specifically in 4-packs, are cloud-only (no local API, no mDNS), and the "connect" hostname matches their generic naming behavior.

**③ TP-Link Kasa EP25/KP400 variants** — Some Kasa manufacturing runs used WNC modules, though TP-Link is more likely to have a device-provided hostname like "TP-LINK_xxxx." Less likely but worth considering if the Kasa cloud endpoint shows up in traffic analysis.

**Physical hunt:** Look for outlet-mounted smart plugs with small LED status lights — specifically 4 plugs that look identical. Cync plugs have a very distinctive small circular button; Wyze plugs have a square button with a "W" logo. If you find 4 matching plugs with no obvious brand logo visible, check the back/bottom for small print.

**Distinguishing tests:**
- **DNS query capture is your fastest path.** Mirror traffic from those IPs in UniFi and run `tcpdump -i any -nn 'src host <IP> and port 53'`. Cync phones home to `\*.gelighting.com` or `\*.cync.com`; Wyze uses `\*.wyze.com`. One DNS query reveals everything.
- Try HTTP on port 80: `curl http://<IP>/` — unlikely to respond, but worth 5 seconds.
- Check UniFi's "Client Details" for the DHCP hostname field — UniFi labels these "connect" because that's what the device sends in its DHCP Option 12 hostname request. That word "connect" is the device's own hostname, not AP-assigned — which actually narrows it considerably. Search for smart home devices that broadcast the DHCP hostname "connect" literally.

---

## 2. Globalscale Technologies — Josh Office

**Most likely candidates, ranked:**

**① Some variant of a smart home hub/bridge using Marvell Armada chipset** — Globalscale is almost exclusively a module supplier for embedded gateways, not end-user IoT nodes. Their Marvell-based modules appeared in several commercial/prosumer IoT gateway products circa 2021. The office location and very low traffic suggests a always-on bridge device, not a sensor.

**② Powerline adapter with WiFi** — Globalscale made Marvell-based chipsets for HomePlug/powerline-over-Ethernet products that added WiFi. If there's a powerline adapter in the office, this would fit perfectly — they're easy to forget because they look like plain wall adapters.

**③ A router/AP in client mode or a travel router** — Less likely given your UniFi setup, but a travel router left plugged in would show this profile.

**Distinguishing tests:**
- `nmap -sU -p 1900 <IP>` — UPnP/SSDP. Gateways and powerline adapters often respond to SSDP even when they don't expose TCP services.
- `nmap -p 80,443,8080,8443,23,22 <IP>` with `-Pn` flag to force scan even if ICMP is blocked.
- Check if the device has an associated wired connection — in UniFi, look at the client's "Uplink" field. A powerline adapter would show as wireless client but might have wired clients behind it.
- Physical: look for a plug-in adapter in the office that has both a coax/ethernet port AND a WiFi antenna nub.

---

## 3. Shenzhen Intellirocks — Josh Office

**Most likely candidates:**

**① A smart power strip or smart outlet for a desk** — Intellirocks is a Shenzhen ODM that OEMs products for brands including some sold under house brands at Amazon, Walmart, etc. Their primary product category is smart plugs and power strips. An office desk with a "smart" power strip you may have bought for surge protection + smart switching would fit the profile.

**② A USB charging hub with smart features** — Some "smart" USB charging stations in the 2022 era added WiFi monitoring/control via Intellirocks modules.

**③ A desk lamp with WiFi** — Some Govee and similar brand desk lamps in 2022 used various Shenzhen ODM modules.

**Physical hunt for the office:** Look for anything plugged in that you may not think of as a "network device" — power strip, charging hub, desk lamp. If it has a small app-controlled feature, it might be this.

**Distinguishing tests:**
- Same DNS capture approach as above — phone-home domain will identify the brand.
- Try `curl http://<IP>:80` and `curl http://<IP>:4096` — some Intellirocks-based products run a local HTTP server on non-standard ports.
- `nmap -p 4096,9999,6668 <IP> -Pn` — smart plugs of this era commonly used these ports for local control before they dropped local APIs.

---

## 4. Two Espressif ESP32 devices — Living Room

These are your most interesting ones because ESP32 appears in both commercial and DIY products. The two-year gap between first-seen dates strongly suggests they're different devices.

**Most likely for the 2023 device:**

**① Shelly smart plug or relay** — Shelly devices (Shelly Plug S, Shelly 1, etc.) use ESP32 or ESP8266, appear with Espressif OUI when they haven't gotten their own, are extremely popular for home automation, and critically: Shelly's local API is HTTP-based on port 80. If `curl http://<IP>/shelly` returns JSON, you found it immediately. This is your highest-yield test.

**② Govee LED controller** — Govee smart LED strips and bulbs from 2022–2023 extensively use ESP32, show up with Espressif OUI, use 2.4GHz only, and have no local API (cloud-only). Very common living room device.

**③ A matter/Thread bridge or smart home accessory** — Several 2023-era smart home accessories use ESP32-C3 or ESP32-S3 for Thread/Matter bridging, which would explain the living room location near your Apple TV (which acts as a Thread border router).

**Most likely for the 2025 device:**

**① A newer Matter-native device** — By 2025, ESP32-C6 (with native Thread/Matter support) is very common in mass-market smart home products. This could be a recently bought smart plug, sensor, or bulb.

**② A DIY device someone set up** — If anyone in the household is into home automation projects, an ESP32-based DIY device (ESPHome, Tasmota, etc.) would match this exactly. Tasmota devices respond to `curl http://<IP>/cm?cmnd=Status` with JSON.

**Distinguishing tests — start here:**
```
# Shelly check (highest yield)
curl http://<IP>/shelly

# Tasmota check
curl http://<IP>/cm?cmnd=Status

# Generic HTTP
curl http://<IP>/

# Try common smart plug ports
nmap -p 80,443,1883,4096,9999,55443 <IP> -Pn
```
- **SSDP discovery:** `nmap -sU -p 1900 --script=upnp-info <IP>` — many ESP32 devices respond to SSDP even without mDNS.

---

## General strategy: traffic analysis beats everything

Your fastest path to all four mysteries is **DNS query interception**, which UniFi makes easy:

1. In UniFi Network → Settings → Traffic Management, create a **Traffic Rule** that mirrors traffic from each mystery IP to a monitoring VLAN, or
2. Use the **UniFi Deep Packet Inspection** dashboard — under Client Details for each device, the "Activity" tab often shows the top domains the device is phoning home to, even without a mirror port.

A single DNS hostname like `api.cync.com`, `api.shelly.cloud`, or `ota.wyze.com` from one of these IPs tells you the entire product line instantly.

---

## Quick summary table

| Device | Top Candidate | Fastest Test |
|--------|--------------|--------------|
| 4× WNC "connect" | GE Cync smart plugs (4-pack) | DNS capture: look for `*.cync.com` |
| Globalscale office | Powerline WiFi adapter / smart hub | SSDP probe; check for wired clients behind it |
| Intellirocks office | Smart power strip/desk outlet | DNS capture; try HTTP port 4096 |
| ESP32 (2023) | Shelly plug or Govee LED | `curl http://<IP>/shelly` |
| ESP32 (2025) | Matter device or new smart plug | nmap ports + Tasmota/Shelly probes |

The "connect" hostname on the WNC batch is the most tantalizing clue — if you can confirm those are Cync plugs, a walk through the house counting identical smart plugs should take about 2 minutes to confirm.
