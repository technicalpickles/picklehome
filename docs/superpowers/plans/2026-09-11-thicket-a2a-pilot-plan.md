# Thicket A2A Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up thicket's `netd`+`agentd` on a new, isolated OrbStack VM (`thicket-pilot`) hosting a second-brain agent with vault access, then give the local `pickleclaw` dev server an A2A client so it can delegate vault work to that agent — verified first through openclaw's gateway interface, then through one real Telegram round-trip.

**Architecture:** `thicket-pilot` (new OrbStack VM) runs thicket's `netd` (Tailscale node + unix-socket proxy) and `agentd` (A2A server + Claude Code session) under a dedicated `second-brain` unix account, with the `pickled-knowledge` vault reachable from that account over an SSHFS mount back to picklelab. A new `nodes/second-brain-bridge` MCP server in the `pickleclaw` repo exposes one tool (`ask_second_brain`) that speaks A2A to `agentd` over the tailnet; it's registered with pickleclaw's dev-VM gateway the same way `gog-mcp` already is. Nothing in production (picklelab's `second-brain-agent`, `openclaw`, or `pickleclaw`) is touched.

**Tech Stack:** thicket (Go `netd`, TypeScript `agentd`), Node/TypeScript + vitest for the new MCP bridge, Docker Compose (pickleclaw dev VM), Tailscale, OrbStack.

**Spec:** [`docs/plans/2026-09-11-thicket-a2a-pilot.md`](../../plans/2026-09-11-thicket-a2a-pilot.md) (picklehome repo) — read it first; this plan implements its decisions and does not repeat their rationale.

## Global Constraints

- Only `netd` and `agentd` are deployed — no `bridge` (Slack) or `phone` (Twilio); out of scope per spec.
- The A2A caller is the **pickleclaw dev server only** — production `pickleclaw`/`openclaw` are never modified.
- The current picklelab `second-brain-agent` container is never touched or stopped.
- Error handling is minimal by design (per spec) — let failures surface loudly, no retry/fallback logic.
- No automated test suite for the infra side; verification is manual per task. The MCP bridge (Task 5) is genuine new application code and does get unit tests.
- thicket requires Node 22+ and Go 1.27+ (pinned in its own `mise.toml`) and has no installer — every thicket-side step is a real command taken from `github.com/ivy/thicket`'s own `deploy/README.md`, `docs/reference.md`, and `docs/runbook.md`.

---

### Task 1: Provision the `thicket-pilot` VM and thicket toolchain

**Files:** none (infrastructure only — nothing in any git repo changes in this task)

**Interfaces:**
- Produces: a running Ubuntu OrbStack VM named `thicket-pilot`, reachable via `ssh thicket-pilot`, with thicket cloned at `~/src/thicket` and its binaries built. Later tasks build on this.

- [ ] **Step 1: Create the OrbStack VM**

```bash
orb create ubuntu:noble thicket-pilot
```

- [ ] **Step 2: Verify SSH access**

Run: `ssh thicket-pilot -- echo ok`
Expected: `ok`

- [ ] **Step 3: Install mise and thicket's pinned toolchain**

```bash
ssh thicket-pilot -- 'curl https://mise.run | sh'
ssh thicket-pilot -- 'echo "eval \"\$(~/.local/bin/mise activate bash)\"" >> ~/.bashrc'
```

- [ ] **Step 4: Clone thicket and install its pinned Node/Go/pnpm**

```bash
ssh thicket-pilot -- 'git clone https://github.com/ivy/thicket ~/src/thicket'
ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise install'
```

