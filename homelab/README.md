# Homelab

Single Intel NUC (Celeron J3455, 16 GB RAM, local SSD) running lightweight always-on services, remote dev environments, and home automation experimentation. Synology NAS on the LAN for backups.

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
| [00: Overview](plans/homelab_00_overview.md) | Mental entry point: goals, hardware, philosophy, constraints |
| [01: Plan](plans/homelab_01_plan.md) | Practical setup checklist: OS, disk layout, stack, directory conventions |
| [02: Architecture](plans/homelab_02_architecture.md) | Decision rationale: why Compose, why Ubuntu, why Tailscale, tradeoffs |
| [03: Host Setup](plans/homelab_03_host_setup.md) | Concrete commands to reproduce the host from bare metal (install, disk, SSH, Docker, Tailscale, deploy access) |
| 04: Services | _Service registry has graduated to [services/README.md](services/README.md). Plan retained as historical context._ |
| [05: Backup and Recovery](plans/homelab_05_backup_and_recovery.md) | Backup targets, tools, restore procedure |
| [06: Operations](plans/homelab_06_operations.md) | Runbook: deploy, restart, disk cleanup, reboot, troubleshooting |
| [07: Agent Access Model](plans/homelab_07_agent_access_model.md) | How coding/admin agents interact with the host safely |

## Services

Full deployment pattern, on-host paths, and a per-service registry (purpose, data location,
access, env vars, backup status) live in **[services/README.md](services/README.md)**. Each
service also has its own README with first-time setup and operations.

| Service | What it is | Details |
|---------|------------|---------|
| climate-auto-switch | 15-min systemd timer running seasonal HVAC comfort switching | [README](services/climate-auto-switch/README.md) |
| backup | Nightly restic backups of `/srv/data` (GFS retention, Postgres dump support) | [README](services/backup/README.md) |
| obsidian-sync | Headless Obsidian Sync clients keeping vaults on-host for agent access | [README](services/obsidian-sync/README.md) |
| brineworks-server | FastAPI PRM backend (contacts/interactions), Tailscale Services | [README](services/brineworks-server/README.md) |
| taskchampion-sync | Self-hosted Taskwarrior sync server (client-side encryption) | [README](services/taskchampion-sync/README.md) |
| github-actions-runner | Self-hosted GitHub Actions runner for the pirpg repo | [README](services/github-actions-runner/README.md) |

All services deploy the same way from the Mac: `just dotenv` to refresh secrets, then
`just deploy-<service>`. See the registry for the shared file layout and the per-service
README for prerequisites and monitoring commands.
