#!/usr/bin/env python3
"""Dump Open WebUI's persistent config + per-model capability overrides.

Runs inside the open-webui container (no sqlite3 CLI in the image, so this
uses the stdlib sqlite3 module against the same webui.db the backend reads).
Secrets are reported as set/unset, never printed.

Usage (from the Mac): just open-webui-inspect-config [prefix]
"""
import json
import sqlite3
import sys

DB_PATH = "/app/backend/data/webui.db"

SECRET_SUFFIXES = ("api_key", "password", "secret", "token")

DEFAULT_PREFIXES = ("web.search.", "web.loader.", "models.default_metadata")


def mask(key, value):
    if any(key.endswith(suffix) for suffix in SECRET_SUFFIXES):
        try:
            unwrapped = json.loads(value) if isinstance(value, str) else value
        except (TypeError, json.JSONDecodeError):
            unwrapped = value
        is_set = bool(unwrapped) and unwrapped not in ("", "null")
        return f"<{'set' if is_set else 'NOT SET'}>"
    return value


def main():
    prefixes = tuple(sys.argv[1:]) or DEFAULT_PREFIXES
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT key, value FROM config ORDER BY key")
    rows = cur.fetchall()

    print("== config ==")
    for key, value in rows:
        if any(key == p or key.startswith(p) for p in prefixes):
            print(f"{key} = {mask(key, value)}")

    print("\n== model capability overrides ==")
    cur.execute("SELECT id, name, meta, is_active FROM model")
    model_rows = cur.fetchall()
    if not model_rows:
        print("(no rows -- every model is using default_metadata / built-in defaults, no per-model overrides exist)")
    for model_id, name, meta, is_active in model_rows:
        meta_d = json.loads(meta) if meta else {}
        caps = meta_d.get("capabilities", {})
        print(f"{model_id} | {name} | active={bool(is_active)} | capabilities={caps}")


if __name__ == "__main__":
    main()
