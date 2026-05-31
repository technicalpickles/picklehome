#!/usr/bin/env bash
# network-diag.sh: Systematic ISP/routing diagnostic
# Usage: ./network-diag.sh <domain>

set -uo pipefail

DOMAIN="${1:?Usage: $0 <domain>}"

# Timeouts (seconds)
T_PING=8
T_DIG=5
T_CURL=12
T_TRACE=20

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

section() { echo; echo -e "${BLUE}${BOLD}━━━  $1  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; }
ok()      { echo -e "  ${GREEN}✓${NC}  $*"; }
fail()    { echo -e "  ${RED}✗${NC}  $*"; }
info()    { echo -e "  ${CYAN}→${NC}  $*"; }
warn()    { echo -e "  ${YELLOW}!${NC}  $*"; }

run() {
    # run <timeout_secs> <label> <cmd...>
    local secs=$1 label=$2; shift 2
    echo -e "\n  ${BOLD}${label}${NC}"
    echo -e "  ${YELLOW}cmd:${NC} $*"
    timeout "$secs" "$@" 2>&1 | sed 's/^/    /'
    local rc=${PIPESTATUS[0]}
    if [ $rc -eq 124 ]; then
        warn "Timed out after ${secs}s"
    fi
    return $rc
}

echo
echo -e "${BOLD}Network Diagnostic: ${DOMAIN}${NC}"
echo -e "$(date)"
echo -e "Nameserver: $(scutil --dns 2>/dev/null | awk '/nameserver/{print $3; exit}' || echo 'unknown')"

# ─── 1. BASELINE ────────────────────────────────────────────────────────────
section "1. Baseline: Can we reach anything?"

for ip in 8.8.8.8 1.1.1.1; do
    if timeout $T_PING ping -c 3 -W 2000 "$ip" > /tmp/ping_out 2>&1; then
        rtt=$(grep -oE 'avg[^/]*/[0-9.]+' /tmp/ping_out | grep -oE '[0-9]+\.[0-9]+$' || echo '?')
        ok "ping $ip  (avg ${rtt}ms)"
    else
        fail "ping $ip: no response"
        cat /tmp/ping_out | sed 's/^/    /'
    fi
done

info "curl google.com (HTTPS, expect 200/301)"
timeout $T_CURL curl -s -o /dev/null -w "    HTTP %{http_code}  connect=%{time_connect}s  total=%{time_total}s\n" \
    --max-time $T_CURL https://www.google.com || warn "curl google.com failed/timed out"

# ─── 2. DNS ──────────────────────────────────────────────────────────────────
section "2. DNS: Name resolution"

for ns in "" "@8.8.8.8" "@1.1.1.1"; do
    label="dig $DOMAIN ${ns:-"(default DNS)"}"
    result=$(timeout $T_DIG dig +short +time=4 $ns "$DOMAIN" 2>&1 | tr '\n' ' ' | sed 's/ $//')
    if [ -n "$result" ]; then
        ok "$label → $result"
    else
        fail "$label → no answer"
    fi
done

# ─── 3. TRACEROUTE ───────────────────────────────────────────────────────────
section "3. Traceroute: Where does the path go?"

info "Tracing to $DOMAIN (max 20 hops, 2s per hop)"
timeout $T_TRACE traceroute -n -m 20 -w 2 "$DOMAIN" 2>&1 | sed 's/^/  /'

echo
info "Tracing to google.com (baseline comparison)"
timeout $T_TRACE traceroute -n -m 20 -w 2 google.com 2>&1 | sed 's/^/  /'

# ─── 4. MTU ──────────────────────────────────────────────────────────────────
section "4. MTU: Do large packets get through?"

# macOS: -D = set Don't Fragment bit, -s = payload size
# 8.8.8.8 used (reliable, not the destination, isolates path to internet)
info "Testing Don't Fragment packets toward 8.8.8.8 (payload sizes: 1472, 1452, 1400, 1200)"
for size in 1472 1452 1400 1200; do
    total=$((size + 28))
    result=$(timeout $T_PING ping -c 2 -W 2000 -D -s "$size" 8.8.8.8 2>&1)
    if echo "$result" | grep -q "2 packets transmitted, 2 packets received"; then
        ok "size ${size} (${total} byte total): passed"
    elif echo "$result" | grep -q "0 packets received"; then
        fail "size ${size} (${total} byte total): DROPPED (possible MTU black hole)"
    else
        warn "size ${size} (${total} byte total), partial: $(echo "$result" | grep 'packets' | tail -1)"
    fi
done

# ─── 5. TCP + TLS HANDSHAKE ──────────────────────────────────────────────────
section "5. TCP/TLS: Where does the HTTPS connection stall?"

info "curl -v https://${DOMAIN} (watching connect vs. TLS vs. first-byte timing)"
timeout $T_CURL curl -v -s -o /dev/null \
    -w "\n  dns=%{time_namelookup}s  connect=%{time_connect}s  tls=%{time_appconnect}s  ttfb=%{time_starttransfer}s  total=%{time_total}s  http=%{http_code}\n" \
    --max-time $T_CURL "https://${DOMAIN}" 2>&1 \
    | grep -E '^\*|^>|^ dns|^  dns|Trying|Connected|SSL|TLS|timed|curl' \
    | sed 's/^/  /'

# ─── 6. IPv4 vs IPv6 ─────────────────────────────────────────────────────────
section "6. IPv4 vs IPv6: Is one protocol broken?"

info "IPv6 connectivity check"
if timeout $T_PING ping6 -c 2 2001:4860:4860::8888 > /dev/null 2>&1; then
    ok "IPv6 reachable (Google DNS)"
else
    warn "IPv6 not reachable (may be normal if ISP doesn't provide it)"
fi

for flag in "-4" "-6"; do
    proto=$([ "$flag" = "-4" ] && echo "IPv4" || echo "IPv6")
    result=$(timeout $T_CURL curl $flag -s -o /dev/null \
        -w "%{http_code} connect=%{time_connect}s total=%{time_total}s" \
        --max-time $T_CURL "https://${DOMAIN}" 2>&1)
    if echo "$result" | grep -qE '^[23]'; then
        ok "$proto ($flag): $result"
    else
        fail "$proto ($flag): $result"
    fi
done

# ─── SUMMARY ─────────────────────────────────────────────────────────────────
section "Summary: Interpretation hints"
cat <<'EOF'
  Traceroute drops inside AT&T hops  → AT&T routing/peering issue, contact ISP
  Traceroute drops at peering point  → BGP dispute between AT&T and CDN provider
  Large MTU pings fail, small pass   → MTU mismatch (very common with AT&T fiber)
                                       Fix: set router MTU to 1492 (PPPoE) or 1452
  IPv4 ok, IPv6 fail (or vice versa) → Dual-stack misconfiguration
  DNS resolves differently by server → AT&T DNS problem; try changing to 8.8.8.8
  TLS time >> connect time           → TLS handshake stall, possible PMTUD issue
  All curl fail, pings pass          → Likely MTU or PMTUD black hole (ICMP blocked)
EOF
echo
