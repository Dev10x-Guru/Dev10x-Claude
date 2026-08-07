---
name: Dev10x:memory-maintenance
description: >
  Audit project and global memory files for stale patterns,
  version-pinned paths, contradictory instructions, and anti-patterns
  that cause skill bypass or permission friction. Reports findings
  and offers to clean up.
  TRIGGER when: user wants to audit memory health, after a plugin
  upgrade, or when agents keep bypassing skills despite memory
  instructions.
  DO NOT TRIGGER when: user wants to save or recall a specific
  memory (use the auto memory system directly).
user-invocable: true
invocation-name: Dev10x:memory-maintenance
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - Write
  - Edit
---

# Dev10x:memory-maintenance — Memory Health Auditor

## Overview

Memory files accumulate over time and can become stale, contradictory,
or actively harmful. This skill audits memory files across all scopes
(global, project, plugin) and identifies issues that cause agents to
misbehave — particularly patterns that lead to skill bypass.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Discover memory files", activeForm="Discovering")`
2. `TaskCreate(subject="Analyze for anti-patterns", activeForm="Analyzing")`
3. `TaskCreate(subject="Present findings", activeForm="Presenting")`
4. `TaskCreate(subject="Apply fixes", activeForm="Applying fixes")`

## Phase 1: Discover Memory Files

Scan all memory locations:

1. Global memory: `~/.claude/memory/*.md`
2. Dev10x global config: `~/.config/Dev10x/**`
3. MEMORY.md index file: `~/.claude/memory/MEMORY.md`

Count files per scope and report.

## Phase 2: Analyze for Anti-Patterns

For each memory file, check for these categories:

### Category 1: Stale Plugin Paths

Search for hardcoded plugin cache paths with version numbers:

```
~/.claude/plugins/cache/Dev10x-Guru/dev10x-claude/0.XX.0/...
```

These break on plugin upgrades. Replace with:
- `${CLAUDE_PLUGIN_ROOT}/...` (in skill contexts)
- MCP tool calls (in memory instructions)
- Skill() invocations (in workflow instructions)

### Category 2: Script-Calling Instructions

Search for memory entries that instruct agents to call scripts
directly instead of using Skill() or MCP tools:

- Patterns: `Bash(`, `scripts/`, `.sh`, `.py` with execution
  context (not documentation references)
- Exceptions: Memory files documenting the feedback itself
  (like `feedback_use_skills_not_scripts.md`) are not violations

### Category 3: Contradictory Instructions

Search for memory entries that contradict each other:

- Two memories giving opposite advice for the same scenario
- A memory instruction that conflicts with a CLAUDE.md rule
- A memory instruction that conflicts with a skill's SKILL.md

### Category 4: Stale References

Search for references to things that no longer exist:

- Deleted files referenced in memory
- Renamed skills referenced by old name
- Closed tickets referenced as "in progress"
- Dates more than 30 days old on project memories

### Category 5: MEMORY.md Index Drift

Compare MEMORY.md index entries against actual files:

- Files listed in MEMORY.md that don't exist on disk
- Files on disk not listed in MEMORY.md
- Descriptions that don't match file content

## Phase 3: Present Findings

Display findings grouped by category and severity:

| Severity | Meaning |
|----------|---------|
| ERROR | Actively causing misbehavior |
| WARNING | Likely to cause issues |
| INFO | Maintenance opportunity |

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Fix all non-INFO** (Recommended) — Auto-fix ERROR and WARNING
- **Review each** — Walk through findings one by one
- **Export report** — Save to temp file
- **Done** — No changes

## Phase 4: Apply Fixes

For each approved fix:

### Stale Plugin Paths
- Replace versioned paths with generic references
- Update the memory file in place via Edit tool

### Script-Calling Instructions
- Replace script paths with Skill() or MCP tool references
- Update the instruction to use the priority order:
  MCP tool → Skill() → gh CLI → Script (fallback only)

### MEMORY.md Index Drift
- Remove entries for deleted files
- Add entries for unlisted files
- Update descriptions to match content

### Stale References
- Flag for user review (don't auto-delete — may be intentional)
- Offer to update or remove

## Important Notes

- **Read-only by default** — only edit files after user approval
- Memory files use frontmatter (name, description, type) — preserve
  it when editing
- MEMORY.md has a 200-line truncation limit — keep it concise
- Some "stale" entries may be intentional historical records —
  flag but don't auto-remove without confirmation