Run: `ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- node --version'`
Expected: `v22.x.x` (or higher, per thicket's `mise.toml` floor)

- [ ] **Step 5: Install dependencies and build**

```bash
ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm install'
ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm compile'
```

Run: `ssh thicket-pilot -- 'ls ~/src/thicket/netd/bin/netd ~/src/thicket/dist-bin/linux-*/thicket-agentd ~/src/thicket/dist-bin/linux-*/thicket'`
Expected: all three paths exist (exact `linux-*` arch suffix depends on the VM's architecture — note it down, it's used in every later `cp` command)

- [ ] **Step 6: Commit nothing yet — this task has no repo changes; note the VM name and built-binary arch suffix in your working notes for later tasks**

---

### Task 2: Create the `second-brain` unix account and roster entry

**Files:**
- Modify (on `thicket-pilot`, inside the thicket checkout): `~/src/thicket/agents.yaml`

**Interfaces:**
- Consumes: `thicket-pilot` VM and thicket checkout from Task 1.
- Produces: a `second-brain` unix account on `thicket-pilot`, a Tailscale auth key at `~second-brain/.config/thicket/tailnet-auth-key`, and a roster entry named `second-brain` that Task 3's `thicket provision` reads.

- [ ] **Step 1: Create the unix account**

```bash
ssh thicket-pilot -- 'sudo useradd --create-home --shell /bin/bash second-brain'
ssh thicket-pilot -- 'sudo loginctl enable-linger second-brain'
```

Run: `ssh thicket-pilot -- 'id second-brain'`
Expected: prints the new user's uid/gid, no error

- [ ] **Step 2: Mint a Tailscale auth key and store it in 1Password**

In the Tailscale admin console, mint a reusable, non-ephemeral auth key tagged `tag:thicket-second-brain` (add that tag to `tagOwners` in the tailnet ACL first if it isn't already there — same one-time step as every other picklehome Tailscale node). Store it in the `picklehome` 1Password vault as a new item `Thicket Second Brain Agent`, field `ts_authkey`.

- [ ] **Step 3: Place the auth key on the VM**

```bash
op read 'op://picklehome/Thicket Second Brain Agent/ts_authkey' | \
  ssh thicket-pilot -- 'sudo -u second-brain sh -c "umask 077; mkdir -p ~second-brain/.config/thicket && cat > ~second-brain/.config/thicket/tailnet-auth-key"'
```

Run: `ssh thicket-pilot -- 'sudo -u second-brain stat -c "%a" ~second-brain/.config/thicket/tailnet-auth-key'`
Expected: `600`

- [ ] **Step 4: Add the agent to the roster**

Edit `~/src/thicket/agents.yaml` on `thicket-pilot` (or edit locally and `scp` it up):

```yaml
agents:
  second-brain:
    host: thicket-pilot
    user: second-brain
    description: Pilot A2A agent with read-write access to the pickled-knowledge vault.
    tag: tag:thicket-second-brain
    harness:
      type: claude-agent-sdk
      cwd: /home/second-brain
      model: claude-sonnet-5
    workspaces:
      vault: /home/second-brain/vault
```

(The `vault` path doesn't exist yet — Task 4 creates it. The roster entry can reference it now; `thicket provision` in Task 3 only needs the entry to exist, not the target directory.)

- [ ] **Step 5: Verify the roster parses**

Run: `ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm exec thicket doctor'` (or the built `thicket` binary directly once Task 3 installs it — for now, running from the checkout is fine)
Expected: no roster/schema errors mentioning `second-brain`

- [ ] **Step 6: This is a local edit inside the thicket checkout on the VM, not a picklehome or pickleclaw commit — no `git commit` here. (If you forked thicket to track this roster entry, commit there instead.)**

---

### Task 3: Render, install, and start `netd` + `agentd`; verify the A2A surface

**Files:** none in picklehome/pickleclaw — this installs into `second-brain`'s home directory on `thicket-pilot`.

**Interfaces:**
- Consumes: roster entry and auth key from Task 2.
- Produces: `thicket-netd` and `thicket-agentd` running as `second-brain`'s systemd user services, and a saved copy of the agent's A2A agent-card JSON — Task 5's client code is built directly from this file's contents, so don't skip saving it.

- [ ] **Step 1: Render the agent's config**

```bash
ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm exec thicket provision --dry-run'
ssh thicket-pilot -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm exec thicket provision'
```

Run: `ssh thicket-pilot -- 'ls ~/.config/thicket/rendered/second-brain/'`
Expected: a directory of rendered config files for the `second-brain` agent

- [ ] **Step 2: Install the rendered config into the agent's own account**

```bash
ssh thicket-pilot -- 'sudo cp -r ~/.config/thicket/rendered/second-brain/. ~second-brain/.config/thicket/ && sudo chown -R second-brain: ~second-brain/.config/thicket'
```

- [ ] **Step 3: Install the binaries into the agent's account**

(Replace `linux-<arch>` with the suffix noted in Task 1, Step 5.)

```bash
ssh thicket-pilot -- 'sudo -u second-brain mkdir -p ~second-brain/.local/bin'
ssh thicket-pilot -- 'sudo cp ~/src/thicket/netd/bin/netd ~second-brain/.local/bin/thicket-netd'
ssh thicket-pilot -- 'sudo cp ~/src/thicket/dist-bin/linux-<arch>/thicket-agentd ~second-brain/.local/bin/'
ssh thicket-pilot -- 'sudo cp ~/src/thicket/dist-bin/linux-<arch>/thicket ~second-brain/.local/bin/'
ssh thicket-pilot -- 'sudo chown -R second-brain: ~second-brain/.local/bin'
```

- [ ] **Step 4: Install Claude Code and authenticate inside the account**

```bash
ssh thicket-pilot -- 'sudo -u second-brain -H bash -c "curl https://mise.run | sh && ~/.local/bin/mise use -g npm:@anthropic-ai/claude-code"'
ssh thicket-pilot -- 'sudo -u second-brain -H claude'
```

Follow the interactive OAuth prompt. Credentials persist under `second-brain`'s home directory.

- [ ] **Step 5: Install and start the systemd user units**

```bash
ssh thicket-pilot -- 'sudo -u second-brain mkdir -p ~second-brain/.config/systemd/user'
ssh thicket-pilot -- 'sudo cp ~/src/thicket/deploy/systemd/thicket-netd.service ~second-brain/.config/systemd/user/'
ssh thicket-pilot -- 'sudo cp ~/src/thicket/deploy/systemd/thicket-agentd.service ~second-brain/.config/systemd/user/'
ssh thicket-pilot -- 'sudo chown -R second-brain: ~second-brain/.config/systemd/user'
ssh thicket-pilot -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user daemon-reload'
ssh thicket-pilot -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user enable --now thicket-agentd.service thicket-netd.service'
```

- [ ] **Step 6: Verify both services are healthy**

Run: `ssh thicket-pilot -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user status thicket-netd thicket-agentd'`
Expected: both `active (running)`

Run: `ssh thicket-pilot -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) $HOME/.local/bin/thicket doctor'`
Expected: no errors for the `second-brain` agent

- [ ] **Step 7: Fetch and save the agent card — Task 5 depends on this file**

```bash
ssh thicket-pilot -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) curl --unix-socket "$XDG_RUNTIME_DIR/thicket/agentd.sock" http://x/.well-known/agent-card.json' > second-brain-agent-card.json
```

Read `second-brain-agent-card.json` and note: the base URL/path A2A messages get POSTed to, and the JSON-RPC method name(s) it advertises (the A2A spec's core method is `message/send`, but confirm against what this card actually declares — don't assume). This file is the actual contract Task 5's client code is written against; nothing in this plan guesses at it.

- [ ] **Step 8: No commit — this task only installs and starts services on the VM. Keep `second-brain-agent-card.json` somewhere you'll have it for Task 5.**

---

### Task 4: Wire and verify vault access for the `second-brain` agent

**Files:** none in any repo — this is host-level VM configuration.

**Interfaces:**
- Consumes: the `second-brain` account from Task 2/3, and picklelab's existing `pickled-knowledge` vault at `/srv/data/obsidian-sync/vaults/pickled-knowledge` (read-write, reachable over Tailscale via `picklelab.tail2023b7.ts.net`).
- Produces: `/home/second-brain/vault` on `thicket-pilot`, mounted read-write via SSHFS onto picklelab's vault directory — the path the roster's `workspaces.vault` entry (Task 2) already points at.

`thicket-pilot` is a separate VM from picklelab (where `obsidian-sync` and the vault actually live), so this can't be a bind mount like the current container uses — it needs a network mount. SSHFS over the existing tailnet reuses infrastructure that's already proven (the same SSH access this plan uses everywhere else), rather than inventing a new sync mechanism for a pilot.

- [ ] **Step 1: Install sshfs on thicket-pilot**

```bash
ssh thicket-pilot -- 'sudo apt-get update && sudo apt-get install -y sshfs'
```

- [ ] **Step 2: Give the second-brain account SSH access to picklelab**

Generate a dedicated ed25519 keypair (no passphrase) on `thicket-pilot` as the `second-brain` user, and add the public key to picklelab's `technicalpickles` account `~/.ssh/authorized_keys` (read-write to the vault directory only in practice, since that's all this key will ever be used for — full account access is broader than needed, but matches how every other picklehome service reaches picklelab today; tightening this is future work, not pilot scope).

```bash
ssh thicket-pilot -- 'sudo -u second-brain ssh-keygen -t ed25519 -f ~second-brain/.ssh/id_ed25519 -N ""'
ssh thicket-pilot -- 'sudo -u second-brain cat ~second-brain/.ssh/id_ed25519.pub'
```

Append the printed public key to `technicalpickles@picklelab:~/.ssh/authorized_keys`.

- [ ] **Step 3: Mount the vault**

```bash
ssh thicket-pilot -- 'sudo -u second-brain mkdir -p ~second-brain/vault'
ssh thicket-pilot -- 'sudo -u second-brain sshfs technicalpickles@picklelab.tail2023b7.ts.net:/srv/data/obsidian-sync/vaults/pickled-knowledge ~second-brain/vault -o reconnect,ServerAliveInterval=15'
```

- [ ] **Step 4: Verify read access**

Run: `ssh thicket-pilot -- 'sudo -u second-brain ls ~second-brain/vault | head -5'`
Expected: real vault file/directory names (not empty, not an error)

- [ ] **Step 5: Verify write access and that obsidian-sync picks it up**

```bash
ssh thicket-pilot -- 'sudo -u second-brain sh -c "echo pilot-test > ~second-brain/vault/thicket-pilot-test.md"'
```

Run (from anywhere with picklelab access): `ssh picklelab -- 'cat /srv/data/obsidian-sync/vaults/pickled-knowledge/thicket-pilot-test.md'`
Expected: `pilot-test`

Delete the test file once confirmed: `ssh thicket-pilot -- 'sudo -u second-brain rm ~second-brain/vault/thicket-pilot-test.md'`

- [ ] **Step 6: Make the mount survive VM reboot**

```bash
ssh thicket-pilot -- 'sudo -u second-brain sh -c "echo \"technicalpickles@picklelab.tail2023b7.ts.net:/srv/data/obsidian-sync/vaults/pickled-knowledge /home/second-brain/vault fuse.sshfs _netdev,reconnect,ServerAliveInterval=15,IdentityFile=/home/second-brain/.ssh/id_ed25519,allow_other 0 0\" | sudo tee -a /etc/fstab"'`
```

- [ ] **Step 7: No commit — host configuration only.**

---

### Task 5: Build the `second-brain-bridge` MCP server

**Files:**
- Create: `nodes/second-brain-bridge/package.json` (in the `pickleclaw` repo)
- Create: `nodes/second-brain-bridge/src/a2a-client.ts`
- Create: `nodes/second-brain-bridge/src/a2a-client.test.ts`
- Create: `nodes/second-brain-bridge/src/server.ts`
- Create: `nodes/second-brain-bridge/vitest.config.ts`
- Create: `nodes/second-brain-bridge/tsconfig.json`

**Interfaces:**
- Consumes: `second-brain-agent-card.json` from Task 3, Step 7 (base URL, method name).
- Produces: `sendToSecondBrain(message: string): Promise<string>` from `a2a-client.ts`, used by `server.ts`'s MCP tool handler and by Task 6's container.

This is genuine new application code (not infra), so it gets real tests, following [TDD](https://github.com/technicalpickles). Work from `pickleclaw/`.

- [ ] **Step 1: Scaffold the package**

```bash
mkdir -p nodes/second-brain-bridge/src
cd nodes/second-brain-bridge
```

`package.json`:

```json
{
  "name": "second-brain-bridge",
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "test": "vitest run",
    "build": "tsc",
    "start": "node dist/server.js"
  },
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "vitest": "^2.1.0"
  }
}
```

`tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "strict": true,
    "esModuleInterop": true
  },
  "include": ["src"]
}
```

`vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { environment: "node" },
});
```

- [ ] **Step 2: Install dependencies**

```bash
npm install
```

- [ ] **Step 3: Write the failing test for the A2A client**

`src/a2a-client.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { sendToSecondBrain } from "./a2a-client.js";

