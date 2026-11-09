#!/usr/bin/env python3
"""Send stdin to Telegram through the picklehome alerts bot.

Usage:  some-check | notify_telegram.py [--dry-run]

Reads the message from stdin. Empty input sends nothing and exits 0, so a
silent check stays silent. Plain text only (no parse_mode), so alert text with
backticks or underscores can't trip Telegram's markup parser.

Config, from the environment (secrets come from 1Password via `op run`):
  TELEGRAM_ALERT_BOT_TOKEN   bot token                      (required)
  TELEGRAM_ALERT_CHAT_ID     chat or group id               (required)
  TELEGRAM_ALERT_THREAD_ID   forum topic id inside a group  (optional)

Exit codes: 0 sent (or nothing to send), 1 send failed, 2 missing config.
A failed send is loud on purpose: a notifier that fails quietly is the same
as no notifier. The bot token never appears in output or error text.

stdlib only, so it runs on picklelab's stock python3.
"""

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.telegram.org"
LIMIT = 4096  # Telegram's max message length
SUFFIX = "\n…(truncated)"


def _redact(text, token):
    return text.replace(token, "<token>") if token else text


def _truncate(text):
    if len(text) <= LIMIT:
        return text
    return text[: LIMIT - len(SUFFIX)] + SUFFIX


def build_payload(chat_id, text, thread_id=None):
    payload = {"chat_id": chat_id, "text": text}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    return payload


def main(argv=None, stdin=None, env=None, opener=None, out=None, err=None):
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin if stdin is None else stdin
    env = os.environ if env is None else env
    opener = urllib.request.urlopen if opener is None else opener
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err

    dry_run = "--dry-run" in argv
    text = stdin.read().strip()
    if not text:
        return 0

    token = env.get("TELEGRAM_ALERT_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_ALERT_CHAT_ID", "")
    missing = [
        name
        for name, value in (
            ("TELEGRAM_ALERT_BOT_TOKEN", token),
            ("TELEGRAM_ALERT_CHAT_ID", chat_id),
        )
        if not value
    ]
    if missing:
        print(f"notify_telegram: missing config: {', '.join(missing)}", file=err)
        return 2

    text = _truncate(text)
    payload = build_payload(chat_id, text, env.get("TELEGRAM_ALERT_THREAD_ID"))

    if dry_run:
        print(f"notify_telegram (dry run): would send {len(text)} chars to chat {chat_id}:", file=out)
        print(text, file=out)
        return 0

    request = urllib.request.Request(
        f"{API}/bot{token}/sendMessage",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with opener(request, timeout=15):
            return 0
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("description", "")
        except (ValueError, OSError):
            detail = ""
        print(_redact(f"notify_telegram: Telegram returned {e.code}: {detail or e.reason}", token), file=err)
    except (urllib.error.URLError, OSError) as e:
        print(_redact(f"notify_telegram: could not reach Telegram: {e}", token), file=err)
    return 1


if __name__ == "__main__":
    sys.exit(main())
