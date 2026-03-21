# Homelab Architecture

This document explains the architectural choices behind the homelab and records the reasoning for the current design. It is intended to answer two questions:

1. Why was the homelab set up this way?
2. What tradeoffs were accepted in exchange for simplicity and reproducibility?

---

## System Context

The homelab runs on a single Intel NUC with:

- 4 GB RAM
- local SSD storage
- external Synology NAS available for backups and bulk storage

The system is intended to host a small set of lightweight always-on services, support occasional remote development via VS Code devcontainers, and serve as a safe place to experiment with admin automation and coding agents.

This is a constrained single-node environment. It is not designed for high availability, horizontal scaling, or multi-node orchestration.

---

## Design Priorities

The architecture is shaped by the following priorities:

1. **Simplicity**
   - keep the number of moving parts low
   - prefer familiar tools over novel infrastructure

2. **Reproducibility**
   - capture infrastructure layout and service definitions in source control
   - make rebuilds straightforward and fast

3. **Recoverability**
   - design for failure and easy restoration rather than perfect uptime
   - keep backups and state easy to reason about

4. **Operational Clarity**
   - ensure services are easy to inspect, restart, and debug
   - use predictable filesystem layout and service conventions

5. **Practical Automation**
   - support future use of coding/admin agents without giving them unrestricted control of the host

---

## Why Ubuntu Server LTS

Ubuntu Server LTS was chosen as the host operating system because it provides a stable and well-supported baseline for a headless server, while still being convenient to operate.

Reasons for this choice:

- broad ecosystem familiarity and documentation
- strong support for Docker-centric workflows
- unattended security updates for low-friction maintenance
- good hardware support for older Intel small-form-factor systems
- predictable long-term support lifecycle

Tradeoffs accepted:

- slightly more default behavior and packaging complexity than a minimal distro
- not as stripped-down as some appliance-style alternatives

Alternatives considered:

- **Debian**: very strong option for stability and low drama, but Ubuntu was preferred for its convenience and maintenance features
- **specialized appliance distros**: rejected because the host is intended to support mixed workloads, not just a single application role

---

## Why Docker Compose Instead of Kubernetes

Docker Compose is the primary service orchestration model because it fits the actual scale and complexity of the system.

Reasons for this choice:

- existing familiarity with Docker and containers
- low operational overhead
- good fit for a small number of services on one machine
- easy to understand and troubleshoot
- works well with VS Code devcontainers

Kubernetes was not chosen because:

- it introduces substantial complexity relative to the needs of a single-node NUC
- it consumes operational attention better spent on storage, backups, and service hygiene
- it does not solve the primary current problem, which is structure and recoverability rather than scheduling

Tradeoff accepted:

- less abstraction and automation than a full orchestration platform
- some service management concerns must be handled through conventions and wrappers

This is an intentional choice to solve the real problem with the smallest effective tool.

---

## Why Compose Per Service

Each service is managed as its own Compose project rather than combining everything into one large Compose file.

Reasons for this choice:

- clearer ownership and lifecycle boundaries per service
- easier to restart, inspect, and reason about services independently
- simpler migration or removal of individual applications
- better fit for a repo-driven configuration model
- easier to give an agent a controlled surface for making changes

Tradeoffs accepted:

- some repetition across service definitions
- requires conventions for naming, logging, and filesystem layout

The architecture favors explicit separation over centralization.

---

## Why systemd Alongside Docker Compose

Docker Compose manages containers, but systemd remains the host-level process manager.

Reasons for combining them:

- predictable startup at boot
- restart behavior integrated with the host
- centralized service control with `systemctl`
- host-native logging and timer support
- easier to operationalize backups, cleanup, and validation through timers and services

Tradeoff accepted:

- additional layer of configuration compared with running Compose directly by hand

This choice improves recoverability and makes the system feel more like a manageable server than a collection of ad hoc containers.

---

## Why Tailscale for Remote Access

Tailscale is the primary remote access mechanism for administration and service exposure.

Reasons for this choice:

- avoids early public internet exposure
- simplifies remote SSH access
- provides internal naming via MagicDNS
- can expose services securely without opening inbound ports on the router
- reduces operational burden compared to a self-managed VPN

Tradeoffs accepted:

- dependence on Tailscale for remote access workflows
- internal naming and TLS choices may be shaped by Tailscale conventions

