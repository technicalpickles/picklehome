---
name: tailscale-cli
description: Use when running `tailscale` commands to debug connectivity, inspect status, or manage `tailscale serve`/`funnel`/Services — especially when `tailscale serve status` looks wrong, `tailscale` isn't found in a shell, `tailscale ping` fails against a host that's clearly up, or you're working across a mix of macOS (GUI app) and Linux (VM/container) nodes in the same tailnet.
---

# Tailscale CLI

## Overview

The `tailscale` CLI behaves differently depending on install shape (macOS GUI app vs. Linux package) and config model (plain node-level `serve` vs. `--service=svc:X` Services). Most "tailscale is broken" moments are actually one of these known gotchas, not a real outage.

## Where the binary lives

| Environment | Binary | Notes |
|---|---|---|
| macOS, Tailscale.app (GUI) | `/Applications/Tailscale.app/Contents/MacOS/Tailscale` | **Not on `$PATH`** — the App Store/direct-download GUI app does not symlink a `tailscale` command by default. `which tailscale` returning nothing does not mean Tailscale isn't running; check the menu-bar icon or `/Applications/Tailscale.app/Contents/MacOS/Tailscale status` directly. Alias it if you use it often: `alias tailscale=/Applications/Tailscale.app/Contents/MacOS/Tailscale`. |
| macOS, Homebrew (`brew install tailscale`) | `tailscale` on `$PATH` | Different install path than the GUI app; if both are present they can diverge in version. |
| Linux (systemd package, VM/container) | `tailscale` on `$PATH`, daemon is `tailscaled` | Standard install. Talks to `tailscaled` over a local socket. |

**Diagnostic tell:** if a `... | jq ...` pipeline throws `jq: parse error: Invalid numeric literal at line 1, column N`, don't debug jq — the upstream command almost certainly failed (e.g. `command not found: tailscale`) and its error text got merged into stdout via `2>&1`, and jq is choking on that text, not real JSON. Re-run the upstream command alone first.

## Root/sudo: don't reach for it by default

`tailscale status` and `tailscale ping` are normally readable by any local user — no `sudo` needed. Mutating commands (`serve`, `funnel`, `up`/`down` in some configs) may need root, *or* may work passwordless if the local user is set as the tailscale operator (`tailscale set --operator=<user>`) or granted a scoped `NOPASSWD` sudo rule for `tailscale serve *`.

Symptom of getting this wrong: `sudo tailscale status --json` hangs asking for a password ("a terminal is required to read the password") on a host where plain `tailscale status` works fine and `sudo tailscale serve status` also works fine (because sudo is scoped to `serve *`, not `status`). Fix: drop the unneeded `sudo`, or check what the sudoers rule actually covers (`sudo -n -l`) before assuming Tailscale itself is broken.

## Services (`svc:`) vs. node-level `serve`

Two different Tailscale features look similar but have separate config and separate status output:

- **Node-level serve**: `tailscale serve --https=443 http://127.0.0.1:8080` — attaches to *this node's* own identity (`<hostname>.<tailnet>.ts.net`).
- **Services**: `tailscale serve --service=svc:myapp --https=443 http://127.0.0.1:8080` — proxies for a named **Service** with its own virtual IP/hostname (`myapp.<tailnet>.ts.net`), independent of which node is currently serving it (enables failover/migration later).

**The gotcha that eats debugging time:** `tailscale serve status` **with no flags only shows node-level routes.** A Service's config is invisible to it — it prints `No serve config` even when the Service is fully configured and traffic is flowing. This looks exactly like "the serve command silently failed" and will send you down a rabbit hole of restarting `tailscaled`, running `tailscale down`/`up`, and re-issuing the serve command, all for nothing.

**Fix:** always check `tailscale serve status --json` and look under `.Services["svc:<name>"]`. That's the real source of truth for Service-based proxies.

```bash
tailscale serve status --json | jq '.Services'
```

**Prerequisite gotcha:** `tailscale serve --service=svc:X ...` does **not** create the Service. A Service must already be defined in the tailnet admin console (Services page, name + port) before the CLI has anything to attach a pending-host-approval to. Running the serve command against an undefined Service reports success ("Serve started and running in the background") but nothing ever shows up as pending, and the hostname never resolves to anything real. Define the Service first, then run `serve --service=`.

## Setting up a brand-new Service (the reliable order)

