"""Guard against committing geolocatable hardware identifiers.

docs/CONVENTIONS.md: full MAC addresses and BSSIDs, device serials, street
addresses, and coordinates never get committed. Private LAN IPs and OUI
prefixes are fine. WiFi MACs near a home are in wardriving databases, so a
full one is effectively a location.

This scans every git-tracked text file for full MAC-shaped tokens. To keep a
MAC in a doc, mask the device half (`aa:bb:cc:xx:xx:xx`). Test fixtures use a
locally-administered address (`02:...`, or anything with bit 1 of the first
octet set, e.g. `AA:BB:CC:...`), which can never collide with real hardware.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

MAC = re.compile(r"(?<![0-9A-Fa-f:.-])([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:.-])")
SONOS_UID = re.compile(r"RINCON_[0-9A-F]{12}")

SKIP_SUFFIXES = {".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".dxf", ".ico"}


def _tracked_text_files():
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO, check=True, capture_output=True
    ).stdout
    for rel in out.decode().split("\0"):
        if not rel:
            continue
        p = REPO / rel
        if p.suffix.lower() in SKIP_SUFFIXES or not p.is_file():
            continue
        yield rel, p


def _is_synthetic(mac: str) -> bool:
    first = int(mac[:2], 16)
    return mac.replace(":", "").replace("-", "").strip("0") == "" or bool(first & 0x02)


def test_no_full_mac_addresses_in_tracked_files():
    offenders = []
    for rel, p in _tracked_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for m in MAC.finditer(line):
                if not _is_synthetic(m.group(0)):
                    offenders.append(f"{rel}:{lineno}: {m.group(0)}")
            for m in SONOS_UID.finditer(line):
                offenders.append(f"{rel}:{lineno}: {m.group(0)} (mask as RINCON_XXXXXXXXXXXX...)")
    assert not offenders, (
        "Full hardware identifiers found in tracked files. Mask the device half "
        "(aa:bb:cc:xx:xx:xx) or use a locally-administered synthetic MAC:\n  "
        + "\n  ".join(offenders)
    )
