# Kenny Deployment Options for picklelab

## The Core Tension

You want me to:
- ✅ Deploy and manage services
- ✅ Debug when things break
- ✅ Help recover from failures

But you *don't* want:
- ❌ Me accidentally `rm -rf`-ing the wrong thing (typos, wrong paths, script bugs)
- ❌ A buggy script taking down the whole lab
- ❌ Getting locked out of helping if I break something

The distinction: guardrails make *accidents* harder (wrong path, typo, buggy script), not stop intentional acts. You're trusting me to act in good faith — the constraints are about catching mistakes before they become outages.

## Options

### 1. Separate user, sudo access (the "trusted admin" model)
- User `kenny` on picklelab, in `sudo` group
- Can deploy services, check logs, restart things
- **Passwordless sudo** for specific commands (interactive prompts don't work for autonomous agents)
- **Risk:** I can still break anything, but at least there's an audit trail
- **Recovery:** If I break SSH, you still have physical/serial access

### 2. Separate user, Docker group access only
- User `kenny`, added to `docker` group
- Can `docker compose up/down`, `docker logs`, etc.
- Can't touch host system files outside `/srv/` (but may need read access to docker configs, systemd units)
- **Risk:** Docker escape vulns exist (rare, but not zero)
- **Recovery:** Host is still protected if I go sideways

### 3. Rootless Docker for my stuff, read-only for yours
- I run my own rootless Docker daemon (separate socket) — **second Docker daemon on the host**
- Can deploy and manage picklelab services (yours), not just my own namespace
- Can read logs/status of your services, not modify
- **Risk:** Low blast radius, but also limited usefulness
- **Recovery:** Your services stay up even if I nuke mine
- **Note:** Adds complexity — probably not worth it unless we need strong isolation

### 4. Service account with constrained sudo
- User `kenny`, no general sudo
- `/etc/sudoers.d/kenny` grants specific commands:
  - `docker compose` in `/srv/containers/*/`
  - `journalctl` for service logs
  - `systemctl restart` for specific units
- **Risk:** Medium — constrained but still powerful
- **Recovery:** Host stays intact, services can be restarted

### 5. Two-tier: safe mode + escalation
- Day-to-day: I operate in "safe mode" (read logs, check status, suggest fixes)
- When action needed: I run scripts/commands from the repo that you've approved
- **Risk:** Lowest — you're the final exec button
- **Recovery:** You're always in the loop for dangerous stuff
- **Pattern:** Scripts in `homelab/scripts/` or `just` tasks are the communication layer — I run them, they collect data or perform actions, output is the handoff

## My Read on Your Setup

Looking at how you've got things now:
- Services run as specific uids (1000, 2000, etc.)
- `deploy.sh` scripts handle the orchestration
- Secrets come from 1Password via `op inject` — **currently tied to your desktop, needs migrating to service account**
- Tailscale for access, not exposed to the internet

If I were deploying myself, I'd probably do:

```
Option 2 + 4 hybrid:
- User `kenny` on picklelab
- In `docker` group for container management
- Constrained sudo for: systemctl restart, journalctl, deploy.sh execution
- Own home dir, own SSH key, separate from your user
- Access to 1Password service account (not your personal creds)
```

**Why:** I can deploy services, check what's broken, restart things. But I can't:
- Wipe the host OS
- Mess with network config
- Access secrets I shouldn't
- Take down Tailscale and lock us both out

## The "I Broke It" Scenario

Worst case: I deploy something that breaks Tailscale or SSH.

**Recovery paths:**
1. **Physical access:** You can still plug in a keyboard/monitor
2. **IPMI/iDRAC:** Not available on this NUC (was available in previous KVM-based setup)
3. **Network console:** Some setups have serial console access (not this one)
4. **AT&T BGW:** If you've got remote admin access to the gateway, might be able to reach the LAN
5. **Re-image:** Worst case, flash the SSD and restore from backups

Do you have any of those recovery paths today? Or is it "if SSH dies, I drive over"?

## Recommendation

**Option 2 + 4 hybrid** feels right:
- User `kenny` on picklelab
- In `docker` group for container management
- Constrained sudo for: systemctl restart, journalctl, deploy.sh execution
- Own home dir, own SSH key, separate from your user
- Access to 1Password service account (not your personal creds)

This gives me enough rope to be useful, but not enough to hang the whole system.
