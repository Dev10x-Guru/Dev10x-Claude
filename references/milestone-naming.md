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

Every milestone title begins with a **namespaced prefix** that
identifies the initiative, followed by the outcome the milestone
delivers. It carries **no sequence number**.

```
<INIT>: <outcome>
```

| Field | Rule |
|-------|------|
| `<INIT>` | 2–6 uppercase letters identifying the initiative (see table below) |
| `: ` | Colon + space separator |
| `<outcome>` | What the milestone delivers, ≤ 50 characters |

**Examples:**

```
AUD: Domain Boundary Safety
AUD: Test Coverage Architectural Gaps
MCP: MCP daemon foundation
MCP: Installable GitHub bot/Action
```

### Ordering is a dependency, not a number (GH-1515)

A sequence number after the prefix (`AUD-M1`, `CREW-M2`) is what
`dev10x:project-scope` forbids since GH-1509: numbered names make
milestones hard to split or merge, because every later title has to
be renamed. The prefix namespaces; it does not order.

Record ordering in the milestone **description** instead, as a
`Depends on: <milestone name>` line, using the format in
[`skills/project-scope/references/milestone-description.md`](../skills/project-scope/references/milestone-description.md).
Omit the line only when the milestone can start now.

## Registered Initiative Prefixes

| Prefix | Initiative | Status |
|--------|-----------|--------|
| `AUD` | Architecture audit series (2026-05-18) | closed (archived) |
| `MCP` | MCP knowledge primitives roadmap | active |
| `PKG` | Per-package architecture & code-review audit (2026-06-10) | active |
| `PERM` | Permission-friction reduction (GH-488) | active |
| `GATE` | Friction gate-policy resolver (ADR-0016, GH-751) | active |
| `SPLIT` | Core-plus-satellite plugin split (ADR-0020, GH-913) | closed (rejected) |
| `QA` | qa-self evidence integrity & portability (2026-09-08) | active |
| `ARCH` | Full architecture audit (2026-09-19) — patterns, archetypes, concurrency, best practices | active |
| `PLG` | Staged plugin split, restructure first (ADR-0034, GH-1522) | active |
| `HOOK` | Hook guards, performance & diagnostics (Claude2 port, 2026-10-18) | active |
| `SKL` | Skill & permission tooling, new authoring skills (Claude2 port, 2026-10-18) | active |
| `ADOPT` | Onboarding & distribution (Claude2 port, 2026-10-18) | active |
| `CONT` | Video series, walkthrough & website content (Claude2 port, 2026-10-18) | active |
| `PLAT` | Profiles, skill porting & model/platform compatibility | active |
| `CREW` | Unattended-run (foreman/crew/subagent) reliability | active |
| `FRIC` | Single-baseline friction model & config migration (ADR-0022) | active |
| `PRW` | PR workflow correctness (gh-pr-* and git skills) | active |
| `DX` | Developer experience: session UX, repo hygiene, green CI | active |
| `COMM` | Chat-driven sessions (Google Chat / Slack watch & reply) | active |

When starting a new initiative that spans multiple milestones, register
its prefix here before creating the first milestone. Pick a prefix that
does not conflict with an existing entry.

**Enforced at creation (GH-1690).** `milestone_create` — and so
`milestones_bulk_create`, which calls it per entry — reads this table
from the current checkout and refuses a title whose `<INIT>` prefix is
missing, before any API call. The error names the row to add. Legacy
`<INIT>-M<n>: ` titles are read by their `<INIT>`. A checkout without
this file is not guarded, so the tool still serves other repos.

The check runs only when a milestone is created, so prefixes of closed
milestones created before it (`CONC`, `FOREMAN`, `GHTOOL`) need no
rows. A milestone created in the web UI bypasses it; the periodic sweep
still covers that path.

## Lifecycle Rule

Close a milestone as soon as its `open_issues` count reaches 0.
A milestone with no open issues in `open` state pollutes the active
list and creates confusion about what is in flight.

Use `mcp__plugin_dev10x_cli__milestone_close` (not raw `gh api`)
to close milestones — the plugin wraps the REST call with proper
permission handling.

## Retroactive renaming

Milestones created before this convention existed — including open
ones still named `<INIT>-M<n>` — are not renamed. Closed milestones
are invisible in the default milestone list, and renaming an open one
breaks every saved `milestone:` filter that names it. Apply the
convention to new milestones only.

## Reference

- MCP tool: `mcp__plugin_dev10x_cli__milestone_close`
- MCP tools table: `.claude/rules/mcp-tools.md`
