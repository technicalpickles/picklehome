# WiFi Survey Tools Research

Research on tools for creating floor plans and WiFi signal heatmaps for the home
network. Conducted 2026-03-18.

---

## Context

- **Problem:** Existing diagnostics (`wifi-diag.py`, `just unifi wifi`) lack spatial context.
  We know signal strength at a point but not coverage across the house.
- **Goal:** Create a floor plan with WiFi heatmap overlay to identify dead zones and
  validate AP placement decisions.
- **Existing asset:** House floor plan already exists in MagicPlan.

---

## Bottom Line

**WiFiMan Floor Plan Mapper is blocked**: it requires a UniFi Cloud Gateway (UDM/UDR/UCG
series), and we have a CloudKey Gen2 + USG. Options: upgrade to a UCG-Ultra (~$129),
try WiFiMan Wizard (~$49, may or may not unlock it), or use NetSpot (~$149, vendor-agnostic).

Use **Design Center** (design.ui.com) as the hub for a reusable floor plan image that
can be shared across tools. This is free and works regardless of hardware.

---

## Tools

### WiFiMan (Ubiquiti): Free Mobile App

WiFiMan is Ubiquiti's free network analysis app. It has two distinct spatial features
that are easily confused:

#### Floor Plan Mapper

- **Requires:** LiDAR-equipped device (iPhone 12 Pro+, iPad Pro 2020+) **AND** a UniFi
  Cloud Gateway (UDM, UDM-Pro, UDM-SE, UDR, UCG-Ultra, UCG-Max, UniFi Express)
- **Does NOT work with CloudKey + USG**: the CloudKey is a "UniFi Console" but not a
  "Cloud Gateway." Ubiquiti gates this feature to the all-in-one gateway+controller devices.
- **How it works:** Hold phone at eye level, walk slowly through the space. LiDAR builds
  a 3D floor plan in real-time with signal strength heatmap overlay.
- **Create floor plans via:** LiDAR/AR scan, photo upload, or built-in sketch tool
- **Export:** Can export/share heatmaps as images (added v1.34, March 2025)
- **Limitation:** Signal strength only: no noise, SNR, or channel overlap metrics

**How to access:** "Floor Plan" tab in bottom navigation (requires both LiDAR device and
Cloud Gateway on the network). Without a Cloud Gateway, the app shows: "Floor Plan
Unavailable: Connect to a network served by UniFi Gateway Console or use WiFiman Wizard
for advanced signal analysis."

#### Signal Mapper (different feature)

- **Requires UniFi Cloud Gateway** (UDM, UDR, UDM-Pro, UDM-SE) on the network
- 2D path-based tracking with per-AP roaming data
- This is the feature behind the "must be connected to UniFi gateway" message

#### WiFiMan Wizard (hardware accessory, ~$49)

- Portable spectrum analyzer for 2.4 GHz and 5 GHz (no 6 GHz)
- Connects via Bluetooth, shows channel usage and interference
- Not required for floor plan surveys

**App versions:** iOS and Android (full features), Desktop (no floor plan), Web (speed test only).

### NetSpot: Paid Desktop/Mobile App

Professional WiFi site survey tool. Free tier is very limited; survey features
require Pro ($149+) or Enterprise ($349+).

- **Survey method:** Continuous walk recording (more automated than WiFiMan's tap-per-point)
- **Metrics:** Signal, noise, SNR, channel overlap, PHY mode, band coverage
- **Floor plan input:** Upload any image
- **Predictive planning:** Pro+ can simulate AP placement before installation
- **Export:** PDF, CSV, detailed reports
- **No LiDAR required**
- **No UniFi dependency**: vendor-agnostic

### UniFi Design Center: Free Web Tool

Pre-deployment planning tool at [design.ui.com](https://design.ui.com/).

- Upload a floor plan image, trace walls and rooms, set scale
- Drag-and-drop Ubiquiti products to simulate WiFi coverage heatmaps
- Generates equipment lists and cost estimates
- **Export:** PDF, PNG, CSV
- **Key role:** PNG export can be used as floor plan background in other tools (NetSpot, etc.)
- Floor plans can be imported INTO InnerSpace (but not the reverse)
- No hardware required; anyone can use it

### UniFi InnerSpace: Free (on UniFi Console)

Post-deployment live mapping tool. Runs on UniFi OS 3.2+ consoles.

- Upload or draw floor plans, place adopted devices (APs, cameras, switches)
- Draw walls and windows for coverage modeling
- View live WiFi coverage heatmaps from real devices
- **No export**: floor plans are locked within InnerSpace (active community feature request)
- Can import floor plans from Design Center

---

## Comparison

| Feature | WiFiMan | NetSpot | Design Center | InnerSpace |
|---|---|---|---|---|
| Cost | Free | $149+ | Free | Free (needs console) |
| Floor plan creation | LiDAR scan, photo, sketch | Upload image | Upload + trace walls | Upload or draw |
| Heatmap source | Real walk survey | Real walk survey | Simulated | Live from devices |
| Metrics | Signal only | Signal, noise, SNR, etc. | Simulated coverage | Live signal |
| Export | Image | PDF, CSV, reports | PDF, PNG, CSV | None |
| Requires UniFi | No (Floor Plan Mapper) | No | No | Yes |
| Requires LiDAR | Yes | No | No | No |

---

## Recommended Workflow (given CloudKey Gen2 + USG setup)

1. **Design Center** (design.ui.com): Upload MagicPlan export, trace walls, place APs.
   Creates a reusable PNG floor plan. Simulated coverage for free AP placement planning.
2. **NetSpot**: Import the Design Center PNG as floor plan background, do a real walk
   survey. Vendor-agnostic, no UniFi hardware dependency. Multi-metric (signal, noise,
   SNR, channel overlap). This is the purchase gate from the wifi-survey-agent-experiment
   plan (~$149 for Pro).
3. **If/when upgrading to a Cloud Gateway (UCG-Ultra, ~$129):**
   - WiFiMan Floor Plan Mapper becomes available (free LiDAR heatmap)
   - InnerSpace becomes available (live coverage monitoring)
   - Both can import floor plans from Design Center

---

## References

- [WiFiMan iOS App](https://apps.apple.com/us/app/ubiquiti-wifiman/id1385561119)
- [Using WiFiMan, Ubiquiti Help Center](https://help.ui.com/hc/en-us/articles/205204150-Using-WiFiman)
- [UniFi Design Center](https://design.ui.com/)
- [InnerSpace Guide, Securing the Universe](https://securingtheuniverse.com/2025/11/10/unifi-innerspace-managing-floorplans-and-network-coverage/)
- [WiFiMan Wizard Store Page](https://store.ui.com/us/en/products/wm-w)
