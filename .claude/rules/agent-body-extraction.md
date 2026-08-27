# Agent Body Extraction Pattern

Reduce token consumption on sub-agent dispatch by moving stable
reference content out of plugin-distributed agent specs in
`agents/` into sibling files under `references/agents/<name>/`.

## Why extract

When a sub-agent is dispatched via the `Agent` tool, its full
spec body from `agents/<name>.md` is loaded into the dispatched
session as the system prompt. Long phase tables, classification
matrices, and operation matrices hit the dispatcher's context
on every dispatch — even when the agent only needs one phase.

Moving stable reference content into `references/agents/<name>/*.md`
lets the agent read only what a given phase needs, instead of
preloading the whole spec.

This pattern mirrors `skill-body-extraction.md` for skills.

## What to extract

**Keep inline in `agents/<name>.md`** (always needed per dispatch):
- YAML frontmatter (`name`, `description`, `tools`, `model`, `color`)
- Brief overview (≤20 lines) — what the agent does, when to use
- Phase outline: numbered phases with one-paragraph summaries
- Severity definitions and report format (gate the output)
- Key heuristics that apply across phases
- Anti-patterns and "Do NOT modify any files" guardrails

**Move to `references/agents/<name>/`** (loaded on demand):
- Detailed classification tables (allow-rule categories, severity
  matrices, deny/ask/skip recommendations)
- Phase-specific tables that span 10+ rows
- Pattern catalogs (e.g., toxicity patterns, known-safe patterns)
- Worked examples per phase
- Operation tables that map inputs to recommended outputs

**Keep inline even when long** when the content gates execution —
e.g., the "IMPORTANT: Do NOT modify any files" instruction, severity
definitions used for the final report, and the report format itself.
Moving those risks agents producing inconsistent output.

## Extraction mechanics

1. Identify cohesive sections to extract — prefer sections that
   already have a clear heading (`### Phase 3: ...`, `### Known-Safe
   Patterns`, multi-row tables).
2. Create `references/agents/<agent-name>/<section-slug>.md`. Use a
   short slug (`classification.md`, `destructive-ops.md`,
   `instruction-paths.md`).
3. Promote the extracted section's internal headings one level up
   so the reference file reads as a standalone doc:
   - `### Phase 3: Allow Rule Classification` inside the agent
     becomes `# Allow Rule Classification` (or `## Phase 3: ...`)
     in the reference file.
4. In the agent spec, replace the section body with a one-paragraph
   summary plus a pointer:

   ```markdown
   ### Phase 3: Allow Rule Classification

   Classify every allow rule into risk categories and note whether
   it is structurally broken or rule-fixable. See
   [`references/agents/permission-auditor/classification.md`](../references/agents/permission-auditor/classification.md)
   for the full category table, HOOK_ENABLED vs DEAD_RULE
   distinction, toxicity patterns, and known-safe patterns.
   ```

5. When the extracted section contains a guardrail referenced from
   the phase outline (e.g., "Deny rules are absolute — only
   recommend for never-permitted ops"), keep that gating text
   inline in the agent spec and move only the supporting tables.

## Reference path convention

Plugin-distributed agents live at the repo root: `agents/<name>.md`.
Their references live at the repo root under `references/agents/<name>/`.

| File | Path |
|------|------|
| Agent spec | `agents/permission-auditor.md` |
| Per-phase reference | `references/agents/permission-auditor/classification.md` |
| Cross-agent shared reference | `references/<topic>.md` (existing convention) |

Do NOT place references inside `agents/<name>/` — agent discovery
walks `agents/*.md` and a subdirectory there can confuse tooling.
The repo-root `references/agents/<name>/` location keeps the agent
file flat and groups references near other shared docs.

## Budget

- `agents/<name>.md` (plugin-distributed): 200 lines per
  `.claude/rules/agents.md`
- `.claude/agents/<name>.md` (internal review-only): 50 lines —
  rarely needs extraction; if it does, prefer splitting the agent
  itself rather than externalizing references
- `references/agents/<name>/*.md`: 200 lines per file. Split
  further when a reference itself grows beyond the cap.

## Reviewer checklist

When reviewing an agent refactor that extracts content:

1. ✓ Agent spec still contains frontmatter, phase outline,
   severity definitions, and report-format guardrails
2. ✓ Each extracted section has a pointer in the agent spec
   that names the reference path
3. ✓ Reference file headings are promoted one level (no lone
   `###` at the top of a reference doc)
4. ✓ No gating logic moved into references. The "Do NOT modify
   files" instruction, severity definitions, and report shape
   stay inline.
5. ✓ `tools:` frontmatter is unchanged — extracting body content
   does not add or remove tool requirements.
6. ✓ Reference paths use relative links from the agent spec
   (`../references/agents/<name>/<file>.md`).

## Current extraction state

| Agent | Original lines | Current spec | Reference files |
|-------|---------------:|-------------:|-----------------|
| permission-auditor | 226 | <200 | `classification.md`, `destructive-ops.md`, `instruction-paths.md`, `worktree-anchoring.md`, `mcp-duplicates.md` |

Pending work (follow-up tickets): pytest-test-writer (156),
issue-investigator (121). These are within the 200-line budget
today but would benefit from the same pattern as their phase
tables grow.

## Relation to skill-body-extraction.md

This rule is the agent-side analogue of
[`skill-body-extraction.md`](skill-body-extraction.md). The
mechanics, "what to extract" guidance, and reviewer checklist
mirror the skill version — the only differences are:

- Agents live as flat files in `agents/`, so references go to
  a sibling repo-root directory rather than under the agent
- The "always-keep-inline" set is shaped by sub-agent dispatch
  semantics rather than skill orchestration (no `TaskCreate` /
  `AskUserQuestion` calls — agents output reports, not workflows)
