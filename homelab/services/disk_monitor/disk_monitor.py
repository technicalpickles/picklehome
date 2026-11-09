#!/usr/bin/env python3
"""
Disk monitor for picklelab — runs locally, checks remote disk usage via SSH.

Logs usage to CSV, calculates rate of change, prints alert to stdout when:
- Usage > 80% (warning) or > 90% (critical)
- Fill rate > 2GB/day or > 5%/week
- Time to full < 7 days

Output goes to stdout, for whatever scheduler runs this to deliver. Silent
(exits 0 with no output) when all is well. If picklelab can't be reached it
prints an alert and exits 1, so a broken monitor never looks like a healthy one.
"""

import csv
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Config
PICKLELAB_HOST = "picklelab.tail2023b7.ts.net"
# ssh user: unset means plain `ssh <host>`, which uses ~/.ssh/config or the
# local username. Set DISK_MONITOR_SSH_USER to override.
PICKLELAB_USER = os.environ.get("DISK_MONITOR_SSH_USER")
CSV_PATH = Path.home() / ".local/state/picklehome/disk-monitor.csv"

# Thresholds
USAGE_WARN = 80      # Alert at 80%
USAGE_CRIT = 90      # Critical at 90%
RATE_WARN_GB = 2     # Alert if filling >2GB/day
RATE_WARN_PCT = 5    # Or >5% per week
TIME_TO_FULL_DAYS = 7  # Alert if <7 days to full

# Filesystems to monitor
FILESYSTEMS = ["/", "/srv", "/srv/containerd", "/srv/ci-docker"]


class SshError(Exception):
    """picklelab couldn't be reached or the remote command failed."""


def log(msg):
    print(f"[{datetime.now().isoformat()}] {msg}", file=sys.stderr)


def ssh_target(user=PICKLELAB_USER):
    """ssh destination: user@host when a user is configured, else the bare host."""
    return f"{user}@{PICKLELAB_HOST}" if user else PICKLELAB_HOST


def ssh_command(cmd):
    """Run command on picklelab via SSH and return stdout. Raises SshError on failure."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new",
             ssh_target(), cmd],
            capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired as e:
        raise SshError(f"ssh to {ssh_target()} timed out after {e.timeout}s") from e
    except OSError as e:
        raise SshError(f"could not run ssh: {e}") from e
    if result.returncode != 0:
        raise SshError(f"ssh to {ssh_target()} failed ({result.returncode}): {result.stderr.strip()}")
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
    if not CSV_PATH.exists():
        return []
    rows = []
    with open(CSV_PATH, "r") as f:
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
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    exists = CSV_PATH.exists()
    with open(CSV_PATH, "a", newline="") as f:
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
    if time_diff_days == 0:
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


def build_alert(usage, history, top_paths, disk_report=None):
    """Build alert message with context."""
    lines = ["🚨 Picklelab Disk Alert\n"]
    
    for mount in FILESYSTEMS:
        if mount not in usage:
            continue
        data = usage[mount]
        rate_gb, rate_pct = calculate_rate(history, mount)
        ttf = estimate_time_to_full(data, rate_gb) if rate_gb and rate_gb > 0 else None
        
        status = "⚠️ WARNING" if data["used_pct"] >= USAGE_WARN else ""
        if data["used_pct"] >= USAGE_CRIT:
            status = "🔴 CRITICAL"
        
        lines.append(f"{status} {mount}")
        lines.append(f"  Used: {data['used_pct']}% ({data['used_gb']}GB / {data['used_gb'] + data['avail_gb']}GB)")
        lines.append(f"  Free: {data['avail_gb']}GB")
        
        if rate_gb is not None:
            direction = "growing" if rate_gb > 0 else "shrinking"
            lines.append(f"  Rate: {abs(rate_gb):.1f}GB/day {direction}")
        if ttf:
            lines.append(f"  ⏰ Time to full: {ttf:.1f} days")
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
    else:
        lines.append("\nRun: just disk-report")
    
    return "\n".join(lines)


def should_alert(usage, history):
    """Determine if we should send an alert."""
    for mount in FILESYSTEMS:
        if mount not in usage:
            continue
        data = usage[mount]
        
        if data["used_pct"] >= USAGE_WARN:
            return True
        
        rate_gb, rate_pct = calculate_rate(history, mount)
        if rate_gb and abs(rate_gb) > RATE_WARN_GB:
            return True
        if rate_pct and abs(rate_pct) > RATE_WARN_PCT:
            return True
        
        if rate_gb and rate_gb > 0:
            ttf = estimate_time_to_full(data, rate_gb)
            if ttf and ttf < TIME_TO_FULL_DAYS:
                return True
    
    return False


def main():
    log("Starting disk monitor check")
    
    try:
        usage = get_disk_usage()
    except SshError as e:
        log(f"Failed to get disk usage: {e}")
        print(f"🚨 Disk monitor could not reach picklelab\n\n{e}")
        return 1
    
    history = load_history()
    save_history(usage)
    
    if not should_alert(usage, history):
        log("Disk usage normal, no alert needed")
        return 0
    
    top_paths = get_top_paths()
    disk_report = get_disk_report()
    message = build_alert(usage, history, top_paths, disk_report)
    
    # Print alert to stdout — Hermes cron job delivers to configured target
    print(message)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
