# Homelab

Single Intel NUC (Celeron J3455, 4 GB RAM, local SSD) running lightweight always-on services, remote dev environments, and home automation experimentation. Synology NAS on the LAN for backups.

**Philosophy:** simple, reproducible, recoverable. No cluster tooling. Easy to rebuild from source control and backups.

**Stack:** Ubuntu Server LTS, Docker Compose (per-service), systemd, Tailscale, git-managed infra repo.

## Plans

| Doc | Purpose |
|-----|---------|
| [00 — Overview](plans/homelab_00_overview.md) | Mental entry point: goals, hardware, philosophy, constraints |
| [01 — Plan](plans/homelab_01_plan.md) | Practical setup checklist: OS, disk layout, stack, directory conventions |
| [02 — Architecture](plans/homelab_02_architecture.md) | Decision rationale: why Compose, why Ubuntu, why Tailscale, tradeoffs |
| 03 — Host Setup | _TODO: concrete commands to reproduce the host from bare metal_ |
| 04 — Services | _TODO: service registry — purpose, compose path, data path, access URL per service_ |
| [05 — Backup and Recovery](plans/homelab_05_backup_and_recovery.md) | Backup targets, tools, restore procedure |
| [06 — Operations](plans/homelab_06_operations.md) | Runbook: deploy, restart, disk cleanup, reboot, troubleshooting |
| [07 — Agent Access Model](plans/homelab_07_agent_access_model.md) | How coding/admin agents interact with the host safely |

## Services

### climate-auto-switch

Runs `climate comfort-switch auto` every 6 hours via systemd timer. Checks outdoor temperature and switches between heat/cool comfort modes. Runs as a Docker container with dependencies baked into the image.

**First-time setup (from Mac):**

```bash
# 1. Generate .env on picklelab (needs 1Password signed in on host)
ssh picklelab "cd /opt/homelab && op signin && scripts/dotenv"

# 2. Seed the ecobee token file (one-time)
just seed-climate-tokens

# 3. Deploy (builds image, installs systemd units, enables timer)
just deploy-climate
```

**Deploy updates (from Mac):**

```bash
just deploy-climate
```

**Manual trigger:**

```bash
ssh picklelab "sudo systemctl start climate-auto-switch.service"
```

**Check logs:**

```bash
ssh picklelab "sudo journalctl -u climate-auto-switch.service -n 50"
```
