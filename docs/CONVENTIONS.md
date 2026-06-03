# Documentation Conventions

## Where information belongs

### Code comments

Implementation details that explain *why* the code works the way it does. Anyone reading the code should find the explanation right where they need it.

Examples:
- Why a class overrides a parent method
- What a sentinel value means and why we convert it
- Why all async work must happen in a single call
- What an exception means and how to recover

### README.md (per module)

Reference documentation for anyone using or extending the module. Covers setup, commands, architecture, API details, and findings from integration work.

Each major module directory should have a README.md:
- `climate/README.md`: overview of all climate subsystems
- `climate/blueair/README.md`: BlueAir-specific API details and commands
- `network/README.md`: network diagnostic tools

README content includes:
- Setup steps and prerequisites
- Command reference with examples
- Configuration file format and options
- API capabilities and limitations
- Device-specific findings (sensor availability, value ranges, quirks)
- Module structure

### CLAUDE.md (per module)

Agent-specific workflow and process guidance: things that shape *how to approach work*, not *how the code works*. Keep these short.

Examples:
- "Read the spec before changing config" (workflow directive)
- Pointers to library source clones for reference
- Which file is the source of truth for a domain

CLAUDE.md should `@import` the README for shared context rather than duplicating it.

### docs/plans/

Design documents and implementation plans. Named `YYYY-MM-DD-<topic>.md`. These are point-in-time artifacts: they capture the thinking behind a design, not ongoing reference material.

### Taskwarrior (the backlog)

Concrete, actionable items: things to do, optionally with dates. Not prose about how something works. Entry point: `task list project:picklehome`, organized by the dotted project hierarchy. A "remaining mystery", a "TODO later", or a "followup" is a task, not a doc and not a memory entry.

### Agent memory (not committed)

The agent keeps a file-based memory outside the repo. It is not version controlled, so unlike everything above it has no forcing function to stay in sync with the code: no PR reviews it, no docs pass sweeps it. Two things belong there and nowhere else:

- **Sensitive data that can't be committed:** device MACs, internal IPs, anything geolocatable. (Secrets go in 1Password instead.)
- **Things with no repo home:** who you are, how you want the agent to work, and in-flight thinking not yet reflected in the code.

Memory points at the repo, it does not copy it. A memory entry that restates the directory layout, an API quirk, or a test count drifts silently the moment the code changes. If a fact is true about the code and not sensitive, it lives in the repo (code, README, or CLAUDE.md) and memory at most links to where.

## Where does this fact go?

| The fact is... | Goes in |
|----------------|---------|
| Sensitive (MAC, internal IP, geolocatable) | Memory, or 1Password for secrets. Never committed. |
| Current truth about how the code works | Code comment, README, or CLAUDE.md (it travels with the code) |
| Something concrete to do | Taskwarrior |
| About you, how to work, or thinking not yet in code | Memory |

## Principles

- **Don't duplicate.** If it's in the code comments, don't repeat it in the README. If it's in the README, don't repeat it in CLAUDE.md.
- **Put it where you'd look for it.** Code facts go in the code. Usage docs go in the README. Process guidance goes in CLAUDE.md.
- **Implementation findings are for everyone.** Quirks discovered during integration (API behavior, device capabilities, value formats) belong in the README, not hidden in CLAUDE.md.
- **CLAUDE.md imports, doesn't repeat.** Use `@README.md` to pull in shared context.
- **Memory points, doesn't copy.** Repo docs have a forcing function and stay current; memory doesn't, so a copied fact rots there silently. Memory links to the repo rather than restating it.
