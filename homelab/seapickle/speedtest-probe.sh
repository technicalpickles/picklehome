#!/usr/bin/env bash
# Daily Ookla speedtest: one JSON line per run to /var/log/seapickle/speedtest.jsonl.
set -euo pipefail

LOG_FILE=/var/log/seapickle/speedtest.jsonl

speedtest --accept-license --accept-gdpr -f json >> "$LOG_FILE"
