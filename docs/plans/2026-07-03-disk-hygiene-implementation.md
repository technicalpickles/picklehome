# disk-hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `homelab/services/disk-hygiene/`: a weekly systemd timer that prunes docker build churn on both docker roots, plus a passwordless `disk-report` diagnostic; so `/srv` can't silently fill to 100% again.

**Architecture:** Host-level systemd oneshot + timer (no container), mirroring the `backup` service. A root-owned `disk-report` script installed to `/usr/local/sbin` and made passwordless-sudo-able via a pinned `NOPASSWD` drop-in. The prune script reuses `disk-report` for before/after logging and fails the unit if `/srv` is still over threshold.

**Tech Stack:** bash, systemd (`.service` + `.timer`), sudoers drop-in, `just` recipes, deployed over SSH to picklelab (Ubuntu).

## Global Constraints

- **Directory:** `homelab/services/disk-hygiene/`. systemd unit names are `docker-prune.service` / `docker-prune.timer` (dir = category, unit = specific job).
- **Prune is dangling-only:** `docker builder prune -f` + `docker image prune -f`. **Never** `-a`, **never** `--volumes`. A tagged/deployed image must never be removable.
- **Two docker roots:** main dockerd (root) + rootless `ci` dockerd (uid 2000), reached via `sudo -iu ci docker …`.
- **`disk-report` install path:** `/usr/local/sbin/disk-report`, owned `root:root`, mode `0755`, NOT writable by `technicalpickles` (else the NOPASSWD pin becomes a root-escalation hole).
- **sudoers line, verbatim:** `technicalpickles ALL=(root) NOPASSWD: /usr/local/sbin/disk-report`
- **Disk guard threshold:** 85% on `/srv`.
- **Deploy pattern:** pre-flight (clean tree, on `main`, push if ahead) → `ssh host "cd /opt/homelab && git pull && homelab/services/disk-hygiene/deploy.sh"`. `deploy.sh` runs on the host, which has passwordless deploy-sudo.
- **Verification note:** these are infra scripts, not unit-testable logic. Per-task gate is `shellcheck` (no warnings) + targeted execution. The behavioral gate is Task 7 (deploy + verify on picklelab).

---

### Task 1: `disk-report.sh`: read-only diagnostic bundle

**Files:**
- Create: `homelab/services/disk-hygiene/disk-report.sh`

**Interfaces:**
- Produces: an executable installed at `/usr/local/sbin/disk-report` that prints df, `/srv` du breakdown, LVM free space, and `docker system df` for both roots. Consumed by `docker-prune.sh` (Task 2) and the sudoers pin (Task 4).

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Read-only disk diagnostic bundle for picklelab.
#
# Installed to /usr/local/sbin/disk-report (root-owned) and made
# passwordless-sudo-able for the technicalpickles user via
# /etc/sudoers.d/docker-prune. Bundles the read-only commands that need root
# (du over root-owned /srv dirs, LVM reads) with the ones that don't, so "what
# does the disk look like" is a single `sudo disk-report` instead of a chain of
# sudo prompts. Must stay READ-ONLY: it is pinned in sudoers, so anything it
# runs, it runs as root without a password.
set -uo pipefail

section() { printf '\n=== %s ===\n' "$1"; }

section "Filesystem usage"
df -h /srv /

section "/srv top-level breakdown"
du -xh -d1 /srv 2>/dev/null | sort -rh

section "/srv/data breakdown"
du -xh -d1 /srv/data 2>/dev/null | sort -rh

section "LVM volume group free space"
vgs
lvs
pvs

section "Docker disk usage (main)"
docker system df

