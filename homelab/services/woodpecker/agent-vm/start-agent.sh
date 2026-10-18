#!/usr/bin/env bash
# Start (or replace) the Woodpecker agent container on the agent VM.
#
#   ./start-agent.sh              # VM named woodpecker-agent
#   ./start-agent.sh some-name
#
# Needs the agent created in the Woodpecker UI first (its server-side filter is
# set there), with that agent's token saved to 1Password as the `agent_token`
# field on the "Woodpecker Agent VM" item. The token goes over a pipe into a
# root-only env file on the VM, never argv or the repo. Run it with the
# sandbox off and 1Password approved, same as any `op read`.
set -euo pipefail

VM="${1:-woodpecker-agent}"

op read 'op://picklehome/Woodpecker Agent VM/agent_token' | orb -m "$VM" sudo sh -c '
  umask 077
  install -d -m 700 /etc/woodpecker-agent
  printf "WOODPECKER_AGENT_SECRET=%s\n" "$(cat)" > /etc/woodpecker-agent/env
'

# Root docker socket on purpose: this VM exists only for CI. The picklelab agent
# uses a rootless dockerd instead, because that host runs everything else.
orb -m "$VM" sudo sh -c '
  docker rm -f woodpecker-agent >/dev/null 2>&1 || true
  docker run -d --name woodpecker-agent --restart unless-stopped \
    --env-file /etc/woodpecker-agent/env \
    -e WOODPECKER_SERVER=woodpecker.tail2023b7.ts.net:9000 \
    -e WOODPECKER_AGENT_LABELS=host=laptop \
    -e WOODPECKER_HOSTNAME=woodpecker-agent-vm \
    -e WOODPECKER_MAX_WORKFLOWS=2 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    woodpeckerci/woodpecker-agent:v3
'

echo "==> Started. Logs: orb -m $VM sudo docker logs -f woodpecker-agent"
