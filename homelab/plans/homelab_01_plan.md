# Homelab Implementation Plan

This document captures the concrete, practical plan for building and operating the single‑node homelab server. It is intended to function as a checklist and operational baseline.

---

## Host Operating System

- Install **Ubuntu Server 24.04 LTS** (minimal install)
- Enable OpenSSH server during install
- Configure static DHCP lease on the router
- Update BIOS and enable **auto power‑on after power loss**

### Base Configuration

- Create primary admin user with SSH key login only
- Disable password SSH login
- Enable unattended security updates
- Configure a **2 GB swapfile**
- Set hostname to a stable, meaningful name (e.g., `nuc`)

---

## Disk Layout Strategy

Primary goal: **prevent container workloads from exhausting the root filesystem.**

On small Docker hosts, the most common cause of "server suddenly dead" is unbounded container log growth (`json-file` driver with no limits), followed by stale images and build cache accumulation. The daemon config below addresses both.

Recommended layout:

- `/` → ~30 GB
- `/srv` → remainder of SSD

Docker data root should live under `/srv`.

Example Docker daemon config:

```json
{
  "data-root": "/srv/docker",
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Create persistent data directories:

```
/srv/data/<service>
/srv/containers/<service>
```

---

## Core Runtime Stack

Install:

- Docker Engine + Compose plugin
- Tailscale
- git
- tmux / editor / core utilities

Enable Docker at boot.

Tailscale must run **on the host (not inside Docker)** to provide reliable remote access even if container networking fails.

---

## Service Management Model

Each service runs as an independent Docker Compose project.

Example structure:

```
/srv/containers/homeassistant
/srv/containers/caddy
/srv/containers/app1
```

Persistent data:

```
/srv/data/homeassistant
/srv/data/app1
```

Compose conventions:

- explicit project names
- bind mounts for all important state
- restart policies enabled
- healthchecks where practical

### systemd Integration

Create templated systemd units to manage Compose apps:

- `docker-compose@homeassistant.service`
- `docker-compose@caddy.service`

Benefits:

- predictable boot ordering
- simple restart semantics
- centralized logging via journald

---

## Networking and Access

Primary remote access mechanism: **Tailscale.**

Goals:

- no direct public exposure initially
- remote SSH via Tailscale
- optional service exposure via Tailscale Serve

Internal service naming options:

- Use Tailscale MagicDNS hostnames
- Optionally introduce reverse proxy (e.g., Caddy) later for friendly internal names

---

## Development Workloads

The host will support **ephemeral devcontainer‑based development** and **agent‑assisted host administration.**

Primary editor is **neovim** (not VS Code). The expected workflow involves SSH into the host via Tailscale and working from the terminal.

### Open questions

- **Devcontainers over a remote Docker host:** devcontainers work locally and over SSH, but the exact workflow for running them against a remote Docker engine (without VS Code) needs investigation. Options may include devcontainer CLI, direct Docker Compose, or SSH + local container reopen.
- **Agent as host admin:** a coding agent (e.g., Claude Code) should be usable over SSH for managing the host through the infra repo and wrapper commands, the same access model described in the agent access doc.

Devcontainer images and build cache are treated as disposable and subject to periodic pruning.

---

## Backup Strategy (Initial Phase)

Target: Synology NAS on local network.

Initial approach:

- Nightly backup of `/srv/data`
- Backup of infrastructure repo (`/opt/homelab`)

Tools:

- Start with rsync if simplicity is preferred
- Consider migrating to restic for snapshotting and retention

Backups must not include `/srv/docker` image layers.

---

## Infrastructure Repository

Location: `/opt/homelab`

Contents:

```
compose/
systemd/
scripts/
checks/
docs/
```

A single entrypoint script (e.g., `homelab`) provides operational commands:

- bootstrap host
- deploy service
- run validation checks
- run backup

This script forms the **safe control surface** for both humans and automation.

---

## Agent Administration Model

Future goal: allow a coding/admin agent to assist with operations.

Principles:

- Agent modifies infra repo rather than arbitrary host files
- Agent uses wrapper commands instead of raw Docker/systemctl
- Limited sudo permissions granted for specific operational commands
- All changes followed by validation checks

---

## Maintenance Practices

- Periodic Docker image / build cache pruning
- Monitor disk usage on `/srv`
- Keep service count low and resource usage lightweight
- Test restore procedure occasionally

---

## Near‑Term Roadmap

- Introduce reverse proxy for internal HTTPS hostnames
- Add goss validation checks (prior experience with the tool; strong fit for this use case)
- Improve backup automation and retention
- Consider moving Home Assistant to dedicated hardware if it becomes critical

This plan is expected to evolve as operational experience accumulates.

