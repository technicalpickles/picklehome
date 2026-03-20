This is a great question, and the fact that you're seeing 19% retries with strong signal is actually a really common and instructive scenario. Let me walk through each of your questions.

## 1. Baseline Expectations

For 5GHz, a retry rate under 10% is generally healthy, and under 5% is excellent. Once you're consistently above 15%, it's worth investigating. Above 25% on 5GHz usually means something specific is wrong — congestion, interference, or a client-side issue.

For 2.4GHz, the baseline is inherently worse. Under 15% is reasonable in a suburban environment, and 20–30% is unfortunately common, especially for low-power IoT devices with single spatial streams and poor antenna designs. The 30–40% you're seeing on your IoT devices isn't great, but it's not unusual for that band in a residential area with overlapping neighbor networks.

The key insight: retry rate is *relative to the environment and band*, not an absolute metric. A 12% retry rate on 5GHz is more concerning than 12% on 2.4GHz.

## 2. User Impact Thresholds

The relationship between retries and user experience is nonlinear and depends heavily on the application:

For **bulk throughput** (downloads, streaming buffers), retries up to about 15–20% on 5GHz are largely absorbed. You lose proportional throughput, but if the link rate is high enough (your 216 Mbps TX rate), the effective throughput is still well above what most applications need. A 19% retry rate on a 216 Mbps link still leaves you with roughly 175 Mbps effective — more than enough for nearly anything.

For **latency-sensitive traffic** (video calls, gaming), retries start mattering much sooner. Each retry adds a frame transmission time plus a backoff period. At 10–15% retries, you'll start seeing occasional latency spikes in the 20–50ms range above baseline. At 25%+, video calls will show intermittent freezes and audio dropouts. The issue isn't the average retry rate — it's the *burstiness*. A steady 15% is less damaging than a rate that's 2% most of the time with bursts to 40%.

For **your specific case**: the 99 satisfaction score and the signal/SNR numbers suggest this iPhone user is almost certainly not experiencing perceptible problems. The retries are eating into headroom, not into usable capacity.

## 3. Retries vs. Other Metrics — A Triage Framework

Here's how I'd rank the metrics for diagnosing "slow internet" complaints, from most to least useful as a leading indicator:

**SNR (Signal-to-Noise Ratio)** is the single best predictor of link quality. Below 25 dB, you'll see MCS rate drops and rising retries. Below 15 dB, the connection becomes barely usable. Your 40 dB is excellent.

**TX/RX Rate (MCS index)** tells you what the radio layer has negotiated. If a client is stuck at MCS 0–2 despite decent signal, something is wrong (interference, client capability, or band steering issues). Your MCS 5 at 2 spatial streams (216 Mbps on 40 MHz) is reasonable but not the maximum — the AP or client is already adapting to some degree.

**Retry rate** is a *symptom*, not a root cause. It tells you *something* is causing frames to fail, but not *what*. It's useful for confirming a problem exists, less useful for diagnosing it.

**Signal strength (RSSI)** is the crudest metric. It tells you about path loss but says nothing about the noise floor or interference. A client at -64 dBm in a quiet environment performs very differently from -64 dBm with a high noise floor. Always look at SNR over raw RSSI.

**UniFi satisfaction score** is a composite that's useful for fleet-level monitoring but hides detail. A score of 99 with 19% retries tells you UniFi's algorithm is weighting the strong signal and good MCS rate heavily. Don't rely on it for troubleshooting individual clients.

**The practical triage order**: When someone says "the internet is slow," first check if it's actually a WAN/routing issue (run a speed test wired). If not, look at the client's SNR and MCS rate. If those are good but retries are high, you're looking at a medium-access-layer problem — congestion, hidden nodes, or interference. If SNR is low, it's a coverage or placement problem.

## 4. High Retries + Good Signal — Why?

This is the most interesting part of your scenario. A 19% retry rate with -64 dBm and 40 dB SNR points toward a few specific causes:

**Co-channel contention (CCI)** is the most likely explanation. Channel 149 at 40 MHz (so 149+153) is a popular choice for 5GHz, and if a neighbor's AP is on the same channel, your AP and theirs are sharing airtime via CSMA/CA. When both try to transmit simultaneously — or when your AP transmits and the client can't decode the frame because it heard the neighbor's AP at the same time — you get retries despite good signal. The key question: what does the channel utilization look like on 149? UniFi shows this in the RF environment view.

