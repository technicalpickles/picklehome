# WiFi TX Retry Rates — What's Normal, What's a Problem?

I'm trying to build a mental model for understanding WiFi TX retry rates — when they matter, when they don't, and at what point they start causing the "the internet is slow" complaints I regularly hear from people on my network.

## My setup

- UniFi network: 4 APs (AC Pro, AC LR, AC HD) managed by a USG
- Mix of 2.4GHz and 5GHz clients (phones, laptops, smart home devices)
- Residential environment, suburban

## What I'm currently seeing (example from one client)

- Device: iPhone on 5GHz, 802.11ac, 2 spatial streams
- AP: UniFi AC LR, channel 149, 40 MHz width
- Signal: -64 dBm, SNR: 40 dB (both seem good)
- TX rate: 216 Mbps (MCS 5), RX: 180 Mbps
- TX Retry rate: 19.2%
- UniFi satisfaction score: 99

The signal and SNR look healthy, but the retry rate seems high. Other clients on different APs show 0-6% retries with similar signal levels, and some show 30-40% (mostly 2.4GHz IoT devices).

## What I'd like to understand

1. **Baseline expectations:** What retry rate ranges are considered normal/acceptable for 5GHz vs 2.4GHz? At what percentage should I actually start worrying?

2. **User impact thresholds:** At what point do retries start translating into perceptible slowness, buffering, or dropped video calls? Is there a rough mapping between retry % and real-world experience degradation?

3. **Retries vs. other metrics:** How should I weigh retry rate against signal strength, SNR, satisfaction score, and TX/RX rates when diagnosing "slow network" complaints? Which metric is the best leading indicator of user-perceived problems?

4. **High retries + good signal — why?** In my example, signal and SNR are solid but retries are 19%. What are the most common explanations for this combination? (channel congestion, hidden node problem, client-side issues, etc.)

5. **UniFi-specific considerations:** Does UniFi's reported retry % measure something different than what you'd see in a packet capture? Are there known quirks in how UniFi calculates or displays this metric?

6. **Pointers for going deeper:** If I want to really understand the mechanics (Block ACK, A-MPDU aggregation, retry counters, 802.11 frame-level behavior), what are good resources or search terms to look into?

I'm not looking to diagnose this one client specifically — I want to build a general framework for interpreting retry rates so I can triage network complaints more effectively.
