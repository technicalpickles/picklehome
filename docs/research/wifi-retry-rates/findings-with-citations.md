# WiFi TX Retry Rates: What's Normal, What's a Problem?

**A practical framework for interpreting 802.11 retry rates on UniFi and other enterprise-lite wireless networks.**

---

## Context: The Scenario

This guide is built around a common real-world situation: a UniFi network (4 APs — AC Pro, AC LR, AC HD — managed by a USG) in a residential suburban environment, serving a mix of 2.4 GHz and 5 GHz clients. One example client illustrates the central puzzle:

| Metric | Value |
|---|---|
| Device | iPhone, 5 GHz, 802.11ac, 2 spatial streams |
| AP | UniFi AC LR, channel 149, 40 MHz width |
| Signal (RSSI) | −64 dBm |
| SNR | 40 dB |
| TX Rate | 216 Mbps (MCS 5) |
| RX Rate | 180 Mbps |
| TX Retry Rate | 19.2% |
| UniFi Satisfaction Score | 99 |

The signal and SNR look healthy. The satisfaction score is near-perfect. But the retry rate looks high — especially compared to other 5 GHz clients on the network showing 0–6%. Meanwhile, some 2.4 GHz IoT devices show 30–40%.

What follows is a framework for making sense of these numbers.

---

## 1. Baseline Expectations: What Retry Rates Are Normal?

There is no single official threshold defined in the IEEE 802.11 standard for an "acceptable" retry rate. However, industry-accepted norms have converged around general ranges based on band and environment.

### 5 GHz Band