**Hidden node problem** is the second most common cause. This happens when two clients (or a client and a neighbor AP) can both hear your AP but can't hear each other. They transmit simultaneously, their frames collide at the AP, and both get retried. RTS/CTS can mitigate this, but it's disabled by default on most UniFi setups and adds overhead of its own.

**Client-side behavior** matters more than people realize. iPhones are known to have power-saving behavior (especially in low-power mode) where they may not acknowledge frames promptly, causing the AP to record a "retry" even though the original frame was received. Some iPhone models also have firmware-level quirks with certain MCS rates or channel widths.

**A-MPDU aggregation effects** can inflate the retry percentage. If the AP sends an aggregate frame (A-MPDU) with 20 subframes and 4 need retransmission, some implementations report that as 4 retries out of 20 (20%) even though the block ACK mechanism handled it efficiently within a single transmission opportunity. This is actually the most likely explanation for your specific numbers — more on this in the UniFi section below.

**Multipath or reflection** can cause issues even with strong signal. If the client is in a location with strong reflections (near metal surfaces, glass, or between rooms), the multiple signal paths can cause inter-symbol interference that degrades frame decoding even at high RSSI.

## 5. UniFi-Specific Considerations

This is where your skepticism is well-placed. UniFi's retry metric has some known quirks:

UniFi reports retries at the **driver/firmware level**, which includes A-MPDU subframe retries. In a packet capture (e.g., with a monitor-mode adapter), you'd see the retry bit set in the 802.11 frame header, which corresponds to full frame retransmissions. But UniFi's controller aggregates retries at the subframe level within A-MPDUs, which typically produces a higher percentage than what you'd measure externally. A "19% retry rate" in UniFi might correspond to something like 8–12% in a packet capture, depending on the aggregation depth.

The **satisfaction score** uses a proprietary algorithm that Ubiquiti hasn't fully documented. From community reverse-engineering, it appears to weight signal strength and expected throughput more heavily than retry rate. This is why you can see a 99 score with 19% retries — the algorithm considers retries a secondary factor when signal quality is high.

UniFi's **per-client retry counter** is also a rolling average, not a point-in-time snapshot. It smooths over bursty retry periods, which means the peak retry rate during congestion windows is likely higher than the reported 19%.

If you want ground truth, the most reliable method is to capture on a monitor-mode adapter on the same channel and look at the retry bit in the 802.11 MAC header yourself.

## 6. Going Deeper

For understanding the frame-level mechanics, here are the specific topics and search terms that will be most productive:

On the **802.11 MAC retransmission mechanism**: look into the distinction between short retry count and long retry count (controlled by dot11ShortRetryLimit and dot11LongRetryLimit in the 802.11 spec — defaults are 7 and 4 respectively). Understanding CSMA/CA, the backoff window (CWmin/CWmax), and how the contention window doubles on each retry is fundamental.

For **Block ACK and A-MPDU**: search for "802.11n Block ACK mechanism" and "A-MPDU aggregation and selective retransmission." The key concept is that with A-MPDU, the receiver sends a Block ACK bitmap indicating which subframes were received successfully, and only the failed subframes are retransmitted. This is far more efficient than retransmitting entire aggregate frames, and it's why high "retry rates" in A-MPDU environments are less impactful than they appear.

For **rate adaptation**: look into Minstrel and Minstrel-HT, which are the rate control algorithms used in the ath9k/ath10k drivers (which underpin UniFi APs). Understanding how these algorithms probe higher and lower MCS rates — and how failed probes count as retries — explains some of the baseline retry rate you'll always see.

For **practical resources**: the book "802.11ac: A Survival Guide" by Matthew Gast is excellent and covers aggregation, block ACK, and channel access in detail. For UniFi-specific behavior, the Ubiquiti community forums have extensive threads on retry rate interpretation — search for "UniFi retry rate normal" and you'll find several detailed discussions from network engineers who've done packet capture comparisons. The WLAN Professionals YouTube channel also has good deep dives on these topics.

---

**Bottom line for your framework**: treat retry rate as a secondary diagnostic, not a primary alarm. If SNR is above 25 dB, MCS rate is reasonable for the client's capabilities, and the satisfaction score is above 80, retries under 20% on 5GHz are probably not causing user-perceptible issues. Focus your troubleshooting energy on clients with low SNR, depressed MCS rates, *and* high retries — that combination is what produces the "slow internet" complaints.
