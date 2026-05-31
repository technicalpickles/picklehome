#!/usr/bin/env python3
"""
DNS resolution comparison tool: queries multiple nameservers directly
from the local machine and compares the IPs returned.

Useful for diagnosing CDN routing differences between resolvers.

Usage:
    uv run --with dnspython network/resolve.py <hostname> [<hostname> ...]
    uv run --with dnspython network/resolve.py static.canva.com claude.ai
"""

import argparse
import sys
import dns.resolver

# Nameservers to compare, in order of interest
NAMESERVERS = {
    "1.1.1.1   (Cloudflare)": "1.1.1.1",
    "8.8.8.8   (Google)    ": "8.8.8.8",
    "192.168.8.254 (BGW)   ": "192.168.8.254",
    "192.168.1.1   (USG)   ": "192.168.1.1",
}


def resolve(host: str, nameserver: str, timeout: float = 3.0) -> list[str]:
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = [nameserver]
    r.timeout = timeout
    r.lifetime = timeout
    try:
        answers = r.resolve(host, "A")
        return sorted(str(rr) for rr in answers)
    except dns.resolver.NXDOMAIN:
        return ["NXDOMAIN"]
    except dns.resolver.NoAnswer:
        return ["(no answer)"]
    except dns.exception.Timeout:
        return ["(timeout)"]
    except Exception as e:
        return [f"(error: {e})"]


def cmd_compare(hosts: list[str]):
    for host in hosts:
        print(f"  {host}")
        print("  " + "─" * 58)
        results = {}
        for label, ns in NAMESERVERS.items():
            ips = resolve(host, ns)
            results[label] = ips
            status = ", ".join(ips)
            print(f"    {label}  {status}")

        ip_sets = [frozenset(v) for v in results.values()
                   if v and v != ["(timeout)"] and v != ["(no answer)"]]
        if len(set(ip_sets)) > 1:
            print("    *** IPs DIFFER across nameservers ***")
        elif any("timeout" in str(v) for v in results.values()):
            print("    *** timeout on one or more nameservers ***")
        print()


def main():
    parser = argparse.ArgumentParser(description="DNS resolution comparison across nameservers")
    parser.add_argument("hosts", nargs="+", help="Hostnames to resolve")
    args = parser.parse_args()

    print(f"DNS comparison: {', '.join(args.hosts)}")
    print("─" * 60)
    print()
    cmd_compare(args.hosts)


if __name__ == "__main__":
    main()
