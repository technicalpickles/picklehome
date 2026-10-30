# 3. refuse-deploys-while-brent-is-active

Date: 2026-10-26

## Status

Accepted.

## Context

Deploying `openclaw` or `brineworks-server` restarts the OpenClaw gateway container. A Brent (Telegram bot) turn that is in flight dies with it, and the only sign is a reply that never arrives. Deploys are mostly run by agent sessions, which have no idea whether Josh is mid-conversation with Brent.

## Decision

`homelab/scripts/openclaw-quiet.sh` asks the gateway whether any non-heartbeat session was active in the last 5 minutes (`openclaw sessions --json --all-agents --active 5`, parsed with `node` in the container because neither the image nor the host is guaranteed a `jq`). If so it prints the sessions, newest first, and exits 75, the code the deploy lock already uses for BUSY.

- Both `homelab/services/openclaw/deploy.sh` and `homelab/services/brineworks-server/deploy.sh` run it first, before anything mutates. The check lives host-side, so a hand-run `deploy.sh` is covered too.
- Override with `HOMELAB_DEPLOY_EVEN_IF_BUSY=1 just deploy-<service>`. The recipes forward it over ssh. The script still prints the BUSY block, then proceeds.
- `just openclaw-quiet` runs the same script over ssh (`bash -s`) and changes nothing, so a Mac-side hook can ask before the deploy starts.
- If the sessions can't be listed (container down, `docker exec` fails), it warns and exits 0. A gateway that is down has no turn to kill.
- The window is an argument, or `HOMELAB_DEPLOY_QUIET_MINUTES`, default 5.

## Alternatives considered

- **Mac-side check only**: a hand-run `deploy.sh` on the host and any other deploy path would skip it. The `just` recipe exists for hooks, but the refusal belongs where the restart happens.
- **brineworks-server request logs instead**: only sees the tool calls that reach that service, not a turn that is thinking or talking to the model, and says nothing for an `openclaw` deploy.
- **Block and wait until quiet**: a deploy that hangs for an unknown time inside an agent session is worse than a fast refusal with an override. Same reasoning as the fail-fast lock in [ADR 0002](0002-host-side-deploy-lock.md).

## Consequences

- A deploy within 5 minutes of any Brent activity exits 75 with the sessions that tripped it; re-run later or override.
- Recent activity counts whatever the session's `status`. A turn can pause between tool calls, so a `done` session a minute ago is still a reason to wait.
- A cron session firing near deploy time also trips it. That is intended: it is a turn that would be killed.
- The check reads the live gateway, so it needs the gateway container to answer `openclaw sessions`. If the CLI changes shape, the script treats the failure as quiet (with a warning) rather than blocking deploys.
