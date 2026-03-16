#!/usr/bin/env python3
"""
Network profiler: visit a URL and report hostnames by speed/errors.

Usage:
    uv run --with playwright network-profile.py <url> [--slow-ms 500] [--timeout 10]

Examples:
    uv run --with playwright network-profile.py https://example.com
    uv run --with playwright network-profile.py https://example.com --slow-ms 1000 --timeout 15
"""

import argparse
from collections import defaultdict
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def collect_requests(url: str, timeout_seconds: int) -> list[dict]:
    records = []
    # Track requests that started but haven't finished yet
    pending: dict[str, dict] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def on_request(req):
            pending[req.url] = {
                "url": req.url,
                "hostname": urlparse(req.url).hostname or req.url,
                "method": req.method,
                "status": 0,
                "duration_ms": -1,
                "failed": False,
                "pending": True,
            }

        def on_request_failed(req):
            entry = pending.pop(req.url, None)
            timing = req.timing
            duration_ms = timing["responseEnd"] - timing["requestStart"]
            records.append({
                "url": req.url,
                "hostname": urlparse(req.url).hostname or req.url,
                "method": req.method,
                "status": 0,
                "duration_ms": max(duration_ms, 0),
                "failed": True,
                "pending": False,
            })

        def on_request_finished(req):
            pending.pop(req.url, None)
            try:
                response = req.response()
                timing = req.timing
                duration_ms = timing["responseEnd"] - timing["requestStart"]
                status = response.status if response else 0
                records.append({
                    "url": req.url,
                    "hostname": urlparse(req.url).hostname or req.url,
                    "method": req.method,
                    "status": status,
                    "duration_ms": max(duration_ms, 0),
                    "failed": False,
                    "pending": False,
                })
            except Exception:
                pass

        page.on("request", on_request)
        page.on("requestfailed", on_request_failed)
        page.on("requestfinished", on_request_finished)

        print(f"Navigating to {url} ...")
        try:
            # Use domcontentloaded so we don't hang on pages with persistent connections
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        except Exception as e:
            print(f"  (navigation note: {e})")

        print(f"Capturing requests for {timeout_seconds}s...")
        page.wait_for_timeout(timeout_seconds * 1000)

        # Snapshot any requests still in-flight when we stopped
        for entry in pending.values():
            entry["pending"] = True
            entry["duration_ms"] = timeout_seconds * 1000  # still running = at least this long
            records.append(entry)

        browser.close()

    return records


def summarize(records: list[dict], slow_ms: int) -> None:
    by_host: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_host[r["hostname"]].append(r)

    # Build per-host stats
    rows = []
    for host, reqs in by_host.items():
        durations = [r["duration_ms"] for r in reqs if r["duration_ms"] >= 0]
        errors = [r for r in reqs if r["status"] >= 400 or r["failed"]]
        pending = [r for r in reqs if r["pending"]]
        slow = [r for r in reqs if not r["pending"] and r["duration_ms"] >= slow_ms]
        avg_ms = sum(durations) / len(durations) if durations else 0
        max_ms = max(durations) if durations else 0
        rows.append({
            "host": host,
            "total": len(reqs),
            "errors": len(errors),
            "pending": len(pending),
            "slow": len(slow),
            "avg_ms": avg_ms,
            "max_ms": max_ms,
        })

    # Sort: errors/pending first, then by max duration descending
    rows.sort(key=lambda r: (-(r["errors"] + r["pending"]), -r["max_ms"]))

    # Print report
    print(f"\n{'─' * 80}")
    print(f"  Network Profile Report  (slow threshold: {slow_ms}ms)")
    print(f"{'─' * 80}")
    print(f"  {'HOSTNAME':<40} {'REQ':>4}  {'ERR':>4}  {'PEND':>4}  {'SLOW':>4}  {'AVG':>7}  {'MAX':>7}")
    print(f"{'─' * 80}")

    for r in rows:
        flag = ""
        if r["errors"] > 0:
            flag += " [ERR]"
        if r["pending"] > 0:
            flag += " [PEND]"
        if r["slow"] > 0:
            flag += " [SLOW]"
        print(
            f"  {r['host']:<40} {r['total']:>4}  {r['errors']:>4}  {r['pending']:>4}  {r['slow']:>4}"
            f"  {r['avg_ms']:>6.0f}ms  {r['max_ms']:>6.0f}ms{flag}"
        )

    print(f"{'─' * 80}")
    print(f"  {len(records)} total requests across {len(rows)} hostnames\n")

    # Detail section: show individual slow/errored requests
    problem_requests = [
        r for r in records
        if r["status"] >= 400 or r["failed"] or r["pending"] or r["duration_ms"] >= slow_ms
    ]
    if problem_requests:
        problem_requests.sort(key=lambda r: -r["duration_ms"])
        print(f"  Problem requests (errors, pending, and slowest):")
        print(f"{'─' * 80}")
        for r in problem_requests[:20]:  # cap at 20
            if r["pending"]:
                status_str = "PEND"
            elif r["failed"]:
                status_str = "FAIL"
            else:
                status_str = str(r["status"])
            print(f"  {status_str:>4}  {r['duration_ms']:>6.0f}ms  {r['url'][:70]}")
        if len(problem_requests) > 20:
            print(f"  ... and {len(problem_requests) - 20} more")
        print()


def main():
    parser = argparse.ArgumentParser(description="Profile network requests for a URL")
    parser.add_argument("url", help="URL to visit")
    parser.add_argument("--slow-ms", type=int, default=500, help="Threshold for 'slow' in ms (default: 500)")
    parser.add_argument("--timeout", type=int, default=10, help="Seconds to capture requests (default: 10)")
    args = parser.parse_args()

    records = collect_requests(args.url, args.timeout)
    summarize(records, args.slow_ms)


if __name__ == "__main__":
    main()
