# Plan: Thicket A2A Pilot for Second Brain Agent

## Context

`second-brain-agent` (see [`2026-06-20-second-brain-agent.md`](2026-06-20-second-brain-agent.md)) is a working, deployed service: Ubuntu container, sshd, tmux, Claude Code CLI, reachable over Tailscale SSH/mosh, `pickled-knowledge` vault mounted read-write at `/vault`. It works, but access is entirely interactive (SSH in, attach tmux) — there's no way for another agent or service to hand it a task programmatically.

[thicket](https://github.com/ivy/thicket) is an open-source "fleet of AI agents" project that treats agent-to-agent (A2A) as a first-class surface. Its model: an agent's identity is a `(host, unix user)` pair. Components:
- **netd** (Go): a Tailscale node per agent, bridging the tailnet into a unix socket
- **agentd** (TypeScript): A2A server + Claude Code session manager (active and dormant sessions) for one unix account
- **bridge** (TypeScript): Slack Socket Mode ↔ A2A
- **phone** (TypeScript): Twilio ConversationRelay ↔ A2A

This is architecturally different from every other picklelab service, which uses Docker Compose + systemd with one container = one Tailscale node (the `ts-agent` sidecar pattern, see `homelab/services/README.md`). Thicket's isolation boundary is unix accounts + Tailscale ACLs, not containers.

Thicket is early: it describes itself as "running, for one operator," says "there is no installer yet, so an agent host needs a checkout," and multi-host deployment is unfinished. Single-host has been proven end-to-end via Slack; the phone bridge works but is undeployed.

### Motivation

The driver is wanting A2A as a first-class surface on second-brain-agent — not a specific complaint about the current SSH/tmux access model (that's mildly annoying at most, see "Known friction" below). Concrete callers, in rough priority order:
1. **openclaw** delegating vault work (e.g. "search the vault for X", "file a note about Y") from its Telegram-facing chat interface
2. Other homelab agents querying it as a shared knowledge service
3. The user, from Claude Code elsewhere, delegating to the always-on agent instead of SSHing in
4. Unnamed future callers — the appeal is general A2A surface area, not one fixed integration

This is explicitly **the pilot for a broader migration** of picklelab's agent-hosting model, not a one-off. If it proves out, `brineworks-agent` and/or openclaw's own agent could eventually move to the same fleet model.

### Known friction (secondary, not a design driver)

Two things about the current setup are mildly annoying, worth watching during the pilot but not required to fix:
- Claude Code the package frequently complains about being out of date and can't self-update from inside the container
- Getting logged out periodically

`agentd` owns Claude Code session lifecycle in thicket's model, so it's worth noting whether this incidentally does better here — but it's not a success criterion.

## Approach

Three options were considered:

- **(A) Integrate directly into picklelab now** — provision thicket's unix accounts and `netd`/`agentd` straight on the production NUC, retire the current container once working. Fastest to a real migration, but risks the one homelab box on unproven, installer-less software.
- **(B) Pilot in isolation, then decide** — stand up thicket on a throwaway host, prove the A2A path end-to-end, leave the current second-brain-agent untouched throughout. **Chosen.**
- **(C) Cherry-pick agentd only** — keep the existing container + `ts-agent` sidecar, bolt on just an A2A server. Least disruptive, but discards thicket's actual security model (unix-account + ACL isolation), so it's not really "adopting thicket," just borrowing the protocol idea.

(B) was chosen because it matches "pilot for a broader migration" literally, costs only a throwaway VM, and nothing currently working is put at risk.

## Architecture

Entirely Mac-side, entirely separate from production:

- **`thicket-pilot`**: a new OrbStack VM (sibling to `pickled-coi`), running thicket's `netd` + `agentd` under a dedicated unix account for the second-brain agent. `pickled-knowledge` vault reachable from that account (mount or sync, mirroring today's `/vault` approach). Joins the tailnet with its own `tag:thicket-*` ACL tags, isolated per thicket's own model.
- **pickleclaw dev server (local, NOT production)**: the existing Mac-side `pickleclaw` local dev instance, which already has Telegram wired up, gains an A2A client capability to call `agentd` on `thicket-pilot`. This gives a real end-to-end test surface (actual Telegram messages) without touching the production `openclaw` deploy on picklelab or production `pickleclaw`.

The current second-brain-agent container on picklelab is untouched for the duration of the pilot — this is purely additive.

## Data flow

```
Telegram message
  → pickleclaw (local dev server)
  → A2A call to agentd on thicket-pilot
  → Claude Code session (agentd-managed, vault access)
  → response over A2A
  → pickleclaw (local dev server)
  → Telegram
```

## What the pilot needs to prove

1. The A2A round-trip actually works end-to-end (Telegram in, vault-aware response out)
2. `agentd`'s Claude Code session management is at least as reliable as today's tmux setup (bonus if it incidentally fixes the update/logout friction)
3. Unix-account + Tailscale ACL isolation is something worth operating, vs. the container model already used everywhere else
4. A rough sense of what a real migration would cost, given thicket has no installer yet and requires a host checkout

## Error handling

Minimal — this is a pilot. Let failures surface loudly (error in Telegram or in logs) and debug by hand. No retry/fallback/restart logic is in scope for the pilot itself.

## Testing

No automated test suite. Verification is manual: send a Telegram message via the pickleclaw dev server, confirm it reaches the vault-aware agent on `thicket-pilot` and a sensible response comes back. Success is judged against the four "what the pilot needs to prove" items above.

## Confirmed decisions

- Pilot host: new OrbStack VM (`thicket-pilot`), not an Incus container, not directly on picklelab
- A2A caller: **pickleclaw dev server only** — production pickleclaw/openclaw are not touched
- Scope: full thicket stack (`netd` + `agentd`), not a cherry-picked A2A-only bolt-on
- This is the pilot for a broader agent-hosting migration, not a one-off experiment
- Current second-brain-agent container stays running, untouched, throughout

## Out of scope (for the pilot)

- Any change to production `openclaw` or `pickleclaw`
- Retiring or modifying the current second-brain-agent container
- Multi-host thicket deployment (thicket itself doesn't really support this yet)
- `bridge` (Slack) or `phone` (Twilio) components — Telegram via pickleclaw dev is the test surface
- Migrating `brineworks-agent` or anything else onto thicket
- Automated resilience/retry logic

## Open questions (to resolve during implementation planning)

- Exact mechanism for vault access from the thicket unix account (bind mount if colocated with obsidian-sync data, or a sync mechanism if `thicket-pilot` is a separate VM from wherever obsidian-sync runs)
- Whether pickleclaw's A2A client is a new dedicated tool/node or wired into its existing message-handling path
- Tailscale ACL tag design for `tag:thicket-*` given the existing tailnet ACL structure
