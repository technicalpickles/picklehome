"""Shared UniFi CloudKey authentication."""

import os
import sys
import warnings

import requests
from dotenv import load_dotenv

load_dotenv()
warnings.filterwarnings("ignore", message="Unverified HTTPS request")

CLOUDKEY = "https://192.168.1.57"
LEGACY = f"{CLOUDKEY}/proxy/network/api/s/default"
BASE = f"{CLOUDKEY}/proxy/network/integration/v1"


def session() -> requests.Session:
    """Return an authenticated requests.Session for the UniFi CloudKey API."""
    api_key = os.environ.get("UNIFI_API_KEY")
    if not api_key:
        sys.exit("UNIFI_API_KEY not set — add it to .env")
    s = requests.Session()
    s.headers.update({"X-API-Key": api_key, "Accept": "application/json"})
    s.verify = False
    return s