describe("sendToSecondBrain", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("posts a message/send JSON-RPC request and returns the agent's text reply", async () => {
    const mockResponse = {
      jsonrpc: "2.0",
      id: 1,
      result: {
        parts: [{ type: "text", text: "Found 3 notes about that." }],
      },
    };
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse,
    });

    const reply = await sendToSecondBrain("search the vault for X", {
      baseUrl: "https://second-brain.tail2023b7.ts.net",
    });

    expect(reply).toBe("Found 3 notes about that.");
    expect(fetch).toHaveBeenCalledWith(
      "https://second-brain.tail2023b7.ts.net",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "content-type": "application/json" }),
      }),
    );
  });

  it("throws with a clear message when the agent is unreachable", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    await expect(
      sendToSecondBrain("hello", { baseUrl: "https://second-brain.tail2023b7.ts.net" }),
    ).rejects.toThrow(/second-brain agent unreachable/i);
  });
});
```

Note: the exact JSON-RPC request/response shape here follows the A2A spec's `message/send` method as a starting point — before implementing Step 5, open `second-brain-agent-card.json` from Task 3 and confirm the method name and result shape it actually advertises match. Adjust this test first if they don't; don't write the client against an assumption the agent's own card contradicts.

- [ ] **Step 4: Run the test to verify it fails**

Run: `npm test`
Expected: FAIL — `Cannot find module './a2a-client.js'`

- [ ] **Step 5: Implement the client**

`src/a2a-client.ts`:

```typescript
export interface SecondBrainOptions {
  baseUrl: string;
}

