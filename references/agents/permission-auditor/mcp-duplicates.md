# MCP Horizontal-Duplicate Detection

Reference material for the `permission-auditor` agent — Phase 4b
(GH-371). The agent spec links here for the source-type table, the
per-finding report steps, and the severity rationale.

## Why it matters

Catalog rules target one MCP prefix. When the same logical capability
arrives from two installations under different prefixes, a rule
covering one leaves the other prompting — the duplication is invisible
in the settings file because neither rule looks wrong on its own.

## Source types

| Source | Prefix shape |
|--------|--------------|
| claude.ai-hosted | `mcp__claude_ai_<Service>__*` |
| user-installed via `claude mcp add` | `mcp__<service>__*` |
| plugin-distributed | `mcp__plugin_<plugin>_<srv>__*` |

## Detection

Run the `mcp-horizontal-duplicates` doctor strategy, registered in
`src/dev10x/skills/doctor/registry.py`.

## Per-finding report steps

1. Report the capability name and how many servers expose it.
2. List each (prefix, example tool) pair.
3. Note that catalog rules targeting one prefix do NOT cover the others.
4. Surface consolidation as an option — do NOT force it.

## Severity

**LOW** (informational). The duplication may be intentional — for
example, keeping a backup server when the hosted one is flaky. Surface
it for user awareness only; never propose removal on this basis alone.
