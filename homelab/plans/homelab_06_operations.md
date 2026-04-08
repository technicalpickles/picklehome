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

