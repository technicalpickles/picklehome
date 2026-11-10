#!/usr/bin/env python3
"""
Disk monitor for picklelab. Checks disk usage over SSH, or on the local host
when DISK_MONITOR_LOCAL=1.

Logs usage to CSV, calculates rate of change, prints alert to stdout when:
- Usage > 80% (warning) or > 90% (critical)
- Time to full < 7 days at the 24h fill rate (a fast rate with plenty of
  runway is not an alert)

The same set of conditions is sent once, then again at most daily. A new
mount or an escalation to critical sends immediately.

Output goes to stdout, for whatever scheduler runs this to deliver. Silent
(exits 0 with no output) when all is well. If picklelab can't be reached it
prints an alert and exits 1, so a broken monitor never looks like a healthy one.
"""

import csv
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from typing import NamedTuple
from pathlib import Path

# Config
PICKLELAB_HOST = "picklelab.tail2023b7.ts.net"
# ssh user: unset means plain `ssh <host>`, which uses ~/.ssh/config or the
# local username. Set DISK_MONITOR_SSH_USER to override.
PICKLELAB_USER = os.environ.get("DISK_MONITOR_SSH_USER")
DEFAULT_CSV_PATH = Path.home() / ".local/state/picklehome/disk-monitor.csv"

# Thresholds
USAGE_WARN = 80      # Alert at 80%
USAGE_CRIT = 90      # Critical at 90%
MIN_RATE_WINDOW_HOURS = 6  # Need this much history before a rate means anything
TIME_TO_FULL_DAYS = 7  # Alert if <7 days to full
REPEAT_HOURS = 24      # Re-send an unchanged alert at most this often

# Filesystems to monitor
FILESYSTEMS = ["/", "/srv", "/srv/containerd", "/srv/ci-docker"]


class SshError(Exception):
    """picklelab couldn't be reached or the remote command failed."""


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}", file=sys.stderr)


def ssh_target(user=PICKLELAB_USER):
    """ssh destination: user@host when a user is configured, else the bare host."""
    return f"{user}@{PICKLELAB_HOST}" if user else PICKLELAB_HOST


def csv_path():
    """History file: DISK_MONITOR_CSV when set, else the per-user state dir."""
    override = os.environ.get("DISK_MONITOR_CSV")
    return Path(override) if override else DEFAULT_CSV_PATH


def ssh_command(cmd):
    """Run command on picklelab and return stdout. Raises SshError on failure.

    With DISK_MONITOR_LOCAL=1 the monitor is running on picklelab itself, so the
    command runs under bash here instead of over ssh.
    """
    if os.environ.get("DISK_MONITOR_LOCAL") == "1":
        argv = ["bash", "-c", cmd]
        where = "local command"
    else:
        argv = ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
                ssh_target(), cmd]
        where = f"ssh to {ssh_target()}"
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        raise SshError(f"{where} timed out after {e.timeout}s") from e
    except OSError as e:
        raise SshError(f"could not run {argv[0]}: {e}") from e
    if result.returncode != 0:
        raise SshError(f"{where} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout.strip()


def parse_df(output):
    """Parse df output, return dict of mountpoint -> {used_pct, used_gb, avail_gb}."""
    results = {}
    lines = output.strip().split("\n")[1:]  # Skip header
    for line in lines:
        parts = line.split()
        if len(parts) >= 6:
            used_pct = int(parts[4].rstrip("%"))
            used_kb = int(parts[2])
            avail_kb = int(parts[3])
            mount = parts[5]
            results[mount] = {
                "used_pct": used_pct,
                "used_gb": round(used_kb / 1024 / 1024, 1),
                "avail_gb": round(avail_kb / 1024 / 1024, 1),
            }
    return results


def get_disk_usage():
    """Get disk usage from picklelab. Raises SshError if it can't be read."""
    # df -k (not -h) for KB values. df exits non-zero when a mount doesn't exist
    # yet (before the Docker split), which would make ssh report failure, so
    # `|| true` keeps partial output; parse_df only sees the mounts that exist.
    output = ssh_command(f"df -k {' '.join(FILESYSTEMS)} 2>/dev/null || true")
    if not output:
        raise SshError("df returned no output for any monitored mount")
    return parse_df(output)


def get_top_paths():
    """Get top 5 paths by size under /srv, including separately mounted dirs."""
    try:
        output = ssh_command("du -h -d1 /srv 2>/dev/null | sort -rh | head -5")
    except SshError as e:
        log(f"top paths unavailable: {e}")
        return []
    if not output:
        return []
    return output.strip().split("\n")


def get_disk_report():
    """Get full disk-report diagnostic output."""
    try:
        output = ssh_command("sudo disk-report")
    except SshError as e:
        log(f"disk-report unavailable: {e}")
        return None
    return output or None


def load_history():
    """Load CSV history, return list of {timestamp, mount, used_pct, used_gb}."""
    path = csv_path()
    if not path.exists():
        return []
    rows = []
    with open(path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "timestamp": datetime.fromisoformat(row["timestamp"]),
                "mount": row["mount"],
                "used_pct": float(row["used_pct"]),
                "used_gb": float(row["used_gb"]),
            })
    return rows


def save_history(usage):
    """Append current usage to CSV."""
    path = csv_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "mount", "used_pct", "used_gb"])
        if not exists:
            writer.writeheader()
        for mount, data in usage.items():
            writer.writerow({
                "timestamp": datetime.now().isoformat(),
                "mount": mount,
                "used_pct": data["used_pct"],
                "used_gb": data["used_gb"],
            })