section "Docker disk usage (rootless ci, uid 2000)"
sudo -iu ci docker system df 2>&1 || echo "ci rootless docker unreachable"
```

- [ ] **Step 2: Make executable + lint**

Run: `chmod +x homelab/services/disk-hygiene/disk-report.sh && shellcheck homelab/services/disk-hygiene/disk-report.sh`
Expected: no output (clean). If `shellcheck` is missing, install via `mise use -g shellcheck` or `brew install shellcheck`.

- [ ] **Step 3: Commit**

```bash
git add homelab/services/disk-hygiene/disk-report.sh
git commit -m "feat(disk-hygiene): add read-only disk-report diagnostic bundle"
```

---

### Task 2: `docker-prune.sh`: the prune job with the disk guard

**Files:**
- Create: `homelab/services/disk-hygiene/docker-prune.sh`

**Interfaces:**
- Consumes: `/usr/local/sbin/disk-report` (Task 1, installed at deploy time).
- Produces: the `ExecStart` target for `docker-prune.service` (Task 3). Runs as root. Exits non-zero if `/srv` > 85% after pruning.

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Weekly disk hygiene: prune dangling images + build cache on BOTH docker roots
# (main dockerd + rootless ci dockerd at uid 2000).
#
# Dangling-only: never -a, never --volumes. A deployed image keeps its tag, so
# dangling prune only reaps the PREVIOUS build (now <none>) and never a running
# service's image. No keep-list needed: the tag is the keep marker.
#
# Runs as root via docker-prune.service. root reaches the main daemon directly
# and the rootless ci daemon via `sudo -iu ci` (no password: it's root).
set -uo pipefail

THRESHOLD=85   # fail the unit if /srv is still above this % after pruning

echo "### disk-report BEFORE ###"
/usr/local/sbin/disk-report

echo
echo "### Pruning main dockerd ###"
docker builder prune -f
docker image prune -f

echo
echo "### Pruning rootless ci dockerd (uid 2000) ###"
sudo -iu ci docker builder prune -f
sudo -iu ci docker image prune -f

echo
echo "### disk-report AFTER ###"
/usr/local/sbin/disk-report

# Guard: surface a still-full disk instead of letting the prune quietly fall
# behind until we're back at 100%. df --output=pcent is GNU coreutils (Ubuntu).
USE=$(df --output=pcent /srv | tail -1 | tr -dc '0-9')
echo
if [ "$USE" -gt "$THRESHOLD" ]; then
    echo "WARNING: /srv still at ${USE}% (> ${THRESHOLD}%) after prune" >&2
    exit 1
fi
echo "/srv at ${USE}% after prune: healthy"
```

- [ ] **Step 2: Make executable + lint**

Run: `chmod +x homelab/services/disk-hygiene/docker-prune.sh && shellcheck homelab/services/disk-hygiene/docker-prune.sh`
Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add homelab/services/disk-hygiene/docker-prune.sh
git commit -m "feat(disk-hygiene): add docker-prune job with post-prune disk guard"
```

---

### Task 3: systemd units (`.service` + `.timer`)

**Files:**
- Create: `homelab/services/disk-hygiene/docker-prune.service`
- Create: `homelab/services/disk-hygiene/docker-prune.timer`

**Interfaces:**
- Consumes: `docker-prune.sh` (Task 2) via `ExecStart` at the on-host repo path.
- Produces: `docker-prune.timer`, symlinked + enabled by `deploy.sh` (Task 5).

- [ ] **Step 1: Write `docker-prune.service`**

```ini
[Unit]
Description=Prune dangling docker images + build cache on both docker roots
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
User=root
ExecStart=/opt/homelab/homelab/services/disk-hygiene/docker-prune.sh
```

- [ ] **Step 2: Write `docker-prune.timer`**

```ini
[Unit]
Description=Weekly docker prune (Saturday 04:00, after nightly backup)

[Timer]
OnCalendar=Sat *-*-* 04:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Commit**

```bash
git add homelab/services/disk-hygiene/docker-prune.service homelab/services/disk-hygiene/docker-prune.timer
git commit -m "feat(disk-hygiene): add docker-prune systemd service + weekly timer"
```

(Unit correctness is verified on the host in Task 7 via `systemctl status` / `systemd-analyze verify`; local `systemd-analyze` is unavailable on macOS.)

---

### Task 4: sudoers drop-in

**Files:**
- Create: `homelab/services/disk-hygiene/docker-prune.sudoers`

**Interfaces:**
- Produces: the file `deploy.sh` (Task 5) validates with `visudo -cf` and installs to `/etc/sudoers.d/docker-prune`.

- [ ] **Step 1: Write the sudoers file**

```
# Allow technicalpickles to run the read-only disk-report diagnostic as root
# without a password. disk-report is installed root-owned and NOT user-writable,
# so pinning this exact path locks down what runs as root (unlike NOPASSWD on
# du/vgs/lvs, which would be an unpinnable whole-filesystem read primitive).
# Installed to /etc/sudoers.d/docker-prune (mode 0440) by deploy.sh.
technicalpickles ALL=(root) NOPASSWD: /usr/local/sbin/disk-report
```

- [ ] **Step 2: Commit**

