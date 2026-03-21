# 2.4 GHz Transmit Power Tuning — Research & Rationale

## Background

On 2026-03-17, 5 GHz transmit power was reduced from max to medium on all APs to address
iPhone roaming churn (see CHANGELOG.md). At the time, 2.4 GHz was deliberately left at max
with the reasoning: *"lower frequency penetrates walls better; reducing risks dead spots."*

On 2026-03-21, we revisited this decision after observing:
- 30% RX utilization on 2.4 GHz (neighbor interference consuming airtime)
- 25-37% retry rates on 2.4 GHz across most APs
- Living Room AC LR and Upstairs AC HD co-channel on ch 6, separated by one floor
  with an open stairwell — each AP's transmissions appearing as "neighbor noise" to the other

## What We Changed

1. **Moved Upstairs 2.4 GHz from ch 6 → ch 11** — eliminated co-channel interference
   between Living Room and Upstairs. Ch 11 was available (Porch AP is offline).
   Immediate result: Upstairs retries dropped from 33% to 0%.

2. **Reduced Living Room AC LR 2.4 GHz to medium** (~13 dBm, down from 17 dBm max).
   All 2.4 GHz clients had strong signal (-36 to -55 dBm), so 4 dB headroom to spare.

3. **Reduced Upstairs AC HD 2.4 GHz to medium** (~16 dBm, down from 19 dBm max).
   Only 2 clients on this radio, both strong signal.

## Research Findings

### Ubiquiti Official Guidance

From [Optimizing WiFi Connectivity](https://help.ui.com/hc/en-us/articles/221029967):
- Use **medium transmission power** on APs in multi-AP environments to prevent mutual interference
- 2.4 GHz should remain on **20 MHz channel width** (already configured)
- Use only channels 1, 6, and 11 (no overlap)

From [Resolving High Airtime Utilization](https://help.ui.com/hc/en-us/articles/30266615758743):
- Reduce transmit power to limit cell size and decrease co-channel interference
- High power creates more overlap → more contention → more retries

### Community Best Practices

From [HostiFi Wireless Best Practices](https://support.hostifi.com/en/articles/6441143-unifi-wireless-best-practices):
- For multi-AP deployments: *"more APs turned down can be better than fewer with power turned up"*
- High TX power creates the **"near-far problem"** — AP reaches client but client can't reply
  at the same range, causing asymmetric links and upstream retries
- 2.4 GHz IoT devices (ESP8266, smart plugs) typically transmit at 10-12 dBm; matching AP
  power closer to client capability improves reliability

From community discussions ([1](https://community.ui.com/questions/AP-LR-Should-I-reduce-transmit-power/7fad1601-e6f0-4c96-bfdc-08ba42456fd4), [2](https://community.ui.com/questions/UAP-AC-LR-Home-Is-Dont-Set-TX-Power-to-Full-for-2-4Ghz-still-valid-advice/e07e6c46-e8ba-472f-8be4-f125e3ea842e)):
- General consensus: **Low or Medium** for 2.4 GHz in residential multi-AP setups
- AC-LR model specifically has high-gain directional antenna that amplifies the problem —
  at max power it reaches much further than needed in a home

### Why the Original "Leave Max" Decision Was Wrong

The concern was dead spots from reduced 2.4 GHz range. In practice:
- All 2.4 GHz clients on Living Room AP had signal from -36 to -55 dBm (strong to excellent)
- A 4 dB reduction still leaves every client well above the -70 dBm threshold for reliable 2.4 GHz
- The AC-LR's "long range" antenna is a liability in this layout — horizontal mount on
  ground floor + open stairwell = signal blasts straight up into Upstairs AP's coverage zone
- The real risk isn't dead spots, it's **excessive overlap creating retries and wasted airtime**

## AP Model Characteristics

| Model | Name | 2.4 GHz Max | 2.4 GHz Medium | Antenna Pattern |
|---|---|---|---|---|
| U7LR | AC Long Range | 24 dBm | ~13 dBm | High-gain, focused beam |
| U7HD | AC High Density | 25 dBm | ~16 dBm | Wide, uniform coverage |
| U7PG2 | AC Pro | 22 dBm | ~15 dBm | Standard omnidirectional |

The AC-LR has the highest effective 2.4 GHz range due to its antenna gain, despite a lower
max power than the AC-HD. This makes it the most important AP to reduce in a multi-floor setup.

## Power Level Reference

All APs report a min of 6 dBm. UniFi's named modes map approximately to:
- **Low**: ~6-8 dBm
- **Medium**: ~50-65% of max (model-dependent)
- **High**: ~80-90% of max
- **Max**: full power
- **Auto**: controller adjusts dynamically (not recommended — can oscillate)

## Follow-up Checks

- After 24h: `just unifi checkup` — compare retry rates to pre-change baseline
- Verify no IoT devices dropped off: check 2.4 GHz client counts on Living Room and Upstairs
- If Porch AP comes back online on ch 11, may need to re-plan 2.4 GHz channel assignments
  (only 3 non-overlapping channels: 1, 6, 11)
