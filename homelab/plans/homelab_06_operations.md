# Operations Runbook

This document describes the routine operational procedures for managing the homelab server. It is intended to be practical and task-oriented.

The goal is to make common actions predictable and safe.

---

## Service Deployment

### Deploy or Update a Service

1. Edit the Compose configuration in:

```
/opt/homelab/compose/<service>
```

2. Apply the change:

```
homelab apply service <service>
```

3. Validate:

```
homelab check
```

4. Inspect logs if needed:

```
docker compose -p <service> logs -f
```

---

## Restarting Services

Preferred approach:

```
homelab restart service <service>
```

Alternative using systemd:

```
sudo systemctl restart docker-compose@<service>
```

---

## Inspecting System State

### Check Running Containers

```
docker ps
```

### Check Service Status

```
systemctl status docker-compose@<service>
```

### View Logs

```
journalctl -u docker-compose@<service>
```

---

## Disk Usage Monitoring

### Check Overall Usage

```
df -h
```

### Inspect Persistent Data Growth

```
du -sh /srv/data/*
```

### Interactive Inspection

```
ncdu /srv
```

### Root Filesystem Growth (sudo required, interactive only)

`du /srv/data/*` and `ncdu /srv` only cover `/srv`. If `df -h` shows the **root** volume (`/dev/mapper/vg0-root`, mounted `/`) filling while `/srv` stays healthy, the culprit is a root-owned directory an unprivileged `du` can't traverse: it reports a few KB and silently skips. Find it with:

```
sudo du -xh -d2 /var/lib /root 2>/dev/null | sort -rh | head -20
```