export async function sendToSecondBrain(
  message: string,
  options: SecondBrainOptions,
): Promise<string> {
  let response: Response;
  try {
    response = await fetch(options.baseUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "message/send",
        params: {
          message: { parts: [{ type: "text", text: message }] },
        },
      }),
    });
  } catch (err) {
    throw new Error(`second-brain agent unreachable: ${(err as Error).message}`);
  }

  if (!response.ok) {
    throw new Error(`second-brain agent returned HTTP ${response.status}`);
  }

  const body = (await response.json()) as {
    result?: { parts?: { type: string; text?: string }[] };
    error?: { message: string };
  };

  if (body.error) {
    throw new Error(`second-brain agent error: ${body.error.message}`);
  }

  const text = body.result?.parts?.find((p) => p.type === "text")?.text;
  if (!text) {
    throw new Error("second-brain agent returned no text part");
  }
  return text;
}
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `npm test`
Expected: PASS (2 tests)

- [ ] **Step 7: Write the MCP server that exposes this as a tool**

Uses the streamable-HTTP transport (not stdio) so this matches how `gog-mcp` is already reached in `dev-vm/compose.yaml` (`http://gog-mcp:8787/mcp`) — the gateway calls it over the network, not as a subprocess.

`src/server.ts`:

```typescript
import http from "node:http";
import { randomUUID } from "node:crypto";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { sendToSecondBrain } from "./a2a-client.js";

const baseUrl = process.env.SECOND_BRAIN_A2A_URL;
if (!baseUrl) {
  throw new Error("SECOND_BRAIN_A2A_URL is required");
}

function buildServer(): Server {
  const server = new Server(
    { name: "second-brain-bridge", version: "0.1.0" },
    { capabilities: { tools: {} } },
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: [
      {
        name: "ask_second_brain",
        description: "Delegate a vault search/read/write task to the second-brain agent.",
        inputSchema: {
          type: "object",
          properties: { message: { type: "string" } },
          required: ["message"],
        },
      },
    ],
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    if (request.params.name !== "ask_second_brain") {
      throw new Error(`unknown tool: ${request.params.name}`);
    }
    const message = (request.params.arguments as { message: string }).message;
    const reply = await sendToSecondBrain(message, { baseUrl: baseUrl! });
    return { content: [{ type: "text", text: reply }] };
  });

  return server;
}

// One transport+server pair per session, per the SDK's streamable-HTTP pattern —
// this bridge only ever has one caller (the dev-VM gateway), so an in-memory map
// keyed by session ID is sufficient; nothing here needs to survive a restart.
const sessions = new Map<string, StreamableHTTPServerTransport>();

const httpServer = http.createServer(async (req, res) => {
  if (req.url !== "/mcp") {
    res.writeHead(404).end();
    return;
  }

  const sessionId = req.headers["mcp-session-id"] as string | undefined;
  let transport = sessionId ? sessions.get(sessionId) : undefined;

  if (!transport) {
    transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: () => randomUUID(),
      onsessioninitialized: (id) => sessions.set(id, transport!),
    });
    await buildServer().connect(transport);
  }

  await transport.handleRequest(req, res);
});

httpServer.listen(8787, "0.0.0.0", () => {
  console.log("second-brain-bridge listening on :8787/mcp");
});
```

