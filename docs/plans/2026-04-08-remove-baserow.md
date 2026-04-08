# Remove Baserow Service

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fully remove the Baserow PRM service from picklelab and the repo, since we've moved to Brineworks.

**Architecture:** Server teardown first (stop service, remove data), then repo cleanup (delete files, update references), then memory/task hygiene. Single commit for repo changes.

**Context:** Baserow was empty, no data to preserve. Brineworks has replaced it.

---

### Task 1: Stop and remove Baserow on picklelab

**Steps:**

```bash
# Stop the service
ssh picklelab "sudo systemctl stop baserow"

# Disable and remove the systemd symlink
ssh picklelab "sudo systemctl disable baserow"
ssh picklelab "sudo rm /etc/systemd/system/baserow.service"
ssh picklelab "sudo systemctl daemon-reload"

# Tear down containers and images
ssh picklelab "cd /opt/homelab/homelab/services/baserow && docker compose -f compose.yaml -f compose.picklelab.yaml down --rmi all --volumes"
```

Verify: `ssh picklelab "systemctl is-active baserow"` should say `inactive` or `failed`. `docker ps -a --filter name=baserow` should be empty.

---

### Task 2: Remove Baserow data from picklelab

```bash
ssh picklelab "sudo rm -rf /srv/data/baserow"
```

Verify: `ssh picklelab "ls /srv/data/baserow"` should fail with "No such file or directory".

---

### Task 3: Delete the Baserow service directory from the repo

**Files:**
- Delete: `homelab/services/baserow/` (entire directory)

```bash
rm -rf homelab/services/baserow/
```

---

### Task 4: Remove Baserow Justfile tasks

**File:** `Justfile` (lines ~189-222)

Remove three tasks:
- `deploy-baserow`
- `baserow-logs`
- `baserow-logs-follow`

---

### Task 5: Remove Baserow entries from .env.template

**File:** `.env.template` (lines 65-69)

Remove:
```
# Baserow PRM (1Password item: Baserow)
# BASEROW_HOST: Tailscale Services hostname -- baserow.<tailnet>.ts.net
BASEROW_HOST={{ op://picklehome/Baserow/host }}
BASEROW_DB_PASSWORD={{ op://picklehome/Baserow/db_password }}
BASEROW_SECRET_KEY={{ op://picklehome/Baserow/secret_key }}
```

---

### Task 6: Remove Baserow section from homelab README

**File:** `homelab/README.md` (lines 59-87)

Remove the entire `### baserow` section.

Also update the backup service description (line ~145) which mentions "Postgres dumps for vikunja and baserow" to just say vikunja.

---

### Task 7: Remove Baserow from backup scripts

**Files:**
- `homelab/services/backup/backup.sh` (line 53): remove `dump_postgres "baserow" "baserow"` call
- `homelab/services/backup/backup.sh` (line 65): remove `--exclude "$DATA_DIR/baserow/db"` line
- `homelab/services/backup/deploy.sh` (line 40): remove `baserow` from the `for svc in vikunja baserow` loop (just `vikunja`)
- `homelab/services/backup/deploy.sh` (lines 46-52): remove the baserow ACL comment block and `setfacl` commands
- `homelab/services/backup/README.md` (line 12): remove baserow row from the backup table

---

### Task 8: Clean up scratch files

```bash
rm scratch/commit-baserow.txt
rm scratch/commit-baserow-url-fix.txt
rm scratch/commit-baserow-docs.txt
```

---

### Task 9: Mark taskwarrior task 11 done

```bash
task 11 done
```

This is the "retry Baserow sync_templates" task, which is moot now.

---

### Task 10: Clean up memory

- Remove `park-baserow-prm.md` from memory
- Update `MEMORY.md` to remove the baserow parked session entry

---

### Task 11: Commit

Stage all repo changes and commit:

```
chore(homelab): remove Baserow service, replaced by Brineworks
```

Note: the backup plan doc (`docs/plans/2026-04-04-homelab-backups.md`) references baserow, but that's a point-in-time design document. Leave it as-is since it reflects what was true when it was written.
