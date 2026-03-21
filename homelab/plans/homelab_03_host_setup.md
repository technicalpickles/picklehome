# Host Setup

_TODO: concrete commands and configuration to reproduce the NUC host from bare metal._

Planned sections:

- BIOS configuration (auto power-on after power loss)
- Ubuntu Server 24.04 LTS install notes
- Admin user + SSH key-only login
- Swapfile creation (2 GB)
- Disk partitioning (`/` ~30 GB, `/srv` remainder)
- Docker Engine + Compose plugin install and `daemon.json`
- Tailscale install (on host, not in Docker)
- `/srv` directory layout creation
- Unattended security updates
- Log rotation config
- Cloning infra repo to `/opt/homelab`
