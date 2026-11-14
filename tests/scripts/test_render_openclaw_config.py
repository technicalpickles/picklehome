"""Pins the openclaw config values deploy.sh writes, via scripts/render-openclaw-config."""
import json
import os
import subprocess
from pathlib import Path

import pytest

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


BATCH = """$RUN_CLI config set --batch-json '[
    {"path":"gateway.bind","value":"lan"}
]'
"""


def _render_fixture(tmp_path, body):
    deploy = tmp_path / "deploy.sh"
    deploy.write_text(body)
    return subprocess.run(
        [str(SCRIPT), str(deploy)], capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "statement",
    [
        "$RUN_CLI config set gateway.port 18789\n",
        "$RUN_CLI config set --batch-json '[{\"path\":\"a\",\"value\":1}]'\n",
    ],
    ids=["path-value", "one-line-batch"],
)
def test_one_line_config_set_refuses_without_running_shell_lines(tmp_path, statement):
    marker = tmp_path / "ran"
    r = _render_fixture(tmp_path, statement + f"touch {marker}\n" + BATCH)
    assert r.returncode != 0
    assert "--batch-json" in r.stderr
    assert not marker.exists()


def test_shell_line_inside_batch_refuses_without_running_it(tmp_path):
    marker = tmp_path / "ran"
    body = BATCH.replace("]'\n", "]' || true\n") + f"touch {marker}\n]'\n"
    r = _render_fixture(tmp_path, body)
    assert r.returncode != 0
    assert "not a JSON line" in r.stderr
    assert not marker.exists()


def test_unclosed_batch_refuses(tmp_path):
    r = _render_fixture(tmp_path, BATCH.replace("]'\n", ""))
    assert r.returncode != 0
    assert "never closed" in r.stderr


def test_indented_config_set_is_not_rendered(tmp_path):
    onboard = "if true; then\n    " + BATCH.replace("gateway.bind", "onboard.only") + "fi\n"
    r = _render_fixture(tmp_path, onboard + BATCH)
    assert r.returncode == 0, r.stderr
    assert [e["path"] for e in json.loads(r.stdout)] == ["gateway.bind"]
