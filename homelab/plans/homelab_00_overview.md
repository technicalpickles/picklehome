# Homelab Overview

## Purpose

This homelab runs on a single Intel NUC and is intended to support lightweight always‑on services, home automation experimentation, and remote development environments. The system is designed to be simple to operate, easy to rebuild, and safe to experiment on without risking critical data.

Primary goals:

- Run a small number of always‑on self‑hosted services (e.g., Home Assistant, reverse proxy, utility apps)
- Provide a remote Docker host for devcontainers and ad‑hoc development workloads
- Enable safe experimentation with infrastructure automation and coding agents
- Maintain a reproducible system that can be rebuilt quickly from backups and source control

## Hardware Summary

- Intel NUC6CAYH (Celeron J3455, 4‑core/4‑thread, 1.5 GHz base / 2.3 GHz burst, 10 W TDP)
- 4 GB RAM
- Local SSD (2.5" SATA bay) for OS and container workloads
- External Synology NAS available for backups and bulk storage

This is a resource‑constrained single‑node environment. Design choices favor low overhead, operational clarity, and resilience to disk or memory pressure.

## Operating Philosophy

The homelab prioritizes:

- **Simplicity over orchestration** — avoid cluster tooling (e.g., Kubernetes) unless clear value emerges
- **Reproducibility over manual tuning** — infrastructure configuration is captured in source control
- **Isolation via conventions** — services are separated using Docker Compose projects and filesystem layout
- **Recoverability over uptime** — the system should be easy to rebuild rather than engineered for high availability
- **Incremental evolution** — start minimal and add structure only when real operational pain appears

## Core Technology Stack

- Ubuntu Server LTS as the host operating system
- Docker Engine with Compose for service management
- systemd for host‑level lifecycle control and timers
- Tailscale for secure remote access and internal service exposure
- Git‑managed infrastructure repository for declarative configuration

Optional or future components may include:

- Reverse proxy (e.g., Caddy) for internal hostnames and TLS
- restic‑based backups to Synology
- goss for host and service state validation (prior experience; planned, not optional)
- Controlled execution environment for coding or admin agents

## Scope and Constraints

This homelab is:

- A single physical node
- Not intended to provide high availability
- Not a production environment for critical household infrastructure (long‑term plan may move Home Assistant to dedicated hardware)
- Expected to run both persistent services and ephemeral development workloads

Given the limited memory and CPU resources, workloads must remain lightweight and disk usage must be carefully managed.

## Success Criteria

The homelab is considered successful if:

- Services are easy to deploy, inspect, and restart
- Disk exhaustion or runaway containers are unlikely to take down the host OS
- Backups exist and restore procedures are documented and testable
- The system can be rebuilt from scratch in a short amount of time
- Automation and agents can assist with administration without introducing unacceptable risk

This document serves as the mental entry point for understanding the purpose, boundaries, and design intent of the homelab.

