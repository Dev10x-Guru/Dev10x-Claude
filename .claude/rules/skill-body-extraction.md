# Skill Body Extraction Pattern

Reduce token consumption on skill invocation by moving reference
content out of SKILL.md into sibling files under `references/`.

## Why extract

When a skill is invoked via the `Skill` tool, its full SKILL.md
body is injected into the conversation as a user message. For
orchestration hubs (work-on at 1443 lines, skill-audit at 1109),
that cost hits every invocation regardless of which phase is
relevant.

Moving stable reference content into `references/*.md` files
means the agent reads only what a given step needs, instead of
loading the whole skill every time.

## What to extract

**Keep inline in SKILL.md** (always needed per invocation):
- YAML frontmatter (`name`, `description`, `allowed-tools`)
- Brief overview (≤20 lines)
- Orchestration contract: `TaskCreate` list, numbered phase/step
  outline, task dependencies
- Decision gates: `AskUserQuestion` call specs with **REQUIRED**
  markers
- Skill routing tables / mandatory delegation maps
- Critical guardrails and anti-patterns that gate execution

**Move to `references/`** (loaded on demand):
- Detailed step-by-step implementation guidance beyond the
  contract outline
- Examples (Example 1, 2, 3 … sections)
- Error-handling scenario tables
- Multi-page phase bodies (when a phase documents what a subagent
  should do, paste it into `references/phases.md` and load it
  only when dispatching)
- Domain reference material (toxicity categories, classification
  tables, detection algorithms)
- Strategy matrices used for adaptive behavior (e.g.,
  same-milestone heuristic, permission classification)

**Keep inline even when long** when the content gates execution —
e.g., `Skill Routing Enforcement` and `Plan Completion Gate`.
Moving those to references risks agents skipping guardrails.

## Extraction mechanics

1. Identify one or more cohesive sections to extract. Prefer
   sections that already have a clear heading (`## Examples`,
   `## Phase Reference`, `### Example Plays`).
2. Create `skills/<name>/references/<section-slug>.md`. Use a
   `.md` extension and a short slug (`examples.md`,
   `phases.md`, `example-plays.md`, `multi-issue-strategies.md`).
3. Promote the extracted section's internal headings one level
   up so the reference file reads as a standalone doc:
   - `### Example 1` inside SKILL.md becomes `## Example 1`
     inside `references/examples.md`.
4. In SKILL.md, replace the section body with a pointer:

   ```markdown
   ## Examples

   See [`references/examples.md`](references/examples.md) for
   walkthroughs covering single-ticket, multi-input, PR
   continuation, and mid-workflow pause scenarios.
   ```

5. When the extracted section contains subsections referenced by
   the workflow (e.g., "evidence-first rule" at the top of
   `## Example Plays`), keep that gating text inline in SKILL.md
   and move only the bulk of the examples.

## Shared references

Content referenced by more than one skill lives at the repo root
`references/` directory instead of the per-skill subdirectory.
Example: `references/task-orchestration.md` is a thin index and
the per-pattern files live at `references/orchestration/*.md`.

When a skill needs only one pattern (e.g., subagent dispatch),
link the pattern file directly rather than the index:

```markdown
See `references/orchestration/subagent-dispatch.md` for the
full dispatch pattern.
```

## Budget

- SKILL.md: soft cap 200 lines per `.claude/rules/INDEX.md`
- Orchestration hubs (work-on, skill-audit, fanout) may exceed
  the cap when the content is semantically cohesive and a split
  plan is documented — follow the `Budget Overrides` guidance
  in `INDEX.md`
- `references/*.md`: 200 lines per file. Split further when a
  reference itself grows beyond the cap (see
  `references/task-orchestration.md` → `references/orchestration/`)

## Subagent context budget

SessionStart-injected context (MOTD, SKILLS.md, plan-sync,
session guidance) appears in the orchestrator session, but
subagents dispatched via `Agent()` start with a fresh system
prompt. Treat this as a feature, not a bug:

- **Do NOT** rely on session context being available in
  subagents. Inline anything the subagent needs into its prompt.
- **Do NOT** instruct subagents to "follow the orchestration
  contract" — they don't see it. Re-state the relevant phase
  inline (see `references/orchestration/subagent-dispatch.md`
  Phase Reference pattern).
- **DO** mark sections of skill bodies that are session-only
  (e.g., MOTD, plan-sync greetings) so future SessionStart
  additions don't accidentally bloat subagent prompts. Use a
  `<!-- session-only -->` HTML comment marker in the source
  document so reviewers can spot it.

When the controller passes file content inline (per
`.claude/rules/model-selection.md` "Inline Context vs
Read-on-Demand"), wrap each file in a clearly-delimited block:

```
<file path="src/foo.py">
...full content...
</file>
```

This eliminates Read permission prompts in the subagent and
keeps the controller's pre-read cheap.

## Reviewer checklist

When reviewing a skill refactor that extracts content:

1. ✓ SKILL.md still contains frontmatter, orchestration contract,
   and decision gates with `REQUIRED: Call AskUserQuestion`
   markers
2. ✓ Each extracted section has a pointer in SKILL.md that names
   the reference path
3. ✓ Reference file headings are promoted one level (no lone
   `###` at the top of a reference doc)
4. ✓ No gating logic moved into references. Routing tables,
   completion gates, and anti-patterns that must be enforced on
   every run stay inline.
5. ✓ Allow-tools declarations are unchanged — extracting body
   content does not add or remove external tools.

## Current extraction state

| Skill | Original lines | Current SKILL.md | Reference files |
|-------|---------------:|-----------------:|-----------------|
| work-on | 1443 | 1188 | `example-plays.md`, `multi-issue-strategies.md`, `examples.md` |
| skill-audit | 1109 | 444 | `phases.md` |

Pending work (follow-up tickets): git-commit, gh-pr-monitor,
gh-pr-respond, fanout, git-groom, qa-self, scope,
git-commit-split, playbook, ticket-scope, gh-pr-merge,
gh-pr-create.

The shared `references/task-orchestration.md` was split into
`references/orchestration/*.md` with a thin index in this PR.
