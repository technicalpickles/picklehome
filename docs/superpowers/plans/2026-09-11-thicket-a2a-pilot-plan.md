# Thicket A2A Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up thicket's `netd`+`agentd` on a new, isolated OrbStack VM (`thicket-pilot`) hosting a second-brain agent with vault access, then give the local `pickleclaw` dev server an A2A client so it can delegate vault work to that agent — verified first through openclaw's gateway interface, then through one real Telegram round-trip.

**Architecture:** `thicket-pilot` (new OrbStack VM) runs thicket's `netd` (Tailscale node + unix-socket proxy) and `agentd` (A2A server + Claude Code session) under a dedicated `second-brain` unix account, with the user's `~/Vaults/pickled-knowledge` vault reachable from that account via a symlink onto OrbStack's existing virtiofs mount of the Mac's filesystem (no SSHFS, no picklelab involvement — see Task 4's corrected text). A new `nodes/second-brain-bridge` MCP server in the `pickleclaw` repo exposes one tool (`ask_second_brain`) that speaks A2A to `agentd` over the tailnet; it's registered with pickleclaw's dev-VM gateway the same way `gog-mcp` already is. Nothing in production (picklelab's `second-brain-agent`, `openclaw`, or `pickleclaw`) is touched.

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
- Produces: a running Ubuntu OrbStack VM named `thicket-pilot`, reachable via `ssh thicket-pilot@orb`, with thicket cloned at `~/src/thicket` and its binaries built at `dist-bin/linux-x64/` + `netd/bin/netd`. Later tasks build on this.

> **Corrected 2026-09-11 after a real dry run.** Three things the first attempt found: (1) plain `ssh thicket-pilot` doesn't resolve on this Mac — OrbStack's `<machine>@orb` form (via its local proxy on `127.0.0.1:32222`, configured in `~/.orbstack/ssh/config`) is what actually works, and it's a loopback connection so it works fine inside the sandbox too. (2) thicket's build fleet (`scripts/platforms.ts`) only supports `macos-arm64` and `linux-x64` — there is no `linux-arm64` target, so on this (Apple Silicon) Mac the VM must be created as `amd64`, not the host-default `arm64`, or `pnpm compile` throws `no fleet platform for linux-arm64`. (3) thicket's JS toolchain is **bun**, not node — `mise.toml` declares no `node` tool at all, and `pnpm compile` calls `bun run scripts/compile.ts`. Steps below reflect all three corrections; the `linux-x64` suffix is now known rather than discovered per-run.

- [ ] **Step 1: Create the OrbStack VM as amd64**

```bash
orb create -a amd64 ubuntu:noble thicket-pilot
```

Run: `orb list`
Expected: a `thicket-pilot` row showing `amd64` as the architecture

- [ ] **Step 2: Verify SSH access**

Run: `ssh thicket-pilot@orb -- echo ok`
Expected: `ok`

- [ ] **Step 3: Install git and mise, then thicket's pinned toolchain**

The base `ubuntu:noble` OrbStack image ships without `git`:

```bash
ssh thicket-pilot@orb -- 'sudo apt-get update -qq && sudo apt-get install -y -qq git'
ssh thicket-pilot@orb -- 'curl https://mise.run | sh'
ssh thicket-pilot@orb -- 'echo "eval \"\$(~/.local/bin/mise activate bash)\"" >> ~/.bashrc'
```

- [ ] **Step 4: Clone thicket and install its pinned bun/Go/pnpm**

```bash
ssh thicket-pilot@orb -- 'git clone https://github.com/ivy/thicket ~/src/thicket'
ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise install'
```

Run: `ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- bun --version'`
Expected: a version string (thicket pins `bun` in its own `mise.toml`; there is no `node` tool to check)

- [ ] **Step 5: Install dependencies and build (TypeScript via bun, netd via Go)**

`pnpm compile` builds the bun-compiled binaries (`agentd`, `bridge`, `thicket` CLI) for the fleet's configured platforms; it does **not** build `netd`, which has its own script:

```bash
ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm install'
ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm compile'
ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm run build:netd'
```

Run: `ssh thicket-pilot@orb -- 'ls ~/src/thicket/netd/bin/netd ~/src/thicket/dist-bin/linux-x64/thicket-agentd ~/src/thicket/dist-bin/linux-x64/thicket'`
Expected: all three paths exist. (The `linux-x64` suffix is now fixed — thicket's fleet table only ever produces this one Linux target, so every later task's `cp` command uses it literally, no per-run discovery needed.)

