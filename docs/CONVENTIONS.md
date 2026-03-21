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
- `climate/README.md` — overview of all climate subsystems
- `climate/blueair/README.md` — BlueAir-specific API details and commands
- `network/README.md` — network diagnostic tools

README content includes:
- Setup steps and prerequisites
- Command reference with examples
- Configuration file format and options
- API capabilities and limitations
- Device-specific findings (sensor availability, value ranges, quirks)
- Module structure

### CLAUDE.md (per module)

Agent-specific workflow and process guidance — things that shape *how to approach work*, not *how the code works*. Keep these short.

Examples:
- "Read the spec before changing config" (workflow directive)
- Pointers to library source clones for reference
- Which file is the source of truth for a domain

CLAUDE.md should `@import` the README for shared context rather than duplicating it.

### docs/plans/

Design documents and implementation plans. Named `YYYY-MM-DD-<topic>.md`. These are point-in-time artifacts — they capture the thinking behind a design, not ongoing reference material.

## Principles

- **Don't duplicate.** If it's in the code comments, don't repeat it in the README. If it's in the README, don't repeat it in CLAUDE.md.
- **Put it where you'd look for it.** Code facts go in the code. Usage docs go in the README. Process guidance goes in CLAUDE.md.
- **Implementation findings are for everyone.** Quirks discovered during integration (API behavior, device capabilities, value formats) belong in the README, not hidden in CLAUDE.md.
- **CLAUDE.md imports, doesn't repeat.** Use `@README.md` to pull in shared context.
