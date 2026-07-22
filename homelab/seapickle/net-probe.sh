#!/usr/bin/env bash
# Connectivity probe: one JSON line per run to /var/log/seapickle/net-probe.jsonl.
#
# Answers, after the fact, "was the internet up when <device> stopped working?":
# LAN gateway ping, WAN ping, DNS resolution, and HTTPS reachability of the
# cloud endpoints the beach house smart devices depend on. Individual probe
# failures are data, not errors, so no `set -e` — every field degrades to null.
set -u

LOG_FILE=/var/log/seapickle/net-probe.jsonl

# Cloud endpoints the beach house devices need (see homelab/seapickle/README.md).
# Reachability = we got any HTTP status back; the apps' own status codes on a
# bare GET (404s etc.) don't matter, a TCP/TLS-level failure does.
declare -A CLOUDS=(
    [connectlife]="https://clife-eu-gateway.hijuconn.com"
    [nest]="https://smartdevicemanagement.googleapis.com"
    [yale]="https://api-production.august.com"
)

# Average RTT in ms, or empty on total loss.
ping_ms() {
    ping -n -c 3 -W 2 -q "$1" 2>/dev/null | awk -F/ '/^(rtt|round-trip)/ {print $5}'
}

gateway="$(ip -4 route show default 2>/dev/null | awk '{print $3; exit}')"
gw_ms=""
[[ -n "$gateway" ]] && gw_ms="$(ping_ms "$gateway")"
wan_ms="$(ping_ms 1.1.1.1)"

dns_ok=false
getent hosts one.one.one.one >/dev/null 2>&1 && dns_ok=true

clouds_json="{}"
for name in "${!CLOUDS[@]}"; do
    read -r code secs < <(curl -s -o /dev/null --max-time 10 \
        -w '%{http_code} %{time_total}' "${CLOUDS[$name]}" 2>/dev/null) || true
    if [[ "${code:-000}" == "000" ]]; then
        entry='{"ok": false, "ms": null}'
    else
        entry="$(jq -nc --arg s "$secs" '{ok: true, ms: (($s | tonumber) * 1000 | floor)}')"
    fi
    clouds_json="$(jq -nc --argjson acc "$clouds_json" --argjson e "$entry" \
        --arg n "$name" '$acc + {($n): $e}')"
done

jq -nc \
    --arg ts "$(date -u +%FT%TZ)" \
    --arg gw "$gw_ms" \
    --arg wan "$wan_ms" \
    --argjson dns "$dns_ok" \
    --argjson clouds "$clouds_json" \
    '{ts: $ts,
      gw_ping_ms:  (if $gw  == "" then null else ($gw  | tonumber) end),
      wan_ping_ms: (if $wan == "" then null else ($wan | tonumber) end),
      dns_ok: $dns,
      clouds: $clouds}' >> "$LOG_FILE"
