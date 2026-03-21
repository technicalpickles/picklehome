# Services

_TODO: registry of each service running on the homelab._

Each service should document:

- Purpose
- Compose location (`/srv/containers/<service>`)
- Persistent data path (`/srv/data/<service>`)
- Access URL / hostname
- Restart strategy
- Backup considerations
- Notes

Planned services:

- Home Assistant (containerized short-term, may migrate to dedicated hardware)
- Caddy reverse proxy (internal HTTPS hostnames)