```bash
git add homelab/services/disk-hygiene/docker-prune.sudoers
git commit -m "feat(disk-hygiene): add pinned NOPASSWD sudoers drop-in for disk-report"
```

(Syntax is validated on the host in Task 5's deploy via `visudo -cf` before it's ever activated.)

---

### Task 5: `deploy.sh`

**Files:**
- Create: `homelab/services/disk-hygiene/deploy.sh`

**Interfaces:**
- Consumes: all four files above, from the on-host checkout `/opt/homelab/homelab/services/disk-hygiene/`.
- Produces: installed `/usr/local/sbin/disk-report`, validated `/etc/sudoers.d/docker-prune`, symlinked + enabled `docker-prune.timer`. Invoked by `just deploy-disk-hygiene` (Task 6).

- [ ] **Step 1: Write the deploy script**

```bash
#!/usr/bin/env bash
# Deploy disk-hygiene tooling on picklelab.
# Idempotent: safe on first setup or any subsequent deploy. Run from the repo
# root on the target host (invoked by `just deploy-disk-hygiene`).
set -euo pipefail

REPO_DIR=/opt/homelab
SERVICE_DIR="$REPO_DIR/homelab/services/disk-hygiene"

cd "$REPO_DIR"
echo "==> Deploying commit $(git rev-parse --short HEAD)"

echo "==> Installing disk-report to /usr/local/sbin (root-owned, not user-writable)"
sudo install -o root -g root -m 0755 "$SERVICE_DIR/disk-report.sh" /usr/local/sbin/disk-report

echo "==> Validating + installing sudoers drop-in"
# Validate BEFORE activating: a broken /etc/sudoers.d file can lock out sudo.
TMP_SUDOERS=$(mktemp)
cp "$SERVICE_DIR/docker-prune.sudoers" "$TMP_SUDOERS"
if ! sudo visudo -cf "$TMP_SUDOERS"; then
    echo "ERROR: sudoers file failed validation, not installing" >&2
    rm -f "$TMP_SUDOERS"
    exit 1
fi
rm -f "$TMP_SUDOERS"
sudo install -o root -g root -m 0440 "$SERVICE_DIR/docker-prune.sudoers" /etc/sudoers.d/docker-prune

echo "==> Verifying rootless ci docker is reachable (prune must cover both roots)"
if ! sudo -iu ci docker version >/dev/null 2>&1; then
    echo "ERROR: rootless ci docker unreachable ('sudo -iu ci docker version' failed)." >&2
    echo "       The prune job would silently cover only the main daemon." >&2
    echo "       Fix ci lingering / rootless docker before relying on this." >&2
    exit 1
fi

echo "==> Linking systemd units"
sudo ln -sf "$SERVICE_DIR/docker-prune.service" /etc/systemd/system/
sudo ln -sf "$SERVICE_DIR/docker-prune.timer" /etc/systemd/system/

echo "==> Reloading systemd and enabling timer"
sudo systemctl daemon-reload
sudo systemctl enable --now docker-prune.timer

echo "==> Status"
systemctl status docker-prune.timer --no-pager || true
echo ""
echo "Done! Next run:"
systemctl list-timers docker-prune.timer --no-pager
```

- [ ] **Step 2: Make executable + lint**

Run: `chmod +x homelab/services/disk-hygiene/deploy.sh && shellcheck homelab/services/disk-hygiene/deploy.sh`
Expected: no output (clean).

- [ ] **Step 3: Commit**

```bash
git add homelab/services/disk-hygiene/deploy.sh
git commit -m "feat(disk-hygiene): add idempotent deploy.sh (install, validate sudoers, enable timer)"
```

---

### Task 6: `just` recipes + README + service registry entry

**Files:**
- Modify: `Justfile` (add recipes near the other `deploy-*` recipes)
- Create: `homelab/services/disk-hygiene/README.md`
- Modify: `homelab/services/README.md` (add a registry entry)

**Interfaces:**
- Consumes: `deploy.sh` (Task 5) and the on-host units/scripts.
- Produces: `just deploy-disk-hygiene`, `just docker-prune-now`, `just docker-prune-status`, `just docker-prune-logs`, `just disk-report`.

- [ ] **Step 1: Add the `just` recipes to `Justfile`**

