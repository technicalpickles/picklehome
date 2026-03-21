"""Shared Lutron Caseta bridge connection."""

import os
import sys

from dotenv import load_dotenv
from pylutron_caseta.smartbridge import Smartbridge

load_dotenv()

SEP = "─" * 70


def section(title):
    print(f"\n{title}")
    print(SEP)


async def connect() -> Smartbridge:
    """Connect to the Caseta bridge, return a Smartbridge instance."""
    bridge_ip = os.environ.get("LUTRON_BRIDGE_IP")
    keyfile = os.environ.get("LUTRON_KEYFILE")
    certfile = os.environ.get("LUTRON_CERTFILE")
    cafile = os.environ.get("LUTRON_CAFILE")

    missing = [
        name for name, val in [
            ("LUTRON_BRIDGE_IP", bridge_ip),
            ("LUTRON_KEYFILE", keyfile),
            ("LUTRON_CERTFILE", certfile),
            ("LUTRON_CAFILE", cafile),
        ]
        if not val
    ]
    if missing:
        sys.exit(
            f"Missing env vars: {', '.join(missing)}\n"
            "Run: just dotenv"
        )

    for path, label in [(keyfile, "key"), (certfile, "cert"), (cafile, "CA")]:
        if not os.path.exists(path):
            sys.exit(f"Lutron {label} file not found: {path}\nRun: just dotenv")

    bridge = Smartbridge.create_tls(
        bridge_ip, keyfile=keyfile, certfile=certfile, ca_certs=cafile
    )
    await bridge.connect()
    return bridge
