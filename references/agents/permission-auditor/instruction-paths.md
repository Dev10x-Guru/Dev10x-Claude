# Instruction File Path Audit

Reference material for the `permission-auditor` agent — Phase 6.
The agent spec links here for the file scan list, the pattern
table, the per-match action steps, and the SKILL.md exclusion
rule.

## Files to scan

- `CLAUDE.md` in project root and `.claude/` directories
- `~/.claude/CLAUDE.md` (global instructions)
- `~/.config/Dev10x/**/*.md` (memory files)

## Patterns to flag

| Pattern | Severity | Rationale |
|---------|----------|-----------|
| `~/.claude/skills/*/scripts/*` | WARNING | Hardcoded skill script path — breaks on plugin updates |
| `~/.claude/plugins/cache/*/*/skills/*/scripts/*` | WARNING | Resolved plugin cache path — ephemeral across versions |
| `~/.claude/tools/*.py` called without skill context | LOW | May be intentional but worth noting |

## For each match

1. Identify the script's parent skill (from the path or nearby
   SKILL.md)
2. Suggest the skill invocation name as replacement
3. If the script is wrapped by an MCP tool, suggest the MCP
   tool name

## Classification

- Paths inside SKILL.md files are **excluded** (skills
  legitimately reference their own scripts)
- Paths in CLAUDE.md or memory files are **flagged**
  (instruction leaks that bypass skill context)