- [ ] **Step 8: Build and smoke-test the server standalone**

```bash
npm run build
SECOND_BRAIN_A2A_URL=https://second-brain.tail2023b7.ts.net node dist/server.js &
```

Run: `curl -s http://localhost:8787/mcp -X POST -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`
Expected: JSON-RPC response listing the `ask_second_brain` tool. Kill the process (`kill %1`) once confirmed — full end-to-end verification against the real agent happens in Task 6.

- [ ] **Step 9: Commit**

```bash
git add nodes/second-brain-bridge/
git commit -m "feat(second-brain-bridge): add A2A client and MCP server for second-brain agent"
```

---

### Task 6: Containerize and register the bridge with pickleclaw's dev-VM gateway

**Files:**
- Create: `nodes/second-brain-bridge/Dockerfile`
- Modify: `openclaw-config/mcp.json5` (dev-local — do not touch the symlinked production copy)
- Modify: `dev-vm/compose.yaml`

**Interfaces:**
- Consumes: `server.ts`/`a2a-client.ts` from Task 5.
- Produces: a `second-brain-bridge` container reachable at `http://second-brain-bridge:8787` from the dev VM's `openclaw` gateway container, registered as an MCP server the gateway can call `ask_second_brain` on.

This follows the exact pattern `gog-mcp` already uses in `dev-vm/compose.yaml` (own container, no host port, gateway reaches it by service name).

