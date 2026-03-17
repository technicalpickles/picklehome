#!/usr/bin/env python3
"""
unifi-api.py — Raw UniFi CloudKey API wrapper for debugging

Thin wrapper around the CloudKey legacy API that handles auth and TLS,
so you can explore endpoints without manually setting headers in curl.

Usage:
    uv run --with requests --with python-dotenv network/unifi-api.py get /stat/device
    uv run --with requests --with python-dotenv network/unifi-api.py get /stat/sta
    uv run --with requests --with python-dotenv network/unifi-api.py put /rest/device/<id> '{"radio_table": [...]}'

Paths are relative to /proxy/network/api/s/default — omit that prefix.
"""

import argparse
import json
import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"


def session():
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set — add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s


def main():
    parser = argparse.ArgumentParser(
        description="Raw UniFi API wrapper — GET/PUT endpoints with auth handled"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="GET an API endpoint")
    p_get.add_argument("path", help="Path relative to /api/s/default, e.g. /stat/device")

    p_put = sub.add_parser("put", help="PUT JSON to an API endpoint")
    p_put.add_argument("path", help="Path relative to /api/s/default, e.g. /rest/device/<id>")
    p_put.add_argument("body", help="JSON body as a string")

    args = parser.parse_args()
    s = session()
    url = f"{LEGACY}{args.path}"

    if args.cmd == "get":
        r = s.get(url, timeout=10)
    elif args.cmd == "put":
        try:
            body = json.loads(args.body)
        except json.JSONDecodeError as e:
            sys.exit(f"Invalid JSON: {e}")
        r = s.put(url, json=body, timeout=10)

    print(json.dumps(r.json(), indent=2))


if __name__ == "__main__":
    main()