def calculate_rate(history, mount, hours=24):
    """Calculate fill rate over last N hours. Returns (gb_per_day, pct_per_week) or (None, None)."""
    mount_history = [h for h in history if h["mount"] == mount]
    if len(mount_history) < 2:
        return None, None
    
    mount_history.sort(key=lambda x: x["timestamp"])
    cutoff = datetime.now() - timedelta(hours=hours)
    recent = [h for h in mount_history if h["timestamp"] >= cutoff]
    if len(recent) < 2:
        return None, None
    
    oldest = recent[0]
    newest = recent[-1]
    time_diff_days = (newest["timestamp"] - oldest["timestamp"]).total_seconds() / 86400
    if time_diff_days * 24 < MIN_RATE_WINDOW_HOURS:
        return None, None
    
    gb_diff = newest["used_gb"] - oldest["used_gb"]
    pct_diff = newest["used_pct"] - oldest["used_pct"]
    
    gb_per_day = gb_diff / time_diff_days
    pct_per_week = (pct_diff / time_diff_days) * 7
    
    return gb_per_day, pct_per_week


def estimate_time_to_full(usage, rate_gb_per_day):
    """Estimate days until 100% full at current rate."""
    if rate_gb_per_day <= 0:
        return None
    free_gb = usage["avail_gb"]
    return free_gb / rate_gb_per_day


class Reason(NamedTuple):
    mount: str
    kind: str  # "warning", "critical" or "fill"


HINTS = {
    "warning": "Prune with `just docker-prune-now`, find what's big with `just disk-report`, or grow the LV.",
    "critical": "Act now: `just docker-prune-now`, then `just disk-report`, or grow the LV.",
    "fill": "Check `just disk-report`. A one-off step (copy, restore) ages out of the 24h window by itself.",
}


def find_reasons(usage, history):
    """Every (mount, kind) currently worth alerting on."""
    reasons = []
    for mount in FILESYSTEMS:
        if mount not in usage:
            continue
        data = usage[mount]
        if data["used_pct"] >= USAGE_CRIT:
            reasons.append(Reason(mount, "critical"))
        elif data["used_pct"] >= USAGE_WARN:
            reasons.append(Reason(mount, "warning"))

        rate_gb, _ = calculate_rate(history, mount)
        if rate_gb and rate_gb > 0:
            ttf = estimate_time_to_full(data, rate_gb)
            if ttf and ttf < TIME_TO_FULL_DAYS:
                reasons.append(Reason(mount, "fill"))
    return reasons


def should_alert(usage, history):
    """Is anything wrong right now, ignoring whether we already said so."""
    return bool(find_reasons(usage, history))


def build_alert(usage, history, top_paths, disk_report=None):
    """Build alert message for the mounts that breach, with a next step each."""
    reasons = find_reasons(usage, history)
    lines = ["🚨 Picklelab Disk Alert\n"]

    for mount in dict.fromkeys(r.mount for r in reasons):
        data = usage[mount]
        kinds = [r.kind for r in reasons if r.mount == mount]
        status = "🔴 CRITICAL" if "critical" in kinds else "⚠️ WARNING"
        rate_gb, _ = calculate_rate(history, mount)

        lines.append(f"{status} {mount}")
        lines.append(f"  Used: {data['used_pct']}% ({data['used_gb']}GB / {data['used_gb'] + data['avail_gb']}GB)")
        lines.append(f"  Free: {data['avail_gb']}GB")
        if rate_gb is not None:
            direction = "growing" if rate_gb > 0 else "shrinking"
            lines.append(f"  Rate: {abs(rate_gb):.1f}GB/day {direction}")
        if "fill" in kinds:
            lines.append(f"  ⏰ Time to full: {estimate_time_to_full(data, rate_gb):.1f} days")
        lines.append(f"  → {HINTS[max(kinds, key=['fill', 'warning', 'critical'].index)]}")
        lines.append("")

    if top_paths:
        lines.append("Top /srv paths:")
        for path in top_paths:
            lines.append(f"  {path}")
        lines.append("")

    if disk_report:
        lines.append("Full disk-report:")
        lines.append("```")
        lines.append(disk_report)
        lines.append("```")

    return "\n".join(lines).rstrip()


def state_path():
    return csv_path().with_name("disk-monitor-alert.json")


def alert_state(reasons, sent_at):
    return {"reasons": sorted(f"{r.mount}:{r.kind}" for r in reasons), "sent_at": sent_at.isoformat()}


def load_alert_state():
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return None


def save_alert_state(state):
    path = state_path()
    if state is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state))


def should_send(reasons, state, now):
    """Send when the conditions changed, or the last identical alert is a day old."""
    if not reasons:
        return False
    if not state or state.get("reasons") != alert_state(reasons, now)["reasons"]:
        return True
    return now - datetime.fromisoformat(state["sent_at"]) >= timedelta(hours=REPEAT_HOURS)


def main():
    log("Starting disk monitor check")
    
    try:
        usage = get_disk_usage()
    except SshError as e:
        log(f"Failed to get disk usage: {e}")
        print(f"🚨 Disk monitor could not check picklelab\n\n{e}")
        return 1
    
    history = load_history()
    save_history(usage)
    
    reasons = find_reasons(usage, history)
    now = datetime.now()
    if not reasons:
        save_alert_state(None)
        log("Disk usage normal, no alert needed")
        return 0
    if not should_send(reasons, load_alert_state(), now):
        log("Same alert already sent recently, staying quiet")
        return 0

    critical = any(r.kind == "critical" for r in reasons)
    top_paths = get_top_paths()
    disk_report = get_disk_report() if critical else None
    message = build_alert(usage, history, top_paths, disk_report)
    save_alert_state(alert_state(reasons, now))

    print(message)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
