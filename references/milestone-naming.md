# Milestone Naming Convention

Standards for GitHub milestone titles in this repository to prevent
numbering collisions across initiatives and make the milestone list
scannable at a glance.

## Problem (observed 2026-05-31)

Two separate initiative sets both used bare `M1`–`M9` numbering:

- Audit 2026-05-18: `🛡️ M1 — Domain Boundary Safety` … `🧬 M9 — Test Coverage Architectural Gaps`
- MCP Roadmap: `M1 · MCP daemon foundation` … `M6 · Installable GitHub bot/Action`

A reader scanning the milestone list cannot tell which `M1` is meant
without reading the full title. This also makes `milestone:` filters in
issue searches ambiguous.

## Convention

Every milestone title must begin with a **namespaced prefix** that
identifies the initiative, followed by a sequence number.

```
<INIT>-M<n>: <short title>
```

| Field | Rule |
|-------|------|
| `<INIT>` | 2–6 uppercase letters identifying the initiative (see table below) |
| `-M<n>` | Hyphen, capital M, integer (no leading zeros) |
| `: ` | Colon + space separator |
| `<short title>` | Human-readable description, ≤ 50 characters |

**Examples:**

```
AUD-M1: Domain Boundary Safety
AUD-M9: Test Coverage Architectural Gaps
MCP-M1: MCP daemon foundation
MCP-M6: Installable GitHub bot/Action
```

## Registered Initiative Prefixes

| Prefix | Initiative | Status |
|--------|-----------|--------|
| `AUD` | Architecture audit series (2026-05-18) | closed (archived) |
| `MCP` | MCP knowledge primitives roadmap | active |
| `PKG` | Per-package architecture & code-review audit (2026-06-10) | active |
| `PERM` | Permission-friction reduction (GH-488) | active |

When starting a new initiative that spans multiple milestones, register
its prefix here before creating the first milestone. Pick a prefix that
does not conflict with an existing entry.

## Lifecycle Rule

Close a milestone as soon as its `open_issues` count reaches 0.
A milestone with no open issues in `open` state pollutes the active
list and creates confusion about what is in flight.

Use `mcp__plugin_Dev10x_cli__milestone_close` (not raw `gh api`)
to close milestones — the plugin wraps the REST call with proper
permission handling.

## Retroactive renaming

Milestones closed before this convention existed do not need to be
renamed — closed milestones are invisible in the default milestone
list. Apply the prefix only to new milestones going forward.

## Reference

- MCP tool: `mcp__plugin_Dev10x_cli__milestone_close`
- MCP tools table: `.claude/rules/mcp-tools.md`