**Root offender: `/var/lib/containerd` (docker's containerd image store).** This host's docker uses the **containerd image store** (the containerd snapshotter), so docker's image layers live in the system containerd's overlayfs snapshotter under `/var/lib/containerd` on the **root** volume. The daemon's `data-root: /srv/docker` only relocates docker's containers/volumes/metadata; it does **not** move the containerd snapshotter, so images quietly fill `/`. Confirmed via `sudo ctr -n moby images ls` listing every service image, with `du` showing 14G (12G overlayfs snapshots + 2.8G content) on 2026-06-13.

These are **live, in-use images** (the `moby` namespace, backing running containers), not leftover junk. Do **not** `rm -rf /var/lib/containerd`. Real fixes:

- **Relocate containerd's root to `/srv`** (durable, honors the data-on-`/srv` design). Set `root = "/srv/containerd"` in `/etc/containerd/config.toml`, stop `docker` then `containerd`, move the existing tree onto `/srv`, restart. `setup-docker.sh` already creates `/srv/containers` but never wires containerd to it, this closes that gap.
- **Prune unused images** to reclaim now: `docker image prune -a` *does* free real root space here (images are on root via containerd), at the cost of re-pulls for stopped services.

**Sudo here is interactive.** Passwordless sudo on picklelab is scoped to the deploy-ops allowlist (`config/sudoers-deploy-ops` → `/etc/sudoers.d/deploy-ops`: `mkdir`, `ln`, `systemctl`, `chown`, `tailscale serve`, `setfacl`, `apt-get`, user management). Disk forensics (`du`, `rm`, `lvextend`) are **not** on it and prompt for a password. An agent driving the host over non-interactive ssh cannot answer that prompt: the command fails silently with no output. This includes Claude Code's `!` session prefix, which is also non-interactive. Hand these to a human to run in an interactive shell (or `ssh -t picklelab`).

**Headroom escape hatch.** VG `vg0` has ~49G free, so `sudo lvextend -r -L +20G /dev/vg0/root` grows root online (ext4, no unmount) when cleanup is deferred.

### Migrating containerd to /srv (one-time, existing host)

The durable fix for the leak above. Fresh hosts get this from `setup-docker.sh`; an
already-running host needs to move the existing tree. **This stops docker and all
services briefly** (a minute or two). All `sudo` here is interactive (not on the
deploy-ops allowlist), so run it in a real shell on the host.

```bash
# 1. Pre-flight: confirm the hog and that /srv has room (needs ~14G headroom)
df -h / /srv
sudo du -sh /var/lib/containerd

# 2. Stop docker (and its socket, or systemd re-activates it) then containerd
sudo systemctl stop docker docker.socket
sudo systemctl stop containerd

# 3. Copy the tree to /srv (rsync preserves perms/xattrs/hardlinks). Source still
#    on root, so / does not grow during the copy; /srv grows ~14G.
sudo mkdir -p /srv/containerd
sudo rsync -aHAX /var/lib/containerd/ /srv/containerd/

# 4. Point containerd at the new root. The shipped config has `root` commented
#    out (`#root = "/var/lib/containerd"`); this uncomments and repoints it,
#    preserving the rest of the config. (Step 6's grep confirms it took.)
sudo sed -i 's|^#\?root = .*|root = "/srv/containerd"|' /etc/containerd/config.toml

# 5. Park the old tree (rollback safety), then bring services back
sudo mv /var/lib/containerd /var/lib/containerd.old
sudo systemctl start containerd
sudo systemctl start docker

# 6. Verify: config points at /srv, images intact, containers running
grep '^root' /etc/containerd/config.toml
sudo ctr -n moby images ls | head
docker ps

# 7. Once confident (services healthy), reclaim the ~14G on root
sudo rm -rf /var/lib/containerd.old
df -h / /srv
```

If anything looks wrong at step 6, roll back: stop docker+containerd, restore
`root = "/var/lib/containerd"` in the config (or remove the override), `sudo mv
/var/lib/containerd.old /var/lib/containerd`, restart.

---

## Docker Cleanup

### Remove Unused Images

```
docker image prune -af
```

### Clean Build Cache

```
docker builder prune -af
```

Do **not** blindly remove volumes unless the impact is understood.

---

## Backup Operations

### Trigger Manual Backup

```
homelab backup
```

### Verify Backup Logs

Check systemd timer and logs:

```
systemctl status backup-restic.timer
journalctl -u backup-restic.service
```

---

## System Updates

### Apply Package Updates

```
sudo apt update && sudo apt upgrade
```

Reboot if kernel updates were installed.

---

## Safe Reboot Procedure

1. Confirm backups completed recently
2. Check disk usage
3. Verify critical services healthy

Then:

```
sudo reboot
```

After reboot:

- verify Tailscale connectivity
- confirm services started
- run validation checks

---

## Devcontainer Maintenance

Dev workloads are ephemeral.

Periodic cleanup:

```
docker system prune -af
```

Run only when confident no important containers are active.

---

## Troubleshooting Workflow

1. Identify failing service
2. Inspect container logs
3. Check systemd unit status
4. Verify disk space and memory pressure
5. Roll back recent configuration changes if necessary

If recovery is unclear, follow documented restore procedure.

---

## Tailscale Services Troubleshooting

### "Advertising the service, but some required ports are missing"

The port in the Tailscale admin console service definition doesn't match the port in the `tailscale serve` command.

**Symptoms:** Service works on localhost, DNS resolves to a service IP, but connections time out from other tailnet nodes.

**Why localhost still works:** picklelab routes to its own service IP locally, so `curl https://svc.<tailnet>.ts.net` succeeds on the host even when other nodes can't reach it. This makes it look like Tailscale is fine when it isn't.

**Diagnosis:**

```bash
# Check serve config (plain `serve status` doesn't show --service mode)
tailscale serve status --json

# Ping the service IP from another node (should respond if healthy)
ping <service-ip>
```

**Fix:** Update the service definition ports in the [admin console](https://login.tailscale.com/admin/services) to match the `--https` port in the serve command (usually 443), then re-advertise:

```bash
sudo tailscale serve --service=svc:<name> --https=443 off
sleep 2
sudo tailscale serve --service=svc:<name> --https=443 http://127.0.0.1:<port>
```

See [tailscale/tailscale#18442](https://github.com/tailscale/tailscale/issues/18442) for background.

### First deploy: service not responding

New services need approval in the admin console before other tailnet nodes can reach them. The deploy scripts print instructions when the Tailscale health check fails, but the short version:

1. Open [Tailscale Services](https://login.tailscale.com/admin/services)
2. Approve the pending service
3. Re-advertise (tailscaled doesn't auto-detect approval)
4. Verify with `curl`

---

## Routine Maintenance Checklist

Weekly or monthly:

- review disk growth
- verify backup success
- prune unused images
- apply system updates
- confirm infra repo is up to date

Operational discipline prevents most incidents.

---

## Summary

The homelab should feel predictable to operate.

Common actions should flow through:

- infrastructure repo changes
- wrapper commands
- validation checks
- observable logs

If an action feels ad hoc or risky, consider improving the operational interface before repeating it.

