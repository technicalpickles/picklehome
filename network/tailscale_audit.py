#!/usr/bin/env python3
"""
Tailscale key expiry audit: lists every tailnet device and flags anything
that doesn't fit the expected pattern.

Expected pattern:
  - Personal devices (macOS/iOS) keep default key expiry -- a human
    reauths periodically, so this is a feature, not a bug.
  - Tagged infra nodes (servers, sidecars) should have key expiry disabled,
    since nothing reauths them and an expired key just goes dark silently.
  - Anything else (untagged, non-personal OS) is unexpected: either a
    forgotten new node that needs a tag + disabled expiry, or a device that
    doesn't belong on the tailnet at all.

Tags and key-expiry-disabled are independent node attributes, so a node
can keep expiry disabled after silently losing its tag (this happened to
picklelab on 2026-09-17: it lost tag:server during manual recovery from a
key-expiry incident, which broke every Tailscale Service it hosted while
SSH/ping/container health stayed green). Folding "has tags OR expiry
disabled" into one "infra, OK" bucket would let that exact outage sail
past this script, so key-expiry-disabled-but-untagged gets its own flag
instead of a silent pass.

Read-only: uses the existing TAILSCALE_OAUTH_CLIENT_ID/SECRET (Policy File
read scope), never mutates anything.

Usage:
    uv run --with requests --with python-dotenv network/tailscale_audit.py
    uv run --with requests --with python-dotenv network/tailscale_audit.py --json
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN_URL = "https://api.tailscale.com/api/v2/oauth/token"
DEVICES_URL = "https://api.tailscale.com/api/v2/tailnet/-/devices"

PERSONAL_OSES = {"macOS", "iOS"}
EXPIRY_SOON_DAYS = 14


def get_access_token() -> str:
    client_id = os.environ["TAILSCALE_OAUTH_CLIENT_ID"]
    client_secret = os.environ["TAILSCALE_OAUTH_CLIENT_SECRET"]
    resp = requests.post(
        TOKEN_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_devices(token: str) -> list[dict]:
    resp = requests.get(
        DEVICES_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["devices"]


def classify(device: dict) -> str:
    if device.get("tags"):
        return "infra"
    # No tags, but expiry was deliberately disabled -- someone made the
    # infra call for this node at some point, yet it's untagged right now.
    # Don't fold this into "infra, OK": it's the exact shape a tagged node
    # takes after silently losing its tag.
    if device.get("keyExpiryDisabled"):
        return "infra_untagged"
    if device.get("os") in PERSONAL_OSES:
        return "personal"
    return "unknown"


def days_until(expires: str) -> int | None:
    if not expires:
        return None
    dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    return (dt - datetime.now(timezone.utc)).days


def audit(devices: list[dict]) -> list[dict]:
    findings = []
    for d in devices:
        category = classify(d)
        expiry_disabled = d.get("keyExpiryDisabled", False)
        expires = d.get("expires")
        remaining = days_until(expires)

        issue = None
        if category == "infra" and not expiry_disabled:
            issue = "tagged infra node without key expiry disabled -- will go dark on expiry"
        elif category == "infra_untagged":
            issue = "key expiry disabled but no ACL tags -- likely lost its tag (check admin console); Services it hosts will fail with 'service hosts must be tagged nodes'"
        elif category == "unknown":
            issue = "untagged, non-personal OS, expiry not disabled -- not recognized as personal or infra"
        elif category == "personal" and remaining is not None and remaining <= EXPIRY_SOON_DAYS:
            if remaining < 0:
                issue = f"key expired {-remaining}d ago -- reauth now (open the app / `tailscale up`)"
            else:
                issue = f"expires in {remaining}d -- reauth soon (open the app / `tailscale up`)"

        findings.append(
            {
                "name": d.get("name"),
                "os": d.get("os"),
                "tags": d.get("tags") or [],
                "category": category,
                "keyExpiryDisabled": expiry_disabled,
                "expires": expires,
                "daysRemaining": remaining,
                "issue": issue,
            }
        )
    return findings


def print_report(findings: list[dict]):
    ok = [f for f in findings if not f["issue"]]
    flagged = [f for f in findings if f["issue"]]

    print(f"Tailnet audit: {len(findings)} devices, {len(flagged)} flagged\n")

    if flagged:
        print("Flagged:")
        for f in flagged:
            print(f"  ⚠ {f['name']} ({f['os']}, tags={f['tags'] or 'none'}) -- {f['issue']}")
        print()

    print("OK:")
    for f in ok:
        expiry = "expiry disabled" if f["keyExpiryDisabled"] else f"expires in {f['daysRemaining']}d"
        print(f"  ✓ {f['name']} ({f['category']}, {f['os']}) -- {expiry}")


def main():
    parser = argparse.ArgumentParser(description="Audit tailnet devices for key-expiry hygiene")
    parser.add_argument("--json", action="store_true", help="print raw findings as JSON")
    args = parser.parse_args()

    token = get_access_token()
    devices = fetch_devices(token)
    findings = audit(devices)

    if args.json:
        import json

        print(json.dumps(findings, indent=2))
        return

    print_report(findings)

    if any(f["issue"] and f["category"] != "personal" for f in findings):
        sys.exit(1)


if __name__ == "__main__":
    main()
