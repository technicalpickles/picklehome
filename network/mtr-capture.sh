#!/usr/bin/env bash
# mtr-capture.sh: capture mtr reports to network/diag-results/mtr/
# Run with sudo: sudo bash network/mtr-capture.sh

OUTDIR="$(dirname "$0")/diag-results/mtr"
mkdir -p "$OUTDIR"
CYCLES=30

declare -A TARGETS=(
    ["104.16.99.29"]="cfl.dropboxstatic.com"
    ["104.16.102.112"]="static.canva.com"
    ["3.161.193.123"]="fjord.dropboxstatic.com"
    ["8.8.8.8"]="google-baseline"
)

echo "Starting mtr ($CYCLES cycles each, running in parallel)..."
for ip in "${!TARGETS[@]}"; do
    label="${TARGETS[$ip]}"
    outfile="$OUTDIR/${label}.txt"
    echo "  → $ip  ($label)"
    mtr --report --report-cycles "$CYCLES" --no-dns "$ip" > "$outfile" 2>&1 &
done

wait
echo ""
echo "Done. Results:"
echo ""
for ip in "${!TARGETS[@]}"; do
    label="${TARGETS[$ip]}"
    echo "══════  ${label}  (${ip})  ══════"
    cat "$OUTDIR/${label}.txt"
    echo ""
done