Alternatives considered:

- direct public ingress: rejected initially due to higher operational and security burden
- self-hosted VPN: more flexible, but unnecessary for current needs

---

## Why the Disk Layout Separates Root From Service Data

The architecture explicitly separates the root filesystem from service and Docker storage.

Reasons for this choice:

- reduce the risk of container activity filling the root disk
- make persistent service data easier to inspect with standard filesystem tools
- simplify backup scope and restore logic
- avoid treating Docker overlay storage as primary application state

Persistent data is expected to live under `/srv/data`, while Docker runtime storage is expected to live under `/srv/docker`.

Tradeoffs accepted:

- requires more up-front host layout decisions
- introduces some operational discipline around bind mounts and storage locations

This is a protective design choice driven by the limited disk and memory budget of the hardware.

---

## Why Bind Mounts for Important State

Important service state is stored in explicit bind-mounted directories instead of relying on anonymous volumes or writable container layers.

Reasons for this choice:

- easy visibility into disk usage
- straightforward backup targeting
- simpler restore and migration workflows
- fewer surprises around hidden state

Tradeoff accepted:

- a slightly more manual approach to organizing service data

This is a clarity-first decision.

---

## Why the Infrastructure Is Repo-Driven

The homelab treats its configuration as a small infrastructure codebase rather than a collection of hand-edited files.

Reasons for this choice:

- version history for changes
- easier reproducibility
- safer collaboration between human operator and future automation/agents
- a single place to document scripts, checks, Compose files, and operational conventions

Tradeoffs accepted:

- requires maintaining repository structure and discipline
- some setup work moves from one-off shell history into maintained scripts

This is the foundation for rebuilding the system quickly and for letting automation assist without mutating the host arbitrarily.

---

## Why Start With Simple Backup Tooling

The initial backup model is intentionally simple: back up persistent service data and infrastructure definitions to the Synology NAS.

Reasons for this choice:

- local NAS already exists
- simple backups are better than aspirational backup systems that never get finished
- straightforward restore logic matters more than sophisticated backup features at the beginning

Rsync is acceptable for early backups. Restic is a likely evolution path because it adds snapshots, retention, and encryption without changing the high-level architecture.

Tradeoff accepted:

- initial backup sophistication may be limited until more operational experience is gained

---

## Why Home Assistant Is Containerized Short Term

Home Assistant is expected to run in a container initially, with the option to move it to dedicated hardware later if it becomes important household infrastructure.

Reasons for this choice:

- fast path to experimentation
- avoids overcommitting early architecture to one application
- keeps the NUC useful as a general-purpose lab host

Tradeoff accepted:

- Home Assistant will not initially have the appliance-style isolation or UX of a dedicated install

This is an intentional short-term compromise in favor of flexibility.

---

## Why the Agent Model Uses Controlled Interfaces

A future coding/admin agent should be able to do useful work without being given unrestricted root-level authority over the host.

Reasons for this design direction:

- direct arbitrary mutation of the host is hard to reason about and recover from
- repo-driven changes are easier to audit and validate
- wrapper scripts create a narrower, more predictable control surface
- validation checks can be run after changes

Tradeoff accepted:

- the agent may have to work through operational interfaces rather than taking shortcuts

This approach favors practical automation over maximum freedom.

---

## Rejected or Deferred Complexity

The following ideas were considered but intentionally deferred:

- **Kubernetes / k3s / full cluster tooling**
  - too much complexity for the current scale

- **heavy configuration management systems**
  - tools like Puppet are powerful, but likely too much framework for a single host at this stage

- **multi-node architecture**
  - unnecessary until a real scaling or availability problem appears

- **public ingress first**
  - security and operational overhead are not justified early on

- **over-optimized sandboxing**
  - useful agent automation requires enough access to actually accomplish tasks; guardrails matter more than theoretical isolation purity

---

## Architectural Summary

The homelab architecture is intentionally conservative.

It uses:

- Ubuntu Server LTS
- Docker Compose per service
- systemd for host-level lifecycle control
- Tailscale for remote access
- explicit filesystem layout under `/srv`
- repo-driven configuration
- simple, evolvable backup strategy

This design does not aim to be elegant in the abstract. It aims to be understandable, practical, and resilient on small hardware.

The core philosophy is:

**use the lightest-weight structure that makes the system easy to operate, rebuild, and evolve.**