This exact sequence has had to be rediscovered on every single new Service stood up on picklelab so far (`taskchampion-sync`, `openclaw`, `brineworks`, `open-webui`) — getting the order wrong is the single most common source of "why won't this approve" on a first deploy. Follow it in this order, not the order a deploy script's automated steps happen to run in:

1. **Define the Service in the admin console first**, before running anything else: https://login.tailscale.com/admin/services → "Define Service" → name + port (`443`). A `tailscale serve --service=` call against an undefined Service can report success with nothing to actually show for it.
2. **Run `tailscale serve --service=svc:X --https=443 <target>`** on the host that will proxy it (this is what a service's `deploy.sh` does automatically).
3. **Restart `tailscaled` on that host**: `sudo systemctl restart tailscaled` (Linux). Confirmed required, not optional — until the daemon restarts, the pending-proxy registration from step 2 does not get pushed up to Tailscale's Services backend, and nothing shows up as approvable in step 4. Just re-toggling `serve ... off` / `serve ... on` (what deploy scripts currently print as remediation) is **not** a substitute for this restart.
4. **Approve the pending host** in the admin console (Services page, next to the Service you defined in step 1).
5. **Validate** from a different node: `curl -fsS https://<name>.<tailnet>.ts.net/<health-path>` (never from the serving host itself — see below).

This restart is a deliberate, expected part of standing up a new Service — it's a different situation from the "don't restart tailscaled reflexively" troubleshooting advice further below, which is about an *already-working* Service whose `serve status` output merely looks wrong.

**Open question, not yet root-caused:** a bare `sudo systemctl restart tailscaled` has intermittently prompted for a password on picklelab even when `sudo -n -l` lists `(ALL) NOPASSWD: /usr/bin/systemctl restart *`. Adding `-n` (`sudo -n systemctl restart tailscaled`) succeeded where the bare form didn't in at least one observed case. Worth a follow-up if it recurs — don't assume the sudoers rule is broken from a single instance.

## `tailscale ping` doesn't work on Service virtual IPs

`tailscale ping <service-hostname-or-vip>` returns `no matching peer` even when the Service is healthy — a Service's virtual IP isn't a real WireGuard peer, so ping has nothing to reach. This is expected, not a failure signal. To test a Service, `curl` the HTTPS hostname instead:

```bash
curl -fsS --max-time 8 https://myapp.<tailnet>.ts.net/healthz -o /dev/null -w 'HTTP %{http_code}\n'
```

## Self-curl from the serving host can hang

Curling a Service's own hostname *from the same host that's proxying it* can time out or hang (hairpin/self-connect issue) even when the Service works fine for every other node. Don't conclude a Service is broken from a failed self-test on the host — verify from a different tailnet node (e.g. your Mac, or another peer) before troubleshooting further.

## Quick troubleshooting checklist: "serve status looks wrong"

1. Are you checking `serve status` bare, or `--json`? Bare misses Services — always add `--json` for Services.
2. Did you `sudo` a command that doesn't need it (or that isn't covered by a scoped sudoers rule)? Try without `sudo` first.
3. Is the target a Service (`svc:`) and does it actually exist in the admin console yet? A serve command against an undefined Service "succeeds" but does nothing.
4. Are you testing with `ping` against a Service VIP? Use `curl` against the hostname instead.
5. Are you testing from the same host that's serving the proxy? Test from a different node.
6. Only after 1-5 are ruled out: check `tailscaled` itself (`systemctl status tailscaled`, `tailscale status`, node's `BackendState`).

**Restarting `tailscaled` on a shared host is a real action, not a diagnostic one** — it affects connectivity for every service that host proxies. Don't do it reflexively while chasing a status-display confusion on an *already-working* Service; confirm with whoever owns the host first, and reach for it only after ruling out the display gotchas above. (This is different from standing up a brand-new Service, where the restart is an expected, required step — see "Setting up a brand-new Service" above.)

## Useful commands

| Command | Purpose |
|---|---|
| `tailscale status` | Peer list + this node's connection state (no sudo needed normally) |
| `tailscale status --json` | Same, machine-readable — `.Self`, `.Peer[]`, `.CurrentTailnet`, `.Health` |
| `tailscale serve status --json` | Real Services + node-serve config — see Services section above |
| `tailscale ping <peer>` | WireGuard-level reachability to a real node (not Services) |
| `tailscale version` | Compare versions across nodes when behavior differs between hosts |
| `tailscale serve --service=svc:X ... off` | Disable a Service's proxy config (keeps the Service definition) |
| `tailscale serve clear svc:X` | Remove all serve config for a Service |
