# Homelab

Single Intel NUC (Celeron J3455, 4 GB RAM, local SSD) running lightweight always-on services, remote dev environments, and home automation experimentation. Synology NAS on the LAN for backups.

**Philosophy:** simple, reproducible, recoverable. No cluster tooling. Easy to rebuild from source control and backups.

**Stack:** Ubuntu Server LTS, Docker Compose (per-service), systemd, Tailscale, git-managed infra repo.

## Secrets

Secrets live in 1Password and are pulled into a local `.env` via `just dotenv`. Each service gets only the vars it needs -- defined in `<service>/.env.vars` -- via `scripts/service-env`, which filters the master `.env` at deploy time and scps the subset to the host.

When adding a new service:
1. Add required secrets to 1Password and `.env.template`
2. Create `homelab/services/<service>/.env.vars` listing the needed var names
3. Have the deploy task call `scripts/service-env` before scp'ing

## Plans

| Doc | Purpose |
|-----|---------|
| [00 — Overview](plans/homelab_00_overview.md) | Mental entry point: goals, hardware, philosophy, constraints |
| [01 — Plan](plans/homelab_01_plan.md) | Practical setup checklist: OS, disk layout, stack, directory conventions |
| [02 — Architecture](plans/homelab_02_architecture.md) | Decision rationale: why Compose, why Ubuntu, why Tailscale, tradeoffs |
| 03 — Host Setup | _TODO: concrete commands to reproduce the host from bare metal_ |
| 04 — Services | _Service registry has graduated to [services/README.md](services/README.md). Plan retained as historical context._ |
| [05 — Backup and Recovery](plans/homelab_05_backup_and_recovery.md) | Backup targets, tools, restore procedure |
| [06 — Operations](plans/homelab_06_operations.md) | Runbook: deploy, restart, disk cleanup, reboot, troubleshooting |
| [07 — Agent Access Model](plans/homelab_07_agent_access_model.md) | How coding/admin agents interact with the host safely |

## Services

### vikunja

Self-hosted task manager (Postgres + Vikunja). Accessible at `https://vikunja.<tailnet>.ts.net` over Tailscale Services. See [services/vikunja/README.md](services/vikunja/README.md) for full setup and API details. Data (database + file attachments) is backed up nightly by the [backup service](services/backup/README.md).

**First-time setup (from Mac):**

```bash
just dotenv        # pull new secrets from 1Password (see service README for prereqs)
just deploy-vikunja  # copies .env, configures tailscale serve, installs + starts systemd unit
```

**Deploy updates:**

```bash
just deploy-vikunja
```

**Logs:**

```bash
just vikunja-logs
just vikunja-logs-follow
```

---


### climate-auto-switch

Runs `climate comfort-switch auto` every 15 minutes via systemd timer. Checks outdoor temperature and switches between heat/cool comfort modes. No-op detection skips API writes when the mode hasn't changed. Runs as a Docker container with dependencies baked into the image. State (OAuth tokens, last run, run log) is backed up nightly by the [backup service](services/backup/README.md).

**First-time setup (from Mac):**

```bash
# 1. Generate .env locally from 1Password
just dotenv

# 2. Seed the ecobee token file (one-time)
just seed-climate-tokens

# 3. Deploy (copies .env, builds image, installs systemd units, enables timer)
just deploy-climate
```

**Deploy updates (from Mac):**

```bash
just deploy-climate
```

**Updating secrets:**

```bash
just dotenv
just deploy-climate
```

**Manual trigger:**

```bash
ssh picklelab "sudo systemctl start climate-auto-switch.service"
```

**Monitoring:**

```bash
just climate-check             # last run state (mode, temps, thermostats)
just climate-log               # recent run log (JSONL, last 10 entries)
just climate-log lines=50      # more history
```

**Systemd logs:**

```bash
ssh picklelab "sudo journalctl -u climate-auto-switch.service -n 50"
```

---

### backup

Nightly restic backups of `/srv/data` at 3am, with Postgres dumps for vikunja. GFS retention (7 daily, 4 weekly, 6 monthly). Runs as a dedicated `backup` system user. See [services/backup/README.md](services/backup/README.md) for what's captured, restore procedure, and future work (Synology, S3).

**First-time setup (from Mac):**

```bash
# 1. Create "Restic Backup" item in 1Password (picklehome vault) with fields:
#    repository (e.g. /srv/backups/restic), password (openssl rand -base64 32)

just dotenv          # pull restic secrets
just deploy-backup   # install restic, create user, set up ACLs, init repo, enable timer
```

**Operations:**

```bash
just backup-now          # manual trigger
just backup-snapshots    # list snapshots
just backup-status       # timer status + next run
just backup-logs         # last 50 lines of service journal
```
