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