- [ ] **Step 6: Commit nothing yet — this task has no repo changes**

---

### Task 2: Create the `second-brain` unix account and roster entry

**Files:**
- Modify (on `thicket-pilot`, inside the thicket checkout): `~/src/thicket/agents.yaml`

**Interfaces:**
- Consumes: `thicket-pilot` VM and thicket checkout from Task 1.
- Produces: a `second-brain` unix account on `thicket-pilot`, a Tailscale auth key at `~second-brain/.config/thicket/tailnet-auth-key`, and a roster entry named `second-brain` that Task 3's `thicket provision` reads.

- [ ] **Step 1: Create the unix account**

```bash
ssh thicket-pilot@orb -- 'sudo useradd --create-home --shell /bin/bash second-brain'
ssh thicket-pilot@orb -- 'sudo loginctl enable-linger second-brain'
```

Run: `ssh thicket-pilot@orb -- 'id second-brain'`
Expected: prints the new user's uid/gid, no error

- [ ] **Step 2: Mint a Tailscale auth key and store it in 1Password**

In the Tailscale admin console, mint a reusable, non-ephemeral auth key tagged `tag:thicket-second-brain` (add that tag to `tagOwners` in the tailnet ACL first if it isn't already there — same one-time step as every other picklehome Tailscale node). Store it in the `picklehome` 1Password vault as a new item `Thicket Second Brain Agent`, field `ts_authkey`.

- [ ] **Step 3: Place the auth key on the VM**

```bash
op read 'op://picklehome/Thicket Second Brain Agent/ts_authkey' | \
  ssh thicket-pilot@orb -- 'sudo -u second-brain sh -c "umask 077; mkdir -p ~second-brain/.config/thicket && cat > ~second-brain/.config/thicket/tailnet-auth-key"'
```

Run: `ssh thicket-pilot@orb -- 'sudo -u second-brain stat -c "%a" ~second-brain/.config/thicket/tailnet-auth-key'`
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

Run: `ssh thicket-pilot@orb -- 'cd ~/src/thicket && ~/.local/bin/mise exec -- pnpm exec thicket doctor'` (or the built `thicket` binary directly once Task 3 installs it — for now, running from the checkout is fine)
Expected: no roster/schema errors mentioning `second-brain`

- [ ] **Step 6: This is a local edit inside the thicket checkout on the VM, not a picklehome or pickleclaw commit — no `git commit` here. (If you forked thicket to track this roster entry, commit there instead.)**

---

### Task 3: Render, install, and start `netd` + `agentd`; verify the A2A surface

**Files:** none in picklehome/pickleclaw — this installs into `second-brain`'s home directory on `thicket-pilot`.

**Interfaces:**
- Consumes: roster entry and auth key from Task 2.
- Produces: `thicket-netd` and `thicket-agentd` running as `second-brain`'s systemd user services, and a saved copy of the agent's A2A agent-card JSON — Task 5's client code is built directly from this file's contents, so don't skip saving it.

- [ ] **Step 1: Render the agent's config**

> **Corrected 2026-09-11 after a real dry run.** thicket has two separate commands that a first read of the docs conflates: `provision` manages each agent's *Slack app* (creating/updating a real Slack app via `apps.manifest.create`, gated on a Slack app-configuration token, and enforcing a ≥174-character `description` per agent — all Slack-specific, confirmed straight from `apps/cli/src/bin.ts` and `provision.ts`) — completely orthogonal to this pilot, which deploys no `bridge`/Slack surface at all. `render` is the command that actually produces the per-account config tree (`agents.yaml`, `agentd.json`, `netd.json`) that `netd`/`agentd` read; it shares the exact same output path (`~/.config/thicket/rendered/<agent>/` by default) and touches nothing Slack-related. Use `render`, not `provision`, here.

```bash
ssh thicket-pilot@orb -- 'cd ~/src/thicket && THICKET_AGENTS_FILE=$HOME/src/thicket/agents.yaml ~/.local/bin/mise exec -- ./dist-bin/linux-x64/thicket render'
```

(`pnpm exec thicket` doesn't resolve as a command — use the built binary directly, same as every other `thicket` invocation in this plan. `THICKET_AGENTS_FILE` is needed because the binary otherwise looks for `~/.config/thicket/agents.yaml`, which doesn't exist — the roster lives in the checkout at `~/src/thicket/agents.yaml`.)

Run: `ssh thicket-pilot@orb -- 'ls ~/.config/thicket/rendered/second-brain/'`
Expected: a directory of rendered config files for the `second-brain` agent (`agents.yaml`, `agentd.json`, `netd.json`)

- [ ] **Step 2: Install the rendered config into the agent's own account**

```bash
ssh thicket-pilot@orb -- 'sudo cp -r ~/.config/thicket/rendered/second-brain/. ~second-brain/.config/thicket/ && sudo chown -R second-brain: ~second-brain/.config/thicket'
```

- [ ] **Step 3: Install the binaries into the agent's account**

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain mkdir -p ~second-brain/.local/bin'
ssh thicket-pilot@orb -- 'sudo cp ~/src/thicket/netd/bin/netd ~second-brain/.local/bin/thicket-netd'
ssh thicket-pilot@orb -- 'sudo cp ~/src/thicket/dist-bin/linux-x64/thicket-agentd ~second-brain/.local/bin/'
ssh thicket-pilot@orb -- 'sudo cp ~/src/thicket/dist-bin/linux-x64/thicket ~second-brain/.local/bin/'
ssh thicket-pilot@orb -- 'sudo chown -R second-brain: ~second-brain/.local/bin'
```

- [ ] **Step 4: Install Claude Code and authenticate inside the account**

> **Corrected 2026-09-11:** two issues, both fixed here. (1) `sudo -u second-brain -H claude` fails with `command not found` — `sudo` execs the binary directly with no shell profile sourced, so `mise`'s shim for the globally-installed `claude` is never on PATH; use `mise exec` to resolve it explicitly. (2) `mise exec -- claude` (or its postinstall) then fails — mise's npm backend doesn't always run `@anthropic-ai/claude-code`'s postinstall (`install.cjs`, which fetches the native binary), and even running it manually needs a `node` binary, which was never installed as a mise tool for this account (only `claude-code` itself was). Install `node` via mise first, then run the postinstall manually if `claude --version` still fails afterward.

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain -H bash -c "curl https://mise.run | sh && ~/.local/bin/mise use -g npm:@anthropic-ai/claude-code && ~/.local/bin/mise use -g node@22"'
ssh thicket-pilot@orb -- 'sudo -u second-brain -H bash -c "~/.local/bin/mise exec -- claude --version"'
```

If the last command errors with `claude native binary not installed`, find and run its postinstall manually first:
```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain -H bash -c "find ~/.local/share/mise -path \"*@anthropic-ai/claude-code/install.cjs\""'
# then, using the path that printed:
ssh thicket-pilot@orb -- 'sudo -u second-brain -H bash -c "~/.local/bin/mise exec -- node <PATH_FROM_ABOVE>"'
```

Once `claude --version` succeeds, log in interactively. One more gotcha here: `sudo -H` sets `$HOME` correctly but leaves `SUDO_USER`/`SUDO_UID`/`SUDO_GID` set to the invoking user (`technicalpickles`) — Claude Code evidently prefers `SUDO_USER`'s home over `$HOME` for settings resolution (observed live: it tried to read `/home/technicalpickles/.claude/settings.json` despite `$HOME=/home/second-brain`), so unset them first:

```bash
ssh -t thicket-pilot@orb -- 'sudo -u second-brain -H bash -c "unset SUDO_USER SUDO_UID SUDO_GID SUDO_COMMAND; ~/.local/bin/mise exec -- claude"'
```

Follow the interactive OAuth prompt (`-t` allocates a pty, needed for the interactive flow). Credentials persist under `second-brain`'s home directory.

- [ ] **Step 5: Install and start the systemd user units**

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain mkdir -p ~second-brain/.config/systemd/user'
ssh thicket-pilot@orb -- 'sudo cp ~/src/thicket/deploy/systemd/thicket-netd.service ~second-brain/.config/systemd/user/'
ssh thicket-pilot@orb -- 'sudo cp ~/src/thicket/deploy/systemd/thicket-agentd.service ~second-brain/.config/systemd/user/'
ssh thicket-pilot@orb -- 'sudo chown -R second-brain: ~second-brain/.config/systemd/user'
ssh thicket-pilot@orb -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user daemon-reload'
ssh thicket-pilot@orb -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user enable --now thicket-agentd.service thicket-netd.service'
```

> **Corrected 2026-09-12 after Task 6's live A2A test.** A real `SendMessage` call reached `agentd` fine but every task failed: `"Agent execution error: Native CLI binary for linux-x64 not found."` `agentd`'s config (`apps/agentd/src/config.ts`) resolves the Claude binary via `findOnPath("claude")` against its own process `PATH` (or `THICKET_CLAUDE_EXECUTABLE`/`claude_executable`, if set) -- and the unit file's `Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin` (added above) never included where Step 4's `mise use -g npm:@anthropic-ai/claude-code` actually installed it (`~/.local/share/mise/installs/npm-anthropic-ai-claude-code/latest/node_modules/.bin/claude`), so it silently fell through to `"sdk-bundled"`, which isn't present. Fix: add a second `Environment=` line to `~second-brain/.config/systemd/user/thicket-agentd.service`, right after the `PATH` one:

```
Environment=THICKET_CLAUDE_EXECUTABLE=%h/.local/share/mise/installs/npm-anthropic-ai-claude-code/latest/node_modules/.bin/claude
```

then `systemctl --user daemon-reload && systemctl --user restart thicket-agentd` (same `sudo -u second-brain -H ... XDG_RUNTIME_DIR=...` invocation as Step 6 below). Confirm via the startup log line: `"agentd listening", ..., "claude":"<that path>"`.

- [ ] **Step 6: Verify both services are healthy**

Run: `ssh thicket-pilot@orb -- 'sudo -u second-brain XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) systemctl --user status thicket-netd thicket-agentd'`
Expected: both `active (running)`

> **Corrected 2026-09-11:** plain `sudo -u second-brain $HOME/...` resolves `$HOME` to `technicalpickles`'s home (no `-H`), same gotcha as Step 4. Use `-H` plus the `SUDO_USER` unset:

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain -H env XDG_RUNTIME_DIR=/run/user/$(id -u second-brain) bash -c "unset SUDO_USER SUDO_UID SUDO_GID SUDO_COMMAND; \$HOME/.local/bin/thicket doctor"'
```
Expected: no errors for the `second-brain` agent (`[tailnet]`/`[version]` FAILs are pre-existing/cosmetic — no system `tailscale` CLI, `~/.local/bin` not on `$PATH` — not blocking; `[slack]` FAIL is expected, this pilot deploys no Slack bridge)

- [ ] **Step 7: Fetch and save the agent card — Task 5 depends on this file**

> **Corrected 2026-09-11:** the `VAR=value command "...$VAR..."` form doesn't make `$VAR` visible for expansion in that same command's own arguments in bash — only in the executed command's environment. Wrap in `bash -c` so the variable is set and expanded together:

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain bash -c "curl -s --unix-socket /run/user/\$(id -u second-brain)/thicket/agentd.sock http://x/.well-known/agent-card.json"' > second-brain-agent-card.json
```

Read `second-brain-agent-card.json` and note: the base URL/path A2A messages get POSTed to, and the JSON-RPC method name(s) it advertises (the A2A spec's core method is `message/send`, but confirm against what this card actually declares — don't assume). This file is the actual contract Task 5's client code is written against; nothing in this plan guesses at it.

- [ ] **Step 8: No commit — this task only installs and starts services on the VM. Keep `second-brain-agent-card.json` somewhere you'll have it for Task 5.**

---

### Task 4: Wire and verify vault access for the `second-brain` agent

**Files:** none in any repo — this is host-level VM configuration.

**Interfaces:**
- Consumes: the `second-brain` account from Task 2/3, and this Mac's `~/Vaults/pickled-knowledge` (the user's directly-edited copy of the vault — not picklelab's `obsidian-sync` copy).
- Produces: `~second-brain/vault` on `thicket-pilot`, symlinked to the vault — the path the roster's `workspaces.vault` entry (Task 2) already points at.

> **Corrected 2026-09-11 — this task is far simpler than originally planned.** The original plan assumed `thicket-pilot` (an OrbStack VM) needed a network mount (SSHFS) to reach the vault, since it's a separate machine from wherever the vault lives — and initially targeted picklelab's `obsidian-sync` copy, matching the existing production `second-brain-agent` container's pattern. Two corrections, from directly checking reality instead of assuming: (1) the vault this pilot should target is the user's own directly-edited copy at `~/Vaults/pickled-knowledge` **on this Mac**, not picklelab's sync copy. (2) `thicket-pilot`, being an OrbStack VM, already has this Mac's entire filesystem mounted read-write via virtiofs at the same path (`/Users/technicalpickles/...`) — confirmed live (`mount | grep mac` inside the VM shows `mac on /Users type virtiofs (rw,relatime)`), and the `second-brain` account can already read and write through it with no extra configuration (verified with an actual write-then-readback test). So: no SSHFS, no new SSH keypair, no picklelab, no `/etc/fstab` entry, no touching production anything — just a symlink.

- [ ] **Step 1: Symlink the agent's vault workspace to the virtiofs-mounted vault**

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain ln -s /Users/technicalpickles/Vaults/pickled-knowledge ~second-brain/vault'
```

- [ ] **Step 2: Verify read access**

Run: `ssh thicket-pilot@orb -- 'sudo -u second-brain ls ~second-brain/vault | head -5'`
Expected: real vault file/directory names (not empty, not an error)

- [ ] **Step 3: Verify write access, readable back on the Mac directly**

```bash
ssh thicket-pilot@orb -- 'sudo -u second-brain sh -c "echo pilot-test > ~second-brain/vault/thicket-pilot-test.md"'
cat ~/Vaults/pickled-knowledge/thicket-pilot-test.md
```
Expected: `pilot-test` (no sync delay — it's the same underlying files via virtiofs, not a copy)

Delete the test file once confirmed: `ssh thicket-pilot@orb -- 'sudo -u second-brain rm ~second-brain/vault/thicket-pilot-test.md'`

- [ ] **Step 4: No further action needed for reboot survival.** OrbStack's virtiofs mounts are set up by the VM's own init on every boot (they're how `/Users`, `/Applications`, etc. get mounted at all) — there's no `/etc/fstab` entry for this pilot to add. The symlink itself persists on the VM's own disk.

- [ ] **Step 5: No commit — host configuration only.**

---

### Task 5: Build the `second-brain-bridge` MCP server

**Files:**
- Create: `nodes/second-brain-bridge/package.json` (in the `pickleclaw` repo)
- Create: `nodes/second-brain-bridge/src/a2a-client.ts`
- Create: `nodes/second-brain-bridge/src/a2a-client.test.ts`
- Create: `nodes/second-brain-bridge/src/server.ts`
- Create: `nodes/second-brain-bridge/vitest.config.ts`
- Create: `nodes/second-brain-bridge/tsconfig.json`

> **Corrected 2026-09-11 against the real agent card from Task 3.** The card's `supportedInterfaces[0].url` is `https://thicket-second-brain/a2a/v1` (`protocolBinding: "JSONRPC"`, `protocolVersion: "1.0"`) — an unqualified hostname (thicket's renderer only appends a tailnet domain suffix when `THICKET_TAILNET_DOMAIN` is set, which it wasn't), plus a `/a2a/v1` path. The code blocks below have already been updated to use `https://thicket-second-brain.tail2023b7.ts.net/a2a/v1` (the actual reachable form, with the tailnet's MagicDNS suffix added and the card's path appended) as the mock/real `baseUrl` — that's the real value Task 6 must set `SECOND_BRAIN_A2A_URL` to. The card does **not** enumerate JSON-RPC method names or a response shape anywhere (`skills: []`, no `methods` field) — `message/send` (used below) is a reasonable inference from `capabilities.streaming: true`/A2A's spec, not something the card confirms, and the exact `result.parts[].text` response shape is likewise unverified against thicket's real wire format. Task 6's live test against the actual running agent is where that assumption gets checked for real — if it's wrong, that's a normal Task 6 finding, not a sign Task 5 was done wrong.

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
      baseUrl: "https://thicket-second-brain.tail2023b7.ts.net/a2a/v1",
    });

    expect(reply).toBe("Found 3 notes about that.");
    expect(fetch).toHaveBeenCalledWith(
      "https://thicket-second-brain.tail2023b7.ts.net/a2a/v1",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "content-type": "application/json" }),
      }),
    );
  });

  it("throws with a clear message when the agent is unreachable", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("ECONNREFUSED"));

    await expect(
      sendToSecondBrain("hello", { baseUrl: "https://thicket-second-brain.tail2023b7.ts.net/a2a/v1" }),
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
SECOND_BRAIN_A2A_URL=https://thicket-second-brain.tail2023b7.ts.net/a2a/v1 node dist/server.js &
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

- [x] **Step 0: Confirm the dev VM can actually reach `thicket-pilot` over the tailnet, before writing any code**

> **Corrected 2026-09-12, by actually running it.** `docker compose` here does NOT run on the `openclaw` OrbStack VM (per this file's own header note) — it runs against OrbStack's *shared* Docker engine, which backs every OrbStack container on this Mac. A `docker run --rm --network dev-vm_default curlimages/curl curl ... https://thicket-second-brain.tail2023b7.ts.net` timed out (DNS resolved to the tailnet IP; TCP never connected), confirming the container isn't a tailnet node. The plan's original two options (join the dev VM itself, or the shared engine) were both rejected here: joining the *shared* engine would put every OrbStack container on this Mac onto the tailnet, not just this pilot — too broad a blast radius for something that's supposed to stay isolated. **Decision: a dedicated Tailscale sidecar in `dev-vm/compose.yaml`** (`tailscale/tailscale` image, own `tag:thicket-bridge`, kernel/TUN mode via `TS_USERSPACE=false` + `/dev/net/tun` + `NET_ADMIN` — the same "container-as-node" pattern as `homelab/services/second-brain-agent`'s `ts-agent` sidecar in this repo), with `second-brain-bridge` sharing its netns via `network_mode: service:second-brain-bridge-ts`. Required, done manually (admin-console/1Password access, not something this session could reach): a `tag:thicket-bridge` `tagOwners` entry + a grant `tag:thicket-bridge -> tag:thicket-second-brain:443` in the tailnet ACL, and a reusable non-ephemeral auth key minted for that tag, written to `~/OrbStack/openclaw/home/technicalpickles/.openclaw/secrets/thicket-bridge-ts-authkey.env` as `TS_AUTHKEY=...` (same env_file convention this compose file already uses for every other secret). Verified after both were in place: `tailscale ping`/`tailscale nc ... 443` from inside the sidecar succeeded, and a real `curl` reached `thicket-second-brain`'s agent-card endpoint.

- [x] **Step 1: Write the Dockerfile**

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

- [x] **Step 2: Register the MCP server**

> **Corrected 2026-09-12, by actually running it.** Editing `openclaw-config/mcp.json5` in the repo has **no effect** on the running dev-VM gateway. `compose.yaml`'s `openclaw` service mounts a named `config` volume (`external: true`, populated once), not this repo file — same "cattle" convention the compose file already documents for provider secrets ("Rotation is therefore 'copy the updated file in again'"). The live file is `/home/node/.openclaw/includes/mcp.json5` *inside* `dev-vm-openclaw-1`; `openclaw mcp list` reads the merged `openclaw.json`, not the repo. To actually register a new server: `docker cp openclaw-config/mcp.json5 dev-vm-openclaw-1:/home/node/.openclaw/includes/mcp.json5 && docker compose restart openclaw`, then confirm with `docker exec dev-vm-openclaw-1 openclaw mcp list`.

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

- [x] **Step 3: Add the compose service**

> **Corrected 2026-09-12** per Step 0's ruling: `second-brain-bridge` has no `environment:`/own network of its own — it shares `second-brain-bridge-ts`'s netns via `network_mode: service:second-brain-bridge-ts`, and that sidecar service carries the `networks.default.aliases: [second-brain-bridge]` entry instead (a service with `network_mode: service:X` has no network attachment of its own to hang a compose alias on). See the actual committed blocks in `dev-vm/compose.yaml` (commit `87bb693`) rather than re-deriving them here.

- [x] **Step 4: Build and start it**

```bash
cd dev-vm
docker compose up -d --build second-brain-bridge-ts second-brain-bridge
```

Run: `docker compose logs second-brain-bridge-ts second-brain-bridge`
Expected: no crash-loop; sidecar logs `joined tailnet as pickleclaw-dev-second-brain-bridge` (or similar), bridge logs `second-brain-bridge listening on :8787/mcp`

- [x] **Step 5: Verify the gateway sees the tool**

> **Corrected 2026-09-12, by actually running it.** Two things this step's original curl missed: (1) `second-brain-bridge` publishes no host port (same as `gog-mcp`) and now also has no network of its own (`network_mode: service:...`), so it's only reachable from other dev-VM containers by the sidecar's alias, never from the Mac directly. (2) the MCP streamable-HTTP transport requires an `initialize` handshake before `tools/list`/`tools/call` — hitting either without one first returns `"Bad Request: Server not initialized"`.

```bash
# 1) initialize — grab the mcp-session-id from the response headers
docker exec dev-vm-openclaw-1 curl -sD - http://second-brain-bridge:8787/mcp -X POST \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke-test","version":"0"}}}'

# 2) tools/list, with that session id
docker exec dev-vm-openclaw-1 curl -s http://second-brain-bridge:8787/mcp -X POST \
  -H 'content-type: application/json' -H 'accept: application/json, text/event-stream' -H "mcp-session-id: <id from step 1>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```
Expected: `tools/list` response includes `ask_second_brain`. Confirmed live, plus a real `tools/call` end to end: asked it "what kind of vault is this?" and got back an accurate, vault-derived answer (Johnny Decimal/PARA Obsidian vault) — the actual pilot proof, not just plumbing.

While debugging the live `tools/call`, two more real findings surfaced and got fixed (not simulated/guessed):

- **`agentd` couldn't find the `claude` binary** (`"Native CLI binary for linux-x64 not found"`, every task failed). Root cause and fix recorded in Task 3 Step 5's 2026-09-12 correction (`THICKET_CLAUDE_EXECUTABLE` env var on the systemd unit).
- **Task 5's `a2a-client.ts` was written against the wrong wire format** — the real agentd needs an `A2A-Version: 1.0` header, method `"SendMessage"` (not `"message/send"`), `messageId`/`role` on the message, untyped `parts`, and the reply nested under `result.task.status.message.parts`. Fixed and re-verified (3/3 tests) in commit `40f36e2`.

- [x] **Step 6: Commit**

Landed as two commits instead of one — the wire-format fix belongs to Task 5's code, discovered here, so it got its own commit rather than being folded into Task 6's:

```
40f36e2 fix(second-brain-bridge): match the real thicket agentd wire format
87bb693 feat(dev-vm): wire second-brain-bridge into the gateway
```

---

### Task 7: End-to-end verification — gateway interface, then Telegram

**Files:** none — this task is pure verification against the pieces built in Tasks 1–6.

**Interfaces:**
- Consumes: everything from Tasks 1–6.
- Produces: the pilot's pass/fail verdict against the spec's four "what the pilot needs to prove" criteria.

- [x] **Step 1: Iterate via the gateway interface**

> **Corrected 2026-09-12, by actually running it.** No Control UI browser session used — the `openclaw` CLI's `agent` command drives a real turn through the gateway directly: `docker exec dev-vm-openclaw-1 openclaw agent --session-key "agent:main:<key>" --message "..." --json`. First attempt (before Step 2's `mcp.json5` propagation fix existed) failed — the gateway's own agent had never heard of a "second brain" and tried to look it up via its native `sessions_send` multi-agent feature instead. After `docker cp`-ing the updated `includes/mcp.json5` in and restarting `openclaw` (see Task 6 Step 2's correction), re-ran it: asked in plain language what kind of vault it manages, and the response JSON's `agentMeta.terminalReceipt.successfulToolNames` showed `["second_brain__ask_second_brain"]` — the model's own tool-selection reasoning picked it, called it over the real A2A path, and returned an accurate, vault-derived answer. This *is* the real gateway-interface proof, not raw MCP protocol calls against the bridge directly (Task 6's verification).

- [x] **Step 2: Fix anything broken, re-run Step 1 until it's clean**

Only the `mcp.json5`-propagation gap above; fixed once, re-ran clean.

- [x] **Step 3: Final full-path check over real Telegram** — **skipped by decision, 2026-09-12**

Telegram is disabled on this dev gateway (`channels.telegram.enabled: false`), with no dev surface currently running. Asked; decided Step 1's gateway-interface proof (real tool-selection reasoning + real A2A round-trip) is sufficient for the pilot's purposes, and not worth standing up a Telegram surface just for this check. Recorded as a deliberate scope decision, not a blocker, in the spec doc's findings.

- [x] **Step 4: Record the pilot's findings**

Written into `docs/plans/2026-09-11-thicket-a2a-pilot.md`'s new "Findings (2026-09-12)" section.

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
