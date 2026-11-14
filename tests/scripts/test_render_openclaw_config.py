"""Pins the openclaw config values deploy.sh writes, via scripts/render-openclaw-config."""
import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "render-openclaw-config"


def _render(host="gw.example.ts.net"):
    out = subprocess.run(
        [str(SCRIPT)],
        env={**os.environ, "OPENCLAW_HOST": host},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {e["path"]: e["value"] for e in json.loads(out)}


def test_heartbeat_is_off_and_internal():
    cfg = _render()
    assert cfg["agents.defaults.heartbeat.every"] == "0m"
    assert cfg["agents.defaults.heartbeat.target"] == "none"


def test_device_pair_advertises_the_tailnet_url():
    cfg = _render("gw.example.ts.net")
    assert cfg["plugins.entries.device-pair.config.publicUrl"] == "wss://gw.example.ts.net"


def test_legacy_extension_relay_auth_is_off():
    assert _render()["browser.extensionRelay.allowLegacyAuth"] is False