```make
# Deploy disk-hygiene (docker-prune timer + disk-report utility) to picklelab
deploy-disk-hygiene host="picklelab":
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "$(git status --porcelain)" ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        exit 1
    fi
    BRANCH=$(git branch --show-current)
    if [ "$BRANCH" != "main" ]; then
        echo "ERROR: not on main (on $BRANCH). Switch to main first."
        exit 1
    fi
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse origin/main)
    if [ "$LOCAL" != "$REMOTE" ]; then
        echo "Pushing to origin/main..."
        git push
    fi
    echo "Deploying commit $(git rev-parse --short HEAD) to {{host}}"
    ssh {{host}} "cd /opt/homelab && git pull && homelab/services/disk-hygiene/deploy.sh"

# Run docker prune now (triggers the systemd service, then shows its log)
docker-prune-now host="picklelab":
    ssh {{host}} "sudo systemctl start docker-prune.service && journalctl -u docker-prune.service -n 60 --no-pager"

# Show docker-prune timer + last-run status
docker-prune-status host="picklelab":
    ssh {{host}} "systemctl status docker-prune.timer --no-pager; echo; systemctl list-timers docker-prune.timer --no-pager"

# Tail docker-prune logs from picklelab
docker-prune-logs host="picklelab" lines="60":
    ssh {{host}} "journalctl -u docker-prune.service -n {{lines}} --no-pager"

# Run the read-only disk-report diagnostic on picklelab (passwordless sudo)
disk-report host="picklelab":
    ssh {{host}} "sudo disk-report"
```

- [ ] **Step 2: Verify `just` parses the new recipes**

Run: `just --list | grep -E 'disk-hygiene|docker-prune|disk-report'`
Expected: all five recipes listed.

- [ ] **Step 3: Write `homelab/services/disk-hygiene/README.md`**

```markdown
# disk-hygiene

Keeps `/srv` from silently filling. Two pieces:

- **`docker-prune`**: a weekly systemd timer (Sat 04:00) that prunes dangling
  images + build cache on **both** docker roots: the main dockerd and the
  rootless `ci` dockerd (uid 2000). Dangling-only (`docker builder prune -f` +
  `docker image prune -f`); never `-a`, never `--volumes`, so no tagged/deployed
  image is ever removed. Fails the unit if `/srv` is still above 85% afterward,
  so a prune that can no longer keep up surfaces instead of rotting.
- **`disk-report`**: a root-owned read-only diagnostic installed to
  `/usr/local/sbin/disk-report`, made passwordless via a pinned sudoers line, so
  investigating disk is a single `sudo disk-report` (df, `/srv` du breakdown,
  LVM free space, `docker system df` for both roots) instead of a chain of sudo
  prompts.

## Why

On 2026-07-03 `/srv` (30G, shared by all services) hit 100% and wedged
second-brain-agent. Root cause: two docker daemons accumulating build churn with
nothing reaping it; `/srv/containerd` alone was 14G. See
[docs/plans/2026-07-03-docker-prune-and-disk-tooling.md](../../../docs/plans/2026-07-03-docker-prune-and-disk-tooling.md).

The structural follow-up (Docker on its own LVM volume) is tracked separately in
taskwarrior.

## Deploy

```bash
just deploy-disk-hygiene
```

Runs `deploy.sh` on the host: installs `disk-report` root-owned, validates the
sudoers drop-in with `visudo -cf` before activating it, verifies the rootless
`ci` docker is reachable, then symlinks + enables the timer.

## Commands

| Command | What |
|---------|------|
| `just deploy-disk-hygiene` | Install/update the tooling on picklelab |
| `just docker-prune-now` | Trigger a prune immediately, show the log |
| `just docker-prune-status` | Timer + last-run status |
| `just docker-prune-logs` | Tail the prune log |
| `just disk-report` | Run the disk diagnostic (passwordless) |

## Safety notes

- **`disk-report` must stay read-only.** It's pinned in sudoers, so anything it
  runs, it runs as root without a password. Installed root-owned and
  non-user-writable so the pin can't become a root-escalation hole.
- **Prune is dangling-only by design.** Reaping old *tagged* versions (`-a`) was
  deliberately rejected: it risks removing a stopped-but-needed image mid-deploy
  for marginal savings.
```

- [ ] **Step 4: Add a registry entry to `homelab/services/README.md`**

