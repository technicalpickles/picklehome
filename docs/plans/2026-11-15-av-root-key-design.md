# Approved root on picklelab with an Automic Vault key

**Goal:** run privileged commands on picklelab without typing a sudo password. Each use is approved in Automic Vault (av) on the Mac or phone. This covers interactive use and agent sessions, which today hard-fail on `sudo: a terminal is required to read the password` for anything outside the `deploy-ops` allowlist.

**Decision:** a second av SSH key, authorized only for `root@picklelab`, reached through a `picklelab-root` ssh alias. Every login runs through a root-owned audit wrapper. Privileged work becomes `ssh picklelab-root '<cmd>'` instead of `sudo <cmd>`.

## What this does and doesn't buy

**Not a new security gate, today.** The `technicalpickles` account, which agents reach with no approval (the av user key is set to authenticate unattended), is already root-equivalent (measured 2026-11-15):

- It's in the `docker` and `lxd` groups. `/var/run/docker.sock` is `root:docker 0660`, so `docker run -v /:/host` is root.
- `sudoers-deploy-ops` grants NOPASSWD on wildcard commands that lead to root: `chown *`, `chmod *`, `ln -sf *`, `apt-get install *` (a local .deb's postinst), `systemctl start|enable *`.
- Some allowlisted scripts under `/opt/homelab` are owned by `technicalpickles` with mode 775, so the user can edit them and then run them under sudo.

**What it does buy:**

- A clean path to root with no pty and no password, for the commands the allowlist doesn't cover. That stops the pressure to keep widening the allowlist.
- An audit trail: av history on the Mac, plus the wrapper's per-command journald log on picklelab.
- The av side of a real gate. The root key turns into a real control once the user account stops being root-equivalent, which is a separate project (see [Follow-up](#follow-up-de-root-the-user-account)).

## Why not the blog-post approach

The starting idea was [passwordless SSH and sudo with 1Password](https://scottstuff.net/posts/2025/07/04/passwordless-ssh-and-sudo-with-1password/): a sudo PAM module checks a key through the forwarded agent. That doesn't work with av's agent (checked 2026-11-15, av 4.24.0):

- av's agent signs only RFC 4252 login payloads: message byte 50, service `ssh-connection`, method `publickey` or the hostbound variant (`authentication()` in automic-vault `src/cli/ssh_agent.rs:252`; ADR 0044 says arbitrary signing fails closed).
- `pam_rssh` signs 32 random bytes (`gen_challenge` in its `src/sign_verify.rs`, called from `src/lib.rs`).
- `pam_ssh_agent_auth` (`libpam-ssh-agent-auth` 0.10.3 on Ubuntu 24.04) signs a login-shaped blob with message byte 54 (`SSH2_MSG_USERAUTH_TRUST_REQUEST`, from its `ssh2.h`) and service `pam_ssh_agent_auth` (`userauth_pubkey_from_id.c`).
- The source reads are the proof. A live `ssh-keygen -Y sign` against the av socket returned `agent refused operation`, with no prompt, which backs them up but only exercises SSHSIG.

A root login is the one kind of signature av is built to gate.

## Current state

| Thing | State |
|---|---|
| av SSH agent | Live on the Mac with one Ed25519 key (SHA256:Rz2W…); `ssh picklelab` already uses it, unattended in agent sessions |
| `~/.ssh/config` | av's managed `Host *` block sets `IdentityAgent <av socket>` and `ForwardAgent no` ahead of the includes, so the `ForwardAgent yes` for picklelab in `config.d/hosts` never applies |
| `~/.ssh/config.d/auth` | In agent sessions a `Match exec` block adds `IdentityFile ~/.ssh/agents/home/id_ed25519` for every host |
| ssh multiplexing | Off (`ControlMaster false`) |
| picklelab sshd | OpenSSH 9.6p1 on Ubuntu 24.04, `PasswordAuthentication no`, `PermitRootLogin` and `AuthorizedKeysFile` unset (defaults are `prohibit-password` and `.ssh/authorized_keys .ssh/authorized_keys2`). `50-cloud-init.conf` can't be read without root. Tailscale SSH is off |
| Passwordless sudo | `homelab/config/sudoers-deploy-ops` (see above) |
| Mac tailnet IP | `100.114.32.22`. Logins through the agent ssh relay arrive from this address (`SSH_CONNECTION` measured) |

## Design

### av key (`av-root-key`)

- In av: Settings → SSH Agent → Add SSH Key… → generate Ed25519, named `picklelab-root`. Generation happens inside av's signed helper and the private key never touches disk.
- Policy: **Approval Required** for every Launcher, Terminal included. Never Allow Authentication.
- One approval covers one ssh connection, not one command. `ssh -t picklelab-root` is a root shell for the life of the connection on one approval. Multiplexing stays off so a connection can't quietly outlive the approval.
- **Approval is blind to the command.** The signed payload holds no command (ADR 0044: remote command arguments are "context, not verified destination restrictions"). When an agent asks, the av prompt can't show what it will run, so the agent has to say so in chat first. The wrapper log is the after-the-fact record.

### picklelab side (`root-authorized-keys`)

- Commit the public key as `homelab/config/root-authorized-keys`:

  ```
  restrict,pty,from="100.114.32.22",command="/usr/local/sbin/root-ssh-audit" ssh-ed25519 AAAA... av:picklelab-root
  ```

  - `restrict` turns off agent, port and X11 forwarding, plus user rc.
  - `pty` adds back interactive shells.
  - `from=` limits logins to the Mac's tailnet address. That also admits anything that egresses through the Mac's Tailscale, such as OrbStack VMs, and it only matters if a signature could be obtained somewhere else.
  - `command=` forces every login through the wrapper.
- Add `homelab/config/root-ssh-audit` → `/usr/local/sbin/root-ssh-audit` (root:root 0755). It logs `$SSH_ORIGINAL_COMMAND` (or `interactive shell`) and the key fingerprint to journald via `logger -t root-ssh`, then runs the command with `exec /bin/bash -c "$SSH_ORIGINAL_COMMAND"`, or `exec /bin/bash -l` when there is none.
- Add `homelab/config/sshd-root-login.conf` → `/etc/ssh/sshd_config.d/20-root-login.conf`:

  ```
  PermitRootLogin prohibit-password
  AuthorizedKeysFile .ssh/authorized_keys
  ```

  This states the default explicitly and closes the `authorized_keys2` side path. `20-` sorts before `50-cloud-init.conf`, and sshd keeps the first value it reads.
- Add `homelab/scripts/setup-root-key.sh`, modeled on `setup-deploy-access.sh`. Run it as `technicalpickles` (it calls `sudo` itself and takes the deploy lock). It:
  - **pins the expected fingerprint** in the script, refuses to install a key file that doesn't match it, and prints a diff before replacing anything;
  - installs the key file to `/root/.ssh/authorized_keys` (dir 0700, file 0600, root:root), removes any `/root/.ssh/authorized_keys2`, and installs the wrapper and the sshd drop-in;
  - runs `sshd -t` and then `systemctl reload ssh`, but only if `-t` passes;
  - verifies with `ssh-keygen -lf /root/.ssh/authorized_keys` against the pinned fingerprint, and with `sshd -T | grep -Ei 'permitrootlogin|authorizedkeysfile'`.

  `/opt/homelab` can be written by the user and by anything that pushes to origin. The pinned fingerprint is what stops a planted key from being installed on a re-run. Never add this script to the sudoers allowlist.

### Mac side (`ssh-alias`)

Add to `~/.ssh/config.d/hosts`:

```
Host picklelab-root
  HostName picklelab
  User root
  IdentityFile ~/.ssh/av/picklelab-root.pub
  IdentitiesOnly yes
  ForwardAgent no
```

- `IdentityFile` points at the public key exported from av, so ssh asks av's agent for that key. Export it by matching the fingerprint shown in av Settings against `ssh-add -L` run with `SSH_AUTH_SOCK` set to the av socket. av reports every key with the comment `Automic Vault`, so set the file's comment by hand.
- In agent sessions `config.d/auth` also offers the user key, because IdentityFile accumulates across matching blocks. That's harmless: OpenSSH asks the server whether a key is acceptable before it requests a signature, so the user key draws no signature (and no prompt) for root, and the root key draws none for `technicalpickles`. To keep it tidy, add `!host picklelab-root` to the `Match exec` lines.
- The agent ssh relay allowlists by host, and `picklelab` is already on it. A measured `ssh -G` resolves the relay `ProxyCommand` for `picklelab-root` in agent sessions.

### Agent use (`agent-docs`)

- Update picklehome `CLAUDE.md` (the sudo bullet under "Sandbox") and `homelab/docs/homelab_07_agent_access_model.md`:
  - An agent that needs root outside the allowlist says the exact command in chat, then runs `ssh picklelab-root '<cmd>'`, and Josh approves it in av.
  - Where the allowlist covers the command, use the allowlist instead, since it needs no human.
- In `homelab_07`, record this as an exception to "unrestricted root shell access", with a human gate on each connection and an audit trail. Note the user-account caveat from [What this does and doesn't buy](#what-this-does-and-doesnt-buy).

## Rollout (each step ends in a check)

1. **`av-root-key`**: Josh generates the key in av and exports the public key to `~/.ssh/av/picklelab-root.pub`. Check: the av socket lists two keys, and `ssh-keygen -lf` on the export matches av Settings.
2. **`root-authorized-keys`**: commit the config files and the script, deploy to `/opt/homelab`, and as `technicalpickles` run `bash /opt/homelab/homelab/scripts/setup-root-key.sh` once (sudo password). Check: the script's own fingerprint and `sshd -T` checks pass.
3. **`ssh-alias`**: add the Host block. Check: `ssh picklelab-root id` shows one av prompt and prints `uid=0(root)`. `ssh picklelab id` still logs in as `technicalpickles` with no new prompt. `journalctl -t root-ssh` shows the `id` line.
4. **Negative checks**:
   - Deny in av → `Permission denied (publickey)`.
   - `ssh -A picklelab-root 'echo $SSH_AUTH_SOCK'` → empty (`restrict`).
   - `from=` can't be tested from another node, because the private key only exists in av, so that test would pass for the wrong reason. Check it by reading the deployed `authorized_keys`.
5. **Agent path**: from a Claude session, `ssh picklelab-root 'systemctl status ssh'` → phone approval → output. Check that `av history` shows Launcher `Claude` and the `picklelab-root` key, and that the journald line is there.
6. **`agent-docs`**: update the two docs above.

Rollback: remove the key in av first. It's instant, needs no root, and invalidates pending signatures. Then, with sudo, delete `/root/.ssh/authorized_keys`, `/usr/local/sbin/root-ssh-audit` and `20-root-login.conf`, and reload sshd.

## Follow-up: de-root the user account

This project is what turns the av approval into a real gate. It's out of scope here, so it's tracked on its own. Scope:

- Take `technicalpickles` out of `docker` and `lxd`. Use a narrow wrapper or rootless docker for the operations deploys need.
- Replace the wildcard sudoers rules with fixed-argument wrappers in root-owned paths.
- Make the allowlisted scripts root-owned and not writable by the user.

Once that's done, the pinned fingerprint in `setup-root-key.sh` stops being belt-and-braces and starts to matter.

## Fallback: an upstream av PAM mode

Take this path if either of these turns out true:

- **You want real `sudo` inside picklelab sessions.** That means tools on the host that call `sudo` themselves, or keeping your current workflow inside a picklelab shell.
- **The root login is unacceptable.** For example, sudo's own policy and logging matter more than the wrapper's log.

The ask to av upstream: let a key flagged for PAM use sign `pam_ssh_agent_auth`'s payload (byte 54, service `pam_ssh_agent_auth`, otherwise the same RFC 4252 shape), with that key at Approval Required. Picklelab would then use stock `libpam-ssh-agent-auth`, `Defaults env_keep += "SSH_AUTH_SOCK"`, and the key in a root-owned file. Costs:

- It widens what av's agent will sign, which ADR 0044 ruled out on purpose, so expect pushback.
- It needs agent forwarding to picklelab, which means overriding av's managed `ForwardAgent no`. A forwarded socket carries requests under the local `ssh` client's Launcher attribution, so the key has to stay at Approval Required.
- Ed25519 support in `pam_ssh_agent_auth` 0.10.3 is untested. **Verify** it before filing.

The root-key setup doesn't block this. If the PAM mode lands, the `picklelab-root` key can stay for agents, or be removed.
