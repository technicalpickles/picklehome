# Homelab

Single Intel NUC (Celeron J3455, 16 GB RAM, local SSD) running lightweight always-on services, remote dev environments, and home automation experimentation. Synology NAS on the LAN for backups.

**Philosophy:** simple, reproducible, recoverable. No cluster tooling. Easy to rebuild from source control and backups.

**Stack:** Ubuntu Server LTS, Docker Compose (per-service), systemd, Tailscale, git-managed infra repo.

## Secrets

Secrets live in 1Password and never land on picklelab as plaintext. Each service directory has an `.env.vars` file naming the vars it needs; `deploy.sh` runs `scripts/service-env --template` on the host to filter the committed `.env.template` down to those keys (as `op://` references, in `.env.op.template`), and the service's systemd unit wraps `docker compose` in `op run --env-file=<that template>` against a read-only 1Password service-account token in `/etc/opt/homelab/`. Secrets resolve at container start and exist only in the container's environment.

`just dotenv` and the Mac-side `.env` are for local dev only; no deploy reads them. The one exception is `backup`, which still uses a scp'd `.env` (tracked as taskwarrior `4ea7fee5-a274-4a1a-9b20-aecda2cda569`).

When adding a new service:
1. Add required secrets to 1Password and `.env.template`
2. Create `homelab/services/<service>/.env.vars` listing the needed var names
3. Have `deploy.sh` write the filtered template, and wrap both `ExecStart` and `ExecStop` in the unit with `op run` (compose interpolates `${VAR:?required}` on every subcommand, `down` included)
4. Use `environment:` in compose, not `env_file:`; `op run` puts secrets in the process environment, so `env_file:` is inert
5. Add a one-line `deploy-<service>` recipe that calls `just _deploy-remote <service> {{host}}`

The full pattern, host paths, and the per-service registry are in [services/README.md](services/README.md).

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
| obsidian-sync | Headless Obsidian Sync clients keeping vaults (`rpg`, `pickled-knowledge`) on-host at `/srv/data/obsidian-sync/vaults/<vault>/` for agent access | [README](services/obsidian-sync/README.md) |
| brineworks-server | FastAPI PRM backend (contacts/interactions), Tailscale Services; app code and base compose in the `brineworks` repo | [README](services/brineworks-server/README.md) |
| brineworks-agent | Phone-reachable Claude Code + `bw` session (SSH+tmux over Tailscale) for email triage | [README](services/brineworks-agent/README.md) |
| second-brain-agent | Phone-reachable Claude Code session with the `pickled-knowledge` vault mounted read-write at `/vault`; app code in the `second-brain-agent` repo | [README](services/second-brain-agent/README.md) |
| taskchampion-sync | Self-hosted Taskwarrior sync server (client-side encryption) | [README](services/taskchampion-sync/README.md) |
| github-actions-runner | Self-hosted GitHub Actions runner for the pirpg repo | [README](services/github-actions-runner/README.md) |
| woodpecker | Self-hosted Woodpecker CI for private GitHub repos (Funnel ingress) | [README](services/woodpecker/README.md) |
| openclaw | Self-hosted OpenClaw agent gateway (Telegram + Tailscale UI); config partly comes from the `pickleclaw` repo | [README](services/openclaw/README.md) |
| open-webui | Open WebUI chat interface backed by Ollama Cloud, with the open-terminal sidecar | [README](services/open-webui/README.md) |
| nikke | Roster dashboard + sync timer; app code and base compose in the `nikke-roster-scanner` repo | [README](services/nikke/README.md) |
| disk-hygiene | Weekly docker-prune timer plus the read-only `just disk-report` diagnostic | [README](services/disk-hygiene/README.md) |

`services/disk_monitor/` is a Mac-side script that polls picklelab's disk usage over ssh (`just disk-monitor-check`), not a deployed service.

Every service deploys the same way from the Mac: `just deploy-<service>`, which checks the local `main` is clean and pushed, then runs one ssh command that pulls and executes that service's `deploy.sh`. See the registry for the shared file layout and the per-service README for prerequisites and monitoring commands. `openclaw` and `backup` wrap that with an extra scp step (private config includes, and backup's legacy `.env`); the rest go straight through `_deploy-remote`.

**pickleclaw vs. openclaw:** "OpenClaw" is the open-source self-hosted chat-to-agent gateway ([docs.openclaw.ai](https://docs.openclaw.ai/)). `pickleclaw` is a separate sibling repo (`technicalpickles/pickleclaw`), the original local OrbStack-VM spike running it. `services/openclaw/` is the productionized deploy of that same setup on picklelab; its config partly symlinks from the `pickleclaw` repo (see that service's README).
