# Agent Access Model

This document defines how coding or administrative agents are expected to interact with the homelab host.

The goal is to make agents genuinely useful for operations and maintenance without giving them unrestricted, opaque control of the system.

The design does not aim for perfect isolation. It aims for **practical guardrails, predictable workflows, and recoverable failure modes.**

---

## Goals

The agent model is designed to support the following outcomes:

- allow agents to perform meaningful operational work
- reduce the chance of catastrophic host damage
- make agent actions understandable and auditable
- preserve a clean separation between desired state and host mutation
- keep the system operable by a human without depending on the agent

---

## Guiding Principles

### Agents Need Enough Access To Be Useful

A sandbox that blocks most real work is not helpful.

The model intentionally allows agents enough authority to:

- inspect system state
- modify infrastructure definitions
- deploy or restart services
- run validation checks
- assist with backup or recovery operations

The priority is not minimal access at all costs. The priority is **useful access within a shaped control surface.**

### Narrow Interfaces Are Better Than Raw Freedom

Agents should interact with the system through a small number of predictable interfaces whenever possible.

Preferred pattern:

- edit files in the infrastructure repository
- run wrapper commands
- invoke validation checks
- inspect logs and service state

Less preferred pattern:

- arbitrary ad hoc changes across the host filesystem
- direct mutation of runtime state without corresponding source-of-truth updates

### Recoverability Matters More Than Theoretical Purity

The system should assume that agent mistakes will happen.

Design choices should therefore emphasize:

- version-controlled changes
- backups of persistent state
- validation after mutation
- limited blast radius for common operations
- easy rollback and rebuild

---

## Scope of Agent Authority

### Expected Agent Capabilities

The agent may eventually be allowed to:

- read service definitions, scripts, and documentation
- inspect Docker containers, images, and logs
- inspect systemd service status
- edit Compose files and wrapper scripts in the infra repository
- trigger service deploys or restarts through approved commands
- run operational checks and validation
- initiate backups through approved commands

### Capabilities To Avoid By Default

The following should not be broadly exposed without a strong reason:

- unrestricted root shell access
- arbitrary writes across `/etc`, `/usr`, or `/`
- unrestricted package installation
- unrestricted destructive Docker commands
- direct editing of sudoers or core security configuration
- broad public network exposure changes

These actions are not forbidden forever, but they should not be the default operating model.

---

## Preferred Control Surface

The preferred agent workflow is:

1. inspect current state
2. modify source-controlled configuration
3. run an approved apply command
4. run validation checks
5. inspect resulting state and logs

The main control surface should be the infrastructure repository at:

```
/opt/homelab
```

This repository should contain:

- Compose definitions
- systemd units or templates
- wrapper scripts
- validation checks
- documentation

The more the host can be driven from this repository, the easier it is for both humans and agents to operate safely.

---

## Filesystem Access Model

### Writable Areas

The agent may be allowed write access to:

- `/opt/homelab`
- explicitly designated working directories
- optional scratch or temp directories

### Read-Heavy Areas

The agent may be allowed read access to:

- `/srv/data` (or selected service directories)
- `/srv/containers`
- `/etc` where needed for inspection
- system logs

### Restricted Areas

Write access should be limited or mediated for:

- `/etc`
- `/usr`
- `/boot`
- `/root`
- arbitrary paths outside the infra repo and approved data locations

This model encourages agents to operate on declared configuration first and mutate the host through controlled mechanisms second.

---

## Command and Privilege Model

The agent should ideally operate as a dedicated non-login user with a limited set of approved elevated commands.

Examples of acceptable elevated actions:

- run homelab wrapper commands
- restart or inspect approved systemd units
- run Docker commands needed for deployment or inspection
- trigger backup commands

Examples of commands that should not be broadly exposed:

- unrestricted `sudo bash`
- arbitrary shell as root
- unrestricted package manager usage
- blanket write access to security-sensitive configuration

A practical pattern is to allow passwordless sudo only for:

- `/opt/homelab/scripts/homelab`
- targeted `systemctl` commands
- targeted Docker commands if needed

This keeps the useful operational path short and intentional.

---

## Wrapper Command Strategy

A small wrapper CLI should become the standard interface for operational changes.

Possible commands:

- `homelab bootstrap`
- `homelab apply host`
- `homelab apply service <name>`
- `homelab restart service <name>`
- `homelab check`
- `homelab backup`
- `homelab restore <target>`

Benefits:

- one consistent operator interface
- easier auditing and logging
- simpler agent prompting and task design
- reduced need for agents to improvise low-level command sequences

This wrapper layer becomes the main contract between automation and infrastructure.

---

## Validation and Safety Checks

Every meaningful mutation should be followed by checks.

Validation may include:

- service enablement and running status
- container health
- port availability
- filesystem presence and permissions
- reverse proxy route checks
- disk space thresholds
- backup timer and job presence

Tools such as goss are a good fit for this layer.

The goal is not just to apply changes, but to verify that the system still matches expectations afterward.

---

## Logging and Auditability

Agent operations should be easy to reconstruct after the fact.

Useful practices:

- require changes through the infra repo where possible
- commit or snapshot config changes before applying them
- log wrapper command execution
- preserve validation output
- keep service logs accessible via journald and Docker logs

A useful system is one where a human can answer:

- what changed?
- who or what changed it?
- did validation pass?
- how do we roll it back?

---

## Failure and Rollback Model

The design assumes that agents will sometimes make mistakes.

Expected failure modes include:

- incorrect Compose edits
- bad restart sequences
- accidental disk pressure
- invalid reverse proxy or routing configuration
- overly aggressive cleanup operations

The system should make recovery straightforward by relying on:

- git history for infra changes
- backups for persistent data
- restartable services with known locations
- documented restore procedures

The agent model is successful when mistakes are inconvenient rather than catastrophic.

---

## Sandboxing Philosophy

Strict sandboxing alone is not sufficient.

The most important protections in this environment are:

- constrained writable paths
- narrow operational interfaces
- limited sudo surface
- source-controlled config
- backups and restore procedures
- post-change validation

Process or container sandboxing may still be useful, especially for running an agent runtime, but it should not be mistaken for the primary control mechanism.

The main risk is usually not kernel escape. It is incorrect but fully authorized changes to real system state.

---

## Human Override and Manual Operability

The homelab must remain fully operable by a human without depending on the agent.

This means:

- all wrapper commands should be usable manually
- the repo layout should be understandable without agent context
- service definitions should remain readable and conventional
- recovery should not require reproducing agent reasoning

The agent is an assistant, not a hidden control plane.

---

## Evolution Path

The initial model should stay simple.

Reasonable evolution steps:

1. agent can read repo and logs
2. agent can edit infra repo
3. agent can run wrapper commands
4. agent can use limited sudo for deploy/restart/backup actions
5. agent can propose larger host changes subject to review

This allows trust and capability to grow together.

---

## Summary

The homelab agent model is built around one idea:

**give the agent enough access to do real work, but shape that access through repo-driven configuration, wrapper commands, validation, and recoverable workflows.**

This model favors usefulness, auditability, and operational clarity over either extreme:

- not unrestricted root-level chaos
- not a sandbox so strict that the agent becomes ineffective

It is designed to support practical automation on a small, understandable server.