- **Under 5%** — Excellent. Clean RF environment, well-placed AP, minimal contention.
- **5–10%** — Healthy. Normal for a moderately loaded network.
- **10–15%** — Worth monitoring. Not necessarily user-impacting, but trending upward.
- **15–25%** — Investigate. Something specific is likely contributing — contention, hidden nodes, client issues, or A-MPDU subframe retry inflation (see [Section 5](#5-unifi-specific-considerations)).
- **Above 25%** — Actively problematic. Likely causing throughput loss and latency spikes.

### 2.4 GHz Band

- **Under 15%** — Reasonable for a suburban residential environment.
- **15–25%** — Common, especially with low-power IoT devices that have single spatial streams and poor antenna designs.
- **25–40%** — Unfortunately typical for the 2.4 GHz band in areas with dense overlapping neighbor networks. Often unavoidable without moving clients to 5 GHz.
- **Above 40%** — Severely degraded. Likely causing dropped connections and very poor throughput.

The key insight is that retry rate is **relative to the band and environment**, not an absolute metric. A 12% retry rate on 5 GHz is more concerning than 12% on 2.4 GHz. As one Extreme Networks engineer noted in a support thread, acceptable retry rates are generally considered to be under 20% for non-critical applications, and 2.4 GHz environments are more susceptible to high contention and co-channel interference due to the limited number of non-overlapping channels ([Extreme Networks Community](https://community.extremenetworks.com/t5/extremewireless-wing/understanding-high-quot-retry-percentage-quot-values/td-p/89545)).

A retry rate of 10–30% is common across real-world deployments ([CSB Technology Partners](https://minnow-crow-x23t.squarespace.com/blog/wi-fi-retry-rate)). The goal is always to push the number as low as possible, but context determines when action is needed.

---

## 2. User Impact Thresholds: When Do Retries Become Perceptible?

The relationship between retry percentage and user experience is **nonlinear** and depends heavily on the application type.

### Bulk Throughput (Downloads, Streaming Buffers)

Retries up to about 15–20% on 5 GHz are largely absorbed by the link-rate headroom. If the negotiated TX rate is high enough, the effective throughput after retries still exceeds what most applications demand.

**Example from the scenario above:** A 19% retry rate on a 216 Mbps link yields roughly 175 Mbps effective throughput — more than sufficient for 4K streaming (~25 Mbps), large downloads, or any typical residential use.

### Latency-Sensitive Traffic (Video Calls, Gaming, VoIP)

Retries start mattering much sooner for these applications. Each retry adds a frame transmission time plus a random backoff period (governed by the exponential backoff algorithm in CSMA/CA). The contention window approximately doubles on each retry attempt, potentially adding significant per-frame delay.

- **10–15% retries:** Occasional latency spikes of 20–50 ms above baseline. Mostly imperceptible for video calls but may cause micro-stutters in competitive gaming.
- **15–25% retries:** Video calls may show intermittent freezes; VoIP quality degrades noticeably.
- **Above 25%:** Consistent packet loss and latency that degrades real-time applications significantly.

**The critical nuance is burstiness.** A steady 15% is less damaging than a rate that's 2% most of the time with bursts to 40%. UniFi's reported retry rate is a rolling average that smooths over these bursts, masking the worst-case moments.

### For the Example Client

The 99 satisfaction score combined with strong signal and SNR strongly suggests this iPhone user is not experiencing perceptible problems. The retries are eating into headroom, not into usable capacity.

---

## 3. Retries vs. Other Metrics: A Diagnostic Triage Framework

When someone reports "the internet is slow," these metrics should be evaluated in a specific order. Here is a ranking from most to least useful as a *leading indicator* of user-perceived problems.

### Tier 1: Signal-to-Noise Ratio (SNR)

**The single best predictor of link quality.** SNR directly determines which MCS rates the radio can reliably decode.

| SNR Range | Expected Behavior |
|---|---|
| Above 40 dB | Excellent — highest MCS rates sustainable |
| 25–40 dB | Good — most MCS rates achievable |
| 15–25 dB | Marginal — MCS rate drops, rising retries |
| Below 15 dB | Poor — barely usable connection |

The example client's 40 dB SNR is excellent.

### Tier 2: TX/RX Rate (MCS Index)

The negotiated MCS rate tells you what the radio layer has decided is achievable. If a client is stuck at MCS 0–2 despite decent signal, something is wrong — interference, client capability limitations, or band steering issues. The example's MCS 5 at 2 spatial streams (216 Mbps on 40 MHz) is reasonable but not the theoretical maximum, suggesting some degree of rate adaptation is already occurring.

### Tier 3: Retry Rate

Retry rate is a **symptom**, not a root cause. It tells you that frames are failing but not *why* they are failing. It is useful for confirming a problem exists but less useful for isolating the cause. Always interpret retry rate alongside SNR and MCS.

### Tier 4: Signal Strength (RSSI)

RSSI is the crudest metric. It tells you about path loss but reveals nothing about the noise floor or interference environment. A client at −64 dBm in a quiet environment performs very differently from −64 dBm in a noisy one. Always prefer SNR over raw RSSI.

### Tier 5: UniFi Satisfaction Score

The satisfaction score is a proprietary composite metric useful for fleet-level monitoring but too opaque for per-client troubleshooting. It appears to weight signal strength and expected throughput more heavily than retry rate, which is why a score of 99 coexists with 19% retries in the example.

### Practical Triage Workflow

1. **Rule out WAN/routing first.** Run a wired speed test to the gateway. If the problem exists wired, it's not a WiFi issue.
2. **Check the client's SNR.** Low SNR → coverage/placement problem.
3. **Check the MCS rate.** Low MCS with good SNR → interference or client driver issue.
4. **Check retries.** High retries with good SNR and MCS → medium access layer problem (contention, hidden nodes, co-channel interference).
5. **Check channel utilization.** High utilization → airtime congestion. Consider channel changes or load balancing.

---

## 4. High Retries + Good Signal: Root Cause Analysis

The combination of good signal, good SNR, and elevated retries is one of the most common and instructive troubleshooting scenarios. It points to a specific subset of causes.

### 4.1 Co-Channel Contention (CCI)

**Most likely explanation in the example scenario.**

Channel 149 at 40 MHz width (149+153) is a common 5 GHz channel choice. If a neighbor's AP operates on the same channel, both APs share airtime via CSMA/CA. When both attempt to transmit simultaneously — or when a client can't decode a frame because it simultaneously received energy from a neighbor's AP — retries result despite good signal from the serving AP.

The diagnostic step is to check channel utilization in UniFi's RF Environment view. High "other BSS" utilization on channel 149 confirms CCI.

**Reference:** The CSMA/CA mechanism requires stations on the same channel to take turns transmitting. If they can detect each other at 3 dB above the noise floor, they must defer ([Wikipedia — CSMA/CA](https://en.wikipedia.org/wiki/Carrier-sense_multiple_access_with_collision_avoidance)). This works well when all stations can hear each other, but breaks down in hidden node scenarios (see below).

### 4.2 Hidden Node Problem

The hidden node problem occurs when two clients (or a client and a neighbor's AP) can both communicate with the serving AP but cannot detect each other's transmissions. They may transmit simultaneously, causing frame collisions at the AP. The serving AP registers these as failed transmissions requiring retries.

RTS/CTS can mitigate this by establishing a reservation-based protocol: a station sends a Request to Send, the AP responds with a Clear to Send (which all stations in range of the AP can hear), and other stations defer for the indicated duration. However, RTS/CTS is disabled by default on most UniFi configurations and adds significant protocol overhead ([Wikipedia — Hidden Node Problem](https://en.wikipedia.org/wiki/Hidden_node_problem)).

### 4.3 Client-Side Behavior

Client devices contribute to retries in ways that AP-side metrics alone cannot reveal:

- **Power-saving modes:** iPhones and other mobile devices may delay acknowledgments when in low-power states, causing the AP to record a timeout and retry even if the original frame was received.
- **Driver/firmware quirks:** Some client radios have known issues with specific MCS rates or channel widths.
- **Asymmetric link budgets:** Client devices have lower transmit power and weaker antennas than APs. The AP may transmit successfully to the client, but the client's ACK (sent at lower power) may not reach the AP reliably, triggering a retry. This is the classic "the client is the weak link" scenario described in enterprise wireless discussions ([Extreme Networks Community](https://community.extremenetworks.com/t5/extremewireless-wing/understanding-high-quot-retry-percentage-quot-values/m-p/89546)).

### 4.4 A-MPDU Aggregation Inflation

**Likely the biggest factor inflating the reported 19% in the example.**

With 802.11n/ac, frames are typically sent as Aggregate MPDUs (A-MPDUs). A single A-MPDU can contain dozens of subframes, and the receiver acknowledges them individually via a Block ACK bitmap. If an A-MPDU contains 20 subframes and 4 need retransmission, some implementations report that as a 20% retry rate — even though the Block ACK mechanism handled it efficiently within a single transmission opportunity, and the actual airtime cost was minimal.

See [Section 5](#5-unifi-specific-considerations) for how this specifically affects UniFi reporting.

### 4.5 Multipath and Reflection

Even with strong signal, environments with significant reflections (metal surfaces, glass, certain room geometries) can cause inter-symbol interference. MIMO helps mitigate multipath in many cases, but it doesn't eliminate it entirely, and in some configurations multipath can still degrade frame decoding at higher MCS rates ([Cisco Community](https://community.cisco.com/t5/wireless/high-rssi-high-snr-but-high-data-retries-rate-multipath-effect/td-p/3043878)).

### 4.6 Rate Control Probe Frames

Rate adaptation algorithms like Minstrel-HT (used in the Linux mac80211 subsystem that underlies UniFi APs) periodically "probe" higher MCS rates by sending frames at rates above the current optimum. These probe frames have a high failure rate by design — they're testing whether channel conditions support a faster rate. Failed probes count as retries, contributing a baseline retry percentage that is normal and expected.

Minstrel-HT selects data rates based on a statistical table of sampled results, choosing the rate with the highest throughput and probability of successful delivery ([ResearchGate — Minstrel-HT Evaluation](https://www.researchgate.net/publication/322940194_Evaluation_of_the_minstrel-HT_rate_adaptation_algorithm_in_IEEE_80211n_WLANs)). The algorithm is widely deployed in popular Linux wireless drivers including Ath5k and Ath9k ([IEEE Xplore — Minstrel Performance](https://ieeexplore.ieee.org/document/6362819/)).

---

## 5. UniFi-Specific Considerations

UniFi's retry metric has several known characteristics that differentiate it from what you'd observe in a raw packet capture.

### Driver-Level vs. Air-Level Retries

UniFi reports retries at the **driver/firmware level**, which includes A-MPDU subframe retries. In a packet capture using a monitor-mode adapter, you would see the Retry bit set in the 802.11 Frame Control field, which corresponds to full frame retransmissions. UniFi's controller aggregates retries at the subframe level within A-MPDUs, which typically produces a **higher percentage** than what external measurement would show.

A reported "19% retry rate" in UniFi may correspond to roughly 8–12% in a Wireshark capture, depending on the A-MPDU aggregation depth. This distinction is important and frequently discussed in the UniFi community forums:

- [Access Point Retry Rates — What is Acceptable?](https://community.ui.com/questions/Access-Point-Retry-Rates-What-is-Acceptable/61d64965-af5a-4dd9-87b1-8ddfd73ef971)
- [High TX Retry Rate UNIFI UAP PRO](https://community.ui.com/questions/High-TX-Retry-Rate-UNIFI-UAP-PRO/c8c0a642-e245-43c7-bd30-aa1a7268e23a)
- [Access Point Retry Rate on the Controller Dashboard](https://community.ui.com/questions/Access-Point-Retry-Rate-on-the-controller-dashboard-/07b6e724-2a10-45e7-af3a-dd442fe526e7)
- [Is This Access Point Retry Rate High?](https://community.ui.com/questions/Is-this-Access-Point-Retry-Rate-high/9c81a4c8-cf43-4897-b136-53e17ddeb27d)

### Satisfaction Score Algorithm

UniFi's satisfaction score uses a proprietary formula that Ubiquiti has not fully documented. Community analysis suggests it weights signal strength and expected throughput more heavily than retry rate. This explains why a 99 score can coexist with 19% retries when signal and SNR are strong.

### Rolling Average

The per-client retry counter displayed in the UniFi controller is a **rolling average**, not a point-in-time measurement. It smooths over bursty retry periods, meaning the peak retry rate during congestion windows is likely significantly higher than the displayed value.

### Retry Calculation Pitfalls

Be aware that some reporting tools (not specific to UniFi) calculate retry percentage incorrectly by dividing retry frames by *successful* frames rather than by *total* frames. The correct formula is:

```
Retry % = Retry Frames / (Successful Frames + Retry Frames) × 100
```

Using the incorrect formula (`Retries / Successful`) can produce percentages exceeding 100%, which is nonsensical. This issue is documented in detail by Ben Miller at [Sniff WiFi](https://www.sniffwifi.com/2024/10/wifi-retry-percentage-wrong.html).

---

## 6. Going Deeper: Frame-Level Mechanics and Resources

### Core 802.11 Retransmission Mechanism

When a WiFi device transmits a unicast data frame, it expects an acknowledgment (ACK) from the receiver. If no ACK is received, the transmitter retransmits the frame with the Retry bit set in the Frame Control field. The 802.11 standard defines two retry limits controlled by `dot11ShortRetryLimit` (default: 7) and `dot11LongRetryLimit` (default: 4), where the threshold between "short" and "long" is determined by `dot11RTSThreshold`. After each failed attempt, the contention window (CW) roughly doubles, increasing the random backoff period before the next retry ([NetAlly — 802.11 Retries](https://www.netally.com/wifi-solutions/802-11-retries/)).

For a deep dive into the formal retry mechanics including SRC/SLRC counters and CW progression, the WARP Project's documentation provides an excellent walkthrough with worked examples from the IEEE 802.11-2012 standard: [WARP Project — 802.11 Retransmissions](https://warpproject.org/trac/wiki/802.11/MAC/Lower/Retransmissions).

### Block ACK and A-MPDU Aggregation

Starting with 802.11n, the Block ACK mechanism allows a receiver to acknowledge multiple frames at once using a bitmap. In A-MPDU aggregation, multiple MPDUs are sent in a single transmission opportunity, and the receiver returns a Block ACK indicating which subframes were successfully received. Only the failed subframes need retransmission — a significant efficiency improvement over retransmitting entire aggregate frames ([WiFi Sharks — Block Acknowledgement](https://wifisharks.com/2020/12/26/block-acknowledgement/)).

The interaction between A-MPDU aggregation size and the Block ACK window limit is a subject of active academic research. A thorough analytical model of this interaction and its impact on throughput is presented in: Demystifying the Performance of A-MPDU Aggregation in 802.11 Networks (2021), [Computer Communications, Vol. 180](https://cs.uwaterloo.ca/~brecht/papers/demyst-comp-comm-2021.pdf).

For a practical comparison of A-MSDU vs. A-MPDU aggregation strategies and their retry implications, CBT Nuggets provides a clear explainer: [MSDU or MPDU: Which Is Best Frame Aggregation?](https://www.cbtnuggets.com/blog/technology/networking/msdu-or-mpdu-which-is-best-frame-aggregation).

### Rate Adaptation Algorithms

The IEEE 802.11 standard does not specify how rate adaptation should work — it's left to the implementation. The Minstrel and Minstrel-HT algorithms are the most widely deployed in Linux-based access points (including UniFi, which uses Qualcomm Atheros chipsets with the ath10k driver family). The algorithms work by maintaining a statistical table of per-rate success probabilities and periodically sampling other rates:

- **Minstrel-HT GitHub (user space implementation):** [Minstrel-Blues](https://github.com/thuehn/Minstrel-Blues) — A research project from TU Berlin extending Minstrel-HT with power control. Contains useful documentation on how the base algorithm works.
- **ns-3 Reference Implementation:** [MinstrelHtWifiManager](https://www.nsnam.org/docs/release/3.27/doxygen/classns3_1_1_minstrel_ht_wifi_manager.html) — The network simulator's implementation, with well-documented parameter descriptions.

### Measuring Retries Independently with Wireshark

To get ground-truth retry rates independent of your controller's reporting, capture traffic on a monitor-mode WiFi adapter tuned to the same channel. Use these Wireshark display filters:

- All data frames from a specific client: `wlan.ta == <CLIENT_MAC> && wlan.fc.type == 2`
- Retried data frames from that client: `wlan.fc.retry == 1 && wlan.fc.type == 2 && wlan.ta == <CLIENT_MAC>`

Count both, divide retries by total, and you have the true over-the-air retry rate. A step-by-step guide is available at [SemFio Networks — Calculate 802.11 Retry Rate with Wireshark](https://semfionetworks.com/blog/calculate-802-11-retry-rate-with-wireshark/).

Alternatively, Wireshark's built-in `Wireless >> WLAN Traffic` statistics view can calculate retry rates per station without manual filtering.

### Recommended Books

- **Matthew S. Gast, [*802.11ac: A Survival Guide*](https://www.oreilly.com/library/view/80211ac-a-survival/9781449357702/) (O'Reilly, 2013)** — Covers aggregation, block ACK, channel access, and beamforming in depth. Gast led the development of the 802.11-2012 revision and chaired security task groups at the Wi-Fi Alliance.
- **Matthew S. Gast, [*802.11 Wireless Networks: The Definitive Guide*](https://www.oreilly.com/library/view/80211-wireless-networks/0596100523/) (O'Reilly)** — The comprehensive reference for the full 802.11 MAC and PHY stack.
- **David D. Coleman & David A. Westcott, *CWNA: Certified Wireless Network Administrator Study Guide*** — Excellent for building a systematic understanding of WiFi fundamentals, including retransmission behavior.

### Useful Search Terms for Further Research

- `802.11 CSMA/CA contention window backoff`
- `A-MPDU Block ACK selective retransmission`
- `Minstrel-HT rate adaptation algorithm`
- `802.11 hidden node problem RTS/CTS`
- `dot11ShortRetryLimit dot11LongRetryLimit`
- `UniFi retry rate normal community`
- `WiFi retry rate vs channel utilization`

---

## Summary: The Decision Framework

| Situation | Action |
|---|---|
| 5 GHz, retries < 10%, good SNR | No action needed. |
| 5 GHz, retries 10–20%, good SNR, high satisfaction | Monitor. Likely A-MPDU inflation or minor contention. Check channel utilization. |
| 5 GHz, retries > 20%, good SNR | Investigate actively. Check for CCI, hidden nodes, client-side issues. |
| 5 GHz, retries > 20%, low SNR | Coverage/placement problem. Address signal quality first. |
| 2.4 GHz, retries 15–30%, IoT devices | Often unavoidable. Migrate capable clients to 5 GHz; accept baseline on 2.4 GHz IoT. |
| 2.4 GHz, retries > 40% | Check for non-WiFi interference (microwaves, Bluetooth, baby monitors). Consider changing channels. |
| Any band, high retries + user complaints | Follow triage workflow: rule out WAN → check SNR → check MCS → check retries → check channel utilization. |

**The bottom line:** Treat retry rate as a secondary diagnostic, not a primary alarm. If SNR is above 25 dB, MCS rate is reasonable for the client's capabilities, and the satisfaction score is above 80, retries under 20% on 5 GHz are probably not causing user-perceptible issues. Focus troubleshooting energy on clients with **low SNR + depressed MCS rates + high retries** — that combination is what produces the "slow internet" complaints.

---

## References

1. NetAlly. "802.11 Retries, What Do They Mean?" (2024). https://www.netally.com/wifi-solutions/802-11-retries/
2. Ben Miller / Sniff WiFi. "These Wi-Fi Retry Percentages Are Too Dang High" (2024). https://www.sniffwifi.com/2024/10/wifi-retry-percentage-wrong.html
3. Extreme Networks Community. "Understanding High Retry Percentage Values" (2019). https://community.extremenetworks.com/t5/extremewireless-wing/understanding-high-quot-retry-percentage-quot-values/td-p/89545
4. SemFio Networks. "Calculate 802.11 Retry Rate with Wireshark." https://semfionetworks.com/blog/calculate-802-11-retry-rate-with-wireshark/
5. CSB Technology Partners. "Wi-Fi Retry Rate." https://minnow-crow-x23t.squarespace.com/blog/wi-fi-retry-rate
6. Cisco Community. "High RSSI, High SNR, but High Data Retries Rate (Multipath Effect?)" (2021). https://community.cisco.com/t5/wireless/high-rssi-high-snr-but-high-data-retries-rate-multipath-effect/td-p/3043878
7. WiFi Sharks. "Block Acknowledgement (BA)" (2020). https://wifisharks.com/2020/12/26/block-acknowledgement/
8. CBT Nuggets. "MSDU or MPDU: Which Is Best Frame Aggregation?" https://www.cbtnuggets.com/blog/technology/networking/msdu-or-mpdu-which-is-best-frame-aggregation
9. WARP Project. "802.11/MAC/Lower/Retransmissions." https://warpproject.org/trac/wiki/802.11/MAC/Lower/Retransmissions
10. Wikipedia. "Carrier-sense multiple access with collision avoidance." https://en.wikipedia.org/wiki/Carrier-sense_multiple_access_with_collision_avoidance
11. Wikipedia. "Hidden node problem." https://en.wikipedia.org/wiki/Hidden_node_problem
12. Ubiquiti Community Forums — relevant threads:
    - [Access Point Retry Rates — What is Acceptable?](https://community.ui.com/questions/Access-Point-Retry-Rates-What-is-Acceptable/61d64965-af5a-4dd9-87b1-8ddfd73ef971)
    - [High TX Retry Rate UNIFI UAP PRO](https://community.ui.com/questions/High-TX-Retry-Rate-UNIFI-UAP-PRO/c8c0a642-e245-43c7-bd30-aa1a7268e23a)
    - [Is This Access Point Retry Rate High?](https://community.ui.com/questions/Is-this-Access-Point-Retry-Rate-high/9c81a4c8-cf43-4897-b136-53e17ddeb27d)
13. Gast, Matthew S. *802.11ac: A Survival Guide: Wi-Fi at Gigabit and Beyond.* O'Reilly Media, 2013. ISBN: 978-1449343149.
14. ResearchGate. "Evaluation of the Minstrel-HT Rate Adaptation Algorithm in IEEE 802.11n WLANs" (2017). https://www.researchgate.net/publication/322940194
15. ResearchGate. "On the Performance of Rate Control Algorithm Minstrel" (2012). https://www.researchgate.net/publication/261386189
16. Brecht et al. "Demystifying the Performance of A-MPDU in 802.11 Networks." *Computer Communications*, Vol. 180, 2021. https://cs.uwaterloo.ca/~brecht/papers/demyst-comp-comm-2021.pdf
17. Huehn, Thomas. "Minstrel-Blues: Joint Rate & Power Control for Linux mac80211." https://github.com/thuehn/Minstrel-Blues
18. Debookee / Medium. "802.11 Packet Retries: Why a Client Wouldn't ACK an Rx Packet?" (2016). https://medium.com/@debookee/802-11-packet-retries-why-a-client-wouldnt-ack-an-rx-packet-c0a370911a40