Add this row/section in the service registry, following the existing per-service block format (place it alphabetically or next to `backup`, whichever matches the file's ordering):

```markdown
### disk-hygiene

Weekly docker prune (both roots) + a passwordless `disk-report` diagnostic. Keeps `/srv` from silently filling.

| | |
|---|---|
| **Purpose** | Reap docker build churn; one-command disk investigation |
| **Compose** | N/A (host systemd timer + scripts, no container) |
| **Data** | None (operates on `/srv/containerd`, `/srv/ci-docker`) |
| **Access** | No UI. systemd timer at Sat 04:00. |
| **Env vars** | None |
| **Backup** | N/A |
| **Restart** | N/A (runs on timer) |

Prunes dangling images + build cache on the main dockerd and the rootless `ci` dockerd. Ships a root-owned `disk-report` at `/usr/local/sbin`, passwordless-sudo-able via a pinned `/etc/sudoers.d/docker-prune`.

Commands: `just deploy-disk-hygiene`, `just docker-prune-now`, `just docker-prune-status`, `just docker-prune-logs`, `just disk-report`

See [disk-hygiene/README.md](disk-hygiene/README.md).

---
```

- [ ] **Step 5: Commit**

```bash
git add Justfile homelab/services/disk-hygiene/README.md homelab/services/README.md
git commit -m "docs(disk-hygiene): add just recipes, README, and service registry entry"
```

---

### Task 7: Deploy to picklelab + end-to-end verification

**Files:** none (operational).

**Interfaces:**
- Consumes: everything above, now committed and pushed to `origin/main`.
- Produces: the running timer + verified passwordless `disk-report` on picklelab.

- [ ] **Step 1: Deploy**

Run: `just deploy-disk-hygiene`
Expected: pushes if needed, `git pull` on host, deploy.sh prints install/validate/verify steps, ends with `docker-prune.timer` active and a "Next run" line showing the upcoming Saturday.

- [ ] **Step 2: Verify passwordless disk-report (the whole point of Part 2)**

Run: `just disk-report`
Expected: full diagnostic output (df, du, LVM, both docker df sections) with **no password prompt**. If it prompts, the sudoers pin or the install ownership is wrong; stop and fix before continuing.

- [ ] **Step 3: Confirm dangling-only prune can't touch a tagged image**

Run: `ssh picklelab "docker images -f dangling=true --format '{{.Repository}}:{{.Tag}}'"`
Expected: only `<none>:<none>` entries (or empty). This is the set `docker image prune -f` will remove; confirming no tagged/deployed image is in scope.

- [ ] **Step 4: Run a prune and confirm reclaim + guard**

Run: `just docker-prune-now`
Expected: before/after `disk-report` sections in the log, prune output from both the main and `sudo -iu ci` daemons, and a final `/srv at NN% after prune: healthy` line (NN ≤ 85). Unit exits 0.

- [ ] **Step 5: Confirm all services still running (prune harmed nothing)**

Run: `ssh picklelab "docker ps --format '{{.Names}}' | sort"`
Expected: the same service containers running as before (second-brain-agent, brineworks-agent, openclaw, obsidian-sync, etc.).

- [ ] **Step 6: Verify idempotency**

Run: `just deploy-disk-hygiene` a second time
Expected: clean re-run, no errors, timer still active (install/symlink/enable are all idempotent).

- [ ] **Step 7: Close out the taskwarrior item**

Run: `task 247 done` (the `homelab.backup` docker-prune task) after confirming Steps 1-6 pass.

---

## Self-Review

**Spec coverage:**
- Part 1 (docker-prune timer): Tasks 2, 3 (script + units), deployed in 5/7. ✓
- Part 2 (disk-report + passwordless sudo): Tasks 1, 4 (script + sudoers), installed/validated in 5, verified in 7. ✓
- Both docker roots (main + rootless ci): handled in `docker-prune.sh` (Task 2) and the deploy reachability check (Task 5). ✓
- "Still full" guard at 85%: Task 2. ✓
- Fixed root-owned script + exact-path NOPASSWD: Tasks 1, 4, install in 5. ✓
- Weekly Sat 04:00, Persistent: Task 3. ✓
- `just` commands, README, registry entry: Task 6. ✓
- Testing/verification section of spec: Task 7 covers dry-run safety, ci reach, guard, sudoers-passwordless, first real run. ✓
- Followup 248 (dedicated docker volume): out of scope by design, referenced in README (Task 6). ✓

**Placeholder scan:** No TBD/TODO; every script and config is written in full. ✓

**Naming consistency:** dir `disk-hygiene`, units `docker-prune.{service,timer}`, install path `/usr/local/sbin/disk-report`, sudoers `/etc/sudoers.d/docker-prune`, threshold 85; consistent across Tasks 1-7 and the Global Constraints. ✓
