# Deploy Sudoers Setup

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable non-interactive (no TTY, no password prompt) deploys from Mac to picklelab by granting `technicalpickles` passwordless sudo for a narrow set of deploy commands.

**Architecture:** A sudoers drop-in file at `/etc/sudoers.d/deploy-ops` allowlists specific commands (mkdir, ln, systemctl, chown, tailscale, setfacl, useradd, usermod, apt-get, restic). A setup script installs it idempotently. Deploy scripts and Justfile tasks are updated to drop the `-t` (TTY) flag from SSH calls.

**Tech Stack:** bash, sudoers, SSH, systemd

---

### Task 1: Create the sudoers drop-in file

This is a template file checked into the repo. It gets installed to `/etc/sudoers.d/deploy-ops` by the setup script.

**Files:**
- Create: `homelab/config/sudoers-deploy-ops`

**Step 1: Write the sudoers file**

The file grants NOPASSWD on exactly the commands used across all deploy scripts today. Grouped by purpose with comments.

```sudoers
# Passwordless sudo for deploy operations on picklelab.
# Installed to /etc/sudoers.d/deploy-ops by homelab/scripts/setup-deploy-access.sh
#
# Scope: narrow allowlist covering commands used by deploy.sh scripts.
# See docs/plans/2026-04-09-deploy-sudoers.md for rationale.

# Directory setup
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/mkdir -p *

# Symlink systemd units into place
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/ln -sf *

# Systemd lifecycle
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/systemctl enable *
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *

# Ownership changes (brineworks, backup)
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/chown *

# Tailscale service advertising (brineworks)
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/tailscale serve *

# ACLs for backup cross-user reads
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/setfacl *

# Backup user management (backup deploy)
technicalpickles ALL=(ALL) NOPASSWD: /usr/sbin/useradd *
technicalpickles ALL=(ALL) NOPASSWD: /usr/sbin/usermod *

# Package install (backup deploy installs restic, acl)
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/apt-get update
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/apt-get install *

# Run restic as backup user (backup deploy init/check)
technicalpickles ALL=(ALL) NOPASSWD: /usr/bin/sudo -u backup *
```

**Step 2: Commit**

```
feat(homelab): add sudoers drop-in template for deploy operations
```

---

### Task 2: Create the setup script

Follows the existing `homelab/scripts/setup-*.sh` pattern. Idempotent, runs on picklelab.

**Files:**
- Create: `homelab/scripts/setup-deploy-access.sh`

**Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Set up passwordless sudo for deploy operations on picklelab.
# Idempotent: safe to re-run.
# Run on the target host (picklelab), not from Mac.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/homelab}"
SUDOERS_SRC="$REPO_DIR/homelab/config/sudoers-deploy-ops"
SUDOERS_DST="/etc/sudoers.d/deploy-ops"

echo "==> Validating sudoers file syntax"
# visudo -cf does a syntax check without installing. Catches errors before
# they lock you out of sudo.
if ! sudo visudo -cf "$SUDOERS_SRC"; then
    echo "ERROR: sudoers file has syntax errors. Not installing."
    exit 1
fi

echo "==> Installing sudoers drop-in to $SUDOERS_DST"
sudo cp "$SUDOERS_SRC" "$SUDOERS_DST"
sudo chmod 0440 "$SUDOERS_DST"

echo "==> Verifying passwordless sudo works for a deploy command"
if sudo -n systemctl daemon-reload 2>/dev/null; then
    echo "    OK: passwordless sudo confirmed"
else
    echo "    WARNING: passwordless sudo not working. Check $SUDOERS_DST"
    exit 1
fi