- [ ] **Step 0: Confirm the dev VM can actually reach `thicket-pilot` over the tailnet, before writing any code**

The `pickleclaw` dev VM's own Tailscale membership hasn't been established anywhere in this plan yet, and thicket's `netd` enforces ACLs strictly (no host-local shortcuts — see `docs/reference.md`'s trust model), so a container inside the dev VM reaching `second-brain.tail2023b7.ts.net` is not guaranteed just because the Mac itself is on the tailnet.

Run: `ssh openclaw@orb -- 'tailscale status'` (or, from inside a throwaway container on the dev VM's compose network: `docker run --rm --network dev-vm_default curlimages/curl curl -sv https://second-brain.tail2023b7.ts.net --unix-socket /dev/null 2>&1 | head -5` as a reachability smoke test)

- If the dev VM (or Docker Desktop/OrbStack's VM host) is already tailnet-joined: add a Tailscale ACL rule granting that node's tag reach to `tag:thicket-second-brain` on `netd`'s port, then re-test.
- If it isn't: install the Tailscale client inside the `pickleclaw` dev VM (not just the Mac host) and join it to the tailnet with its own tag, then add the same ACL grant.

Do not proceed to Step 1 until a plain `curl` to `https://second-brain.tail2023b7.ts.net` from inside the dev VM's network succeeds (even a TLS/404 response is fine — the point is confirming the packet gets there at all, not that the request is well-formed yet).

- [ ] **Step 1: Write the Dockerfile**

`nodes/second-brain-bridge/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --omit=dev
COPY tsconfig.json ./
COPY src ./src
RUN npm install typescript && npm run build && npm prune --omit=dev

ENV SECOND_BRAIN_A2A_URL=""
EXPOSE 8787
CMD ["node", "dist/server.js"]
```

- [ ] **Step 2: Register the MCP server**

Add to the local (dev-only, non-symlinked) `openclaw-config/mcp.json5`:

```json5
{
  servers: {
    // existing gog entry stays as-is
    second_brain: {
      transport: "streamable-http",
      url: "http://second-brain-bridge:8787/mcp",
    },
  },
}
```

- [ ] **Step 3: Add the compose service**

In `dev-vm/compose.yaml`, alongside the existing `gog-mcp`/`goplaces-node` blocks:

```yaml
  second-brain-bridge:
    build:
      context: ../nodes/second-brain-bridge
    restart: unless-stopped
    environment:
      SECOND_BRAIN_A2A_URL: https://second-brain.tail2023b7.ts.net
```

(No `env_file`/secrets needed — the A2A endpoint isn't a credential, and thicket's Tailscale ACLs are what actually gate access, not a bearer token.)

- [ ] **Step 4: Build and start it**

```bash
cd dev-vm
docker compose up -d --build second-brain-bridge
```

Run: `docker compose logs second-brain-bridge`
Expected: no crash-loop; process stays up

- [ ] **Step 5: Verify the gateway sees the tool**

Run: `docker exec dev-vm-openclaw-1 curl -s http://second-brain-bridge:8787/mcp -X POST -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'`
Expected: JSON response listing `ask_second_brain` among the tools

- [ ] **Step 6: Commit**

```bash
git add nodes/second-brain-bridge/Dockerfile dev-vm/compose.yaml openclaw-config/mcp.json5
git commit -m "feat(dev-vm): wire second-brain-bridge into the gateway"
```

---

### Task 7: End-to-end verification — gateway interface, then Telegram

**Files:** none — this task is pure verification against the pieces built in Tasks 1–6.

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the pilot's pass/fail verdict against the spec's four "what the pilot needs to prove" criteria.

- [ ] **Step 1: Iterate via the gateway interface**

Open the dev VM's Control UI (`ssh -N -L 18789:127.0.0.1:18789 openclaw@orb`, then `http://127.0.0.1:18789`) or use the `openclaw` CLI directly against the dev gateway. Send a message that should trigger `ask_second_brain` (e.g. "ask the second brain to list recent notes").

Expected: the gateway calls the tool, `second-brain-bridge`'s logs show the outbound A2A call, and a real vault-derived answer comes back — not a canned/error response.

- [ ] **Step 2: Fix anything broken, re-run Step 1 until it's clean**

This is the fast-iteration loop the spec calls for — don't move to Telegram until Step 1 is reliably working.

- [ ] **Step 3: Final full-path check over real Telegram**

Send an actual Telegram message to the pickleclaw dev bot with the same kind of vault request. Confirm the round-trip completes through Telegram → pickleclaw dev → second-brain-bridge → thicket-pilot → vault → back.

- [ ] **Step 4: Record the pilot's findings**

Write up, in the spec doc (`docs/plans/2026-09-11-thicket-a2a-pilot.md`) or a follow-up note, how each of these held up:
1. A2A round-trip end-to-end — pass/fail
2. `agentd`'s Claude Code session reliability vs. today's tmux setup, and whether the update/logout friction recurred
3. Whether unix-account + Tailscale ACL isolation is something worth operating going forward
4. A real cost estimate for migrating picklelab's `second-brain-agent` onto this model, given thicket's lack of an installer

This is the artifact that decides whether the broader migration (mentioned in the spec's motivation) proceeds.

- [ ] **Step 5: Commit the findings**

```bash
git add docs/plans/2026-09-11-thicket-a2a-pilot.md
git commit -m "docs(plans): record thicket A2A pilot findings"
```
