"""Tests for homelab/scripts/notify_telegram.py. No network: urlopen is stubbed."""
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "homelab" / "scripts" / "notify_telegram.py"
spec = importlib.util.spec_from_file_location("notify_telegram", SCRIPT)
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)

TOKEN = "123456:SECRET-TOKEN-VALUE"
ENV = {"TELEGRAM_ALERT_BOT_TOKEN": TOKEN, "TELEGRAM_ALERT_CHAT_ID": "42"}


class FakeResponse:
    def __init__(self, body=b'{"ok": true}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run(text, env=ENV, args=(), opener=None):
    out, err = io.StringIO(), io.StringIO()
    code = notify.main(list(args), stdin=io.StringIO(text), env=env, opener=opener, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_sends_the_message_to_the_configured_chat():
    seen = {}

    def opener(req, timeout=None):
        seen["url"], seen["body"] = req.full_url, json.loads(req.data)
        return FakeResponse()

    code, _, _ = run("disk is full\n", opener=opener)

    assert code == 0
    assert seen["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert seen["body"]["chat_id"] == "42"
    assert seen["body"]["text"] == "disk is full"
    assert "message_thread_id" not in seen["body"]
    assert "parse_mode" not in seen["body"]


def test_thread_id_is_sent_when_configured():
    seen = {}

    def opener(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return FakeResponse()

    run("hi", env={**ENV, "TELEGRAM_ALERT_THREAD_ID": "7"}, opener=opener)

    assert seen["body"]["message_thread_id"] == 7


def test_empty_input_sends_nothing_and_succeeds():
    def opener(req, timeout=None):
        raise AssertionError("must not send")

    code, out, err = run("  \n\n", opener=opener)

    assert (code, out, err) == (0, "", "")


def test_long_messages_are_truncated_to_the_telegram_limit():
    seen = {}

    def opener(req, timeout=None):
        seen["text"] = json.loads(req.data)["text"]
        return FakeResponse()

    run("x" * 10000, opener=opener)

    assert len(seen["text"]) <= 4096
    assert seen["text"].endswith("(truncated)")


def test_dry_run_prints_the_message_and_never_the_token_or_network():
    def opener(req, timeout=None):
        raise AssertionError("must not send")

    code, out, err = run("hello", args=["--dry-run"], opener=opener)

    assert code == 0
    assert "hello" in out and "42" in out
    assert TOKEN not in out + err


@pytest.mark.parametrize("missing", ["TELEGRAM_ALERT_BOT_TOKEN", "TELEGRAM_ALERT_CHAT_ID"])
def test_missing_config_is_a_loud_failure_naming_the_variable(missing):
    env = {k: v for k, v in ENV.items() if k != missing}

    code, _, err = run("hello", env=env)

    assert code == 2
    assert missing in err


def test_telegram_rejection_fails_with_its_description_and_hides_the_token():
    def opener(req, timeout=None):
        body = io.BytesIO(b'{"ok": false, "description": "chat not found"}')
        raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, body)

    code, _, err = run("hello", opener=opener)

    assert code == 1
    assert "chat not found" in err
    assert TOKEN not in err


def test_network_error_fails_and_hides_the_token():
    def opener(req, timeout=None):
        raise urllib.error.URLError(f"connection refused to {req.full_url}")

    code, _, err = run("hello", opener=opener)

    assert code == 1
    assert "connection refused" in err
    assert TOKEN not in err