echo ""
echo "Done! Deploy commands no longer require a password or TTY."
```

**Step 2: Make executable and commit**

```bash
chmod +x homelab/scripts/setup-deploy-access.sh
```

```
feat(homelab): add setup script for deploy sudoers
```

---

### Task 3: Update Justfile deploy tasks to drop `-t` flag

With passwordless sudo, `ssh -t` (force TTY) is no longer needed for deploy commands. Remove it so deploys work non-interactively.

**Files:**
- Modify: `Justfile`

**Step 1: Remove `-t` from deploy SSH calls**

These lines change from `ssh -t {{host}}` to `ssh {{host}}`:

| Line | Current | New |
|------|---------|-----|
| 138 | `ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/climate-auto-switch/deploy.sh"` | `ssh {{host}} "cd /opt/homelab && git pull && homelab/services/climate-auto-switch/deploy.sh"` |
| 142 | `ssh -t {{host}} "sudo mkdir -p ..."` | `ssh {{host}} "sudo mkdir -p ..."` |
| 144 | `ssh -t {{host}} "sudo mv ..."` | `ssh {{host}} "sudo mv ..."` |
| 216 | `ssh -t {{host}} "cd /opt/homelab && homelab/services/brineworks-server/deploy.sh"` | `ssh {{host}} "cd /opt/homelab && homelab/services/brineworks-server/deploy.sh"` |
| 285 | `ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/backup/deploy.sh"` | `ssh {{host}} "cd /opt/homelab && git pull && homelab/services/backup/deploy.sh"` |
| 289 | `ssh -t {{host}} "sudo systemctl start backup.service"` | `ssh {{host}} "sudo systemctl start backup.service"` |
| 323 | `ssh -t {{host}} "cd /opt/homelab && git pull && homelab/services/obsidian-sync/deploy.sh"` | `ssh {{host}} "cd /opt/homelab && git pull && homelab/services/obsidian-sync/deploy.sh"` |

Note: keep `-t` on interactive commands that genuinely need a TTY (e.g. `obsidian-sync-exec` which runs an interactive container, `vikunja-logs-follow` which streams logs). Only remove it from deploy/sudo calls.

**Step 2: Commit**

```
chore(homelab): drop ssh -t from deploy tasks (passwordless sudo)
```

---

### Task 4: Document in host setup

Add a section to `homelab/plans/homelab_03_host_setup.md` so this is reproducible from bare metal.

**Files:**
- Modify: `homelab/plans/homelab_03_host_setup.md`

**Step 1: Add deploy access section after the "Infra repo" section**

```markdown
### Deploy access (passwordless sudo)

Scripted: `homelab/scripts/setup-deploy-access.sh`

Installs a sudoers drop-in (`/etc/sudoers.d/deploy-ops`) granting `technicalpickles` passwordless sudo for the specific commands used by deploy scripts: `mkdir`, `ln`, `systemctl`, `chown`, `tailscale serve`, `setfacl`, `useradd`, `usermod`, `apt-get`, and running commands as the `backup` user.

This enables non-interactive deploys from Mac (`ssh picklelab "..."` without `-t` flag).

The allowlist template lives in `homelab/config/sudoers-deploy-ops`. The setup script validates syntax with `visudo -cf` before installing, so a bad edit won't lock you out.

Run after initial host setup:

```bash
cd /opt/homelab
homelab/scripts/setup-deploy-access.sh
```
```

**Step 2: Commit**

```
docs(homelab): document deploy access setup for host provisioning
```

---

### Task 5: Verify end-to-end

This task requires access to picklelab. Run manually.

**Step 1: Push and pull**

From Mac:
```bash
git push
ssh picklelab "cd /opt/homelab && git pull"
```

**Step 2: Run setup script**

```bash
ssh picklelab "cd /opt/homelab && homelab/scripts/setup-deploy-access.sh"
```

**Step 3: Test non-interactive deploy**

Pick a service and deploy without `-t`:

```bash
ssh picklelab "sudo systemctl daemon-reload"
```

If that returns without a password prompt, the sudoers drop-in is working.

**Step 4: Full deploy test**

```bash
just deploy-climate
```

Confirm it completes without TTY errors.
