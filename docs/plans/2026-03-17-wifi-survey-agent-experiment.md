# WiFi Survey + Agent-Driven Improvement Experiment

**Date:** 2026-03-17
**Goal:** Use agent-driven workflow to diagnose and fix Tracy's WiFi issues, building toward a repeatable process for ongoing RF improvement.

## Motivation

Tracy experiences WiFi problems across multiple devices, especially in her office. Existing tooling (`wifi-diag.py`, `unifi-wifi.py`) covers point-in-time metrics and AP stats, but lacks spatial context: the agent knows room names but not physical layout, adjacency, or obstructions. This experiment adds that spatial layer and validates whether it improves agent reasoning.

## Phase 1: Spatial Foundation

1. Scan Tracy's office + path to nearest AP(s) in MagicPlan (current house, previous scan is for old house)
2. Export floor plan image from MagicPlan
3. Upload to UniFi floor plan feature; place all APs on it
4. Add a text description of the layout to `network/TOPOLOGY.md`:
   - Rooms and adjacency
   - Known obstructions (brick wall between office and living room already noted)
   - Which APs are physically nearest to Tracy's office

This gives the agent a persistent spatial model that carries across sessions.

## Phase 2: Baseline Measurement

Run diagnostics on Tracy's device and from the AP side:

```bash
# On Tracy's device
just wifi-diag

# From any machine with .env
just unifi-wifi client tracy
just unifi-wifi aps
```

Save all output to a new investigation file: `network/investigations/tracy-office-YYYY-MM-DD.md`

If the above data doesn't clearly explain the issue, proceed to a NetSpot walk survey:
- Import MagicPlan floor plan image into NetSpot
- Walk Tracy's office and surrounding areas in survey mode
- Export results and add summary to the investigation file

**This is the gate for deciding whether NetSpot is worth purchasing.**

## Phase 3: Agent Analysis and Recommendations

Open a new session, share the investigation file. With floor plan context in TOPOLOGY.md and the diagnostic snapshot, the agent will:

1. Identify likely cause (coverage gap, wrong AP association, channel interference, roaming issue)
2. Recommend specific changes (channel, transmit power, AP placement)
3. Optionally execute changes via `just unifi-wifi set-channel` or `just unifi-api`

## Phase 4: Validation and Staleness Detection

After any changes:

1. Re-run `just wifi-diag` on Tracy's device to confirm improvement
2. Add before/after results to the investigation file
3. Update `network/TOPOLOGY.md` with new channel/config state

**Staleness tracking:** Add a `last_survey` date to TOPOLOGY.md. At the start of WiFi-related sessions, the agent checks this date and prompts for a new survey if:
- The date is older than a threshold (e.g. 90 days), or
- Channel or AP changes have been made since the last survey

## Success Criteria

- Tracy's WiFi issues are diagnosed and resolved (or root cause identified)
- The agent can reason about the spatial layout without needing to ask where things are
- The workflow is repeatable: future issues follow the same investigation → analysis → change → validate loop
- Clear signal on whether NetSpot walk surveys add value over point measurements from `wifi-diag.py`
