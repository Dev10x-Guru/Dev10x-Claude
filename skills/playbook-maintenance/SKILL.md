---
name: Dev10x:playbook-maintenance
description: >
  Review user playbook overrides against current defaults to detect
  drift. Identifies new steps, improved prompts, updated fragments,
  and structural changes in defaults that overrides have missed.
  Presents findings with recommendations and delegates edits to
  Dev10x:playbook.
  TRIGGER when: user wants to check if their playbook overrides are
  up to date, after a plugin upgrade, or when defaults have changed.
  DO NOT TRIGGER when: user wants to view or edit a specific play
  (use Dev10x:playbook instead).
user-invocable: true
invocation-name: Dev10x:playbook-maintenance
allowed-tools:
  - Read
  - Glob
  - Grep
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
  - mcp__plugin_Dev10x_cli__mktmp
  - Skill(Dev10x:playbook)
---

# Dev10x:playbook-maintenance — Playbook Drift Detector

## Overview

When default playbooks are improved (new steps, better prompts, new
fragments), user overrides become stale. This skill detects that
drift and helps reconcile it.

It compares each user override against its corresponding default
play, produces a structured diff, and offers to apply selected
improvements via `Dev10x:playbook`.

## Orchestration

**REQUIRED: Create tasks before ANY work.** Execute at startup:

1. `TaskCreate(subject="Phase 1: Discover overrides", activeForm="Discovering overrides")`
2. `TaskCreate(subject="Phase 2: Analyze drift", activeForm="Analyzing drift")`
3. `TaskCreate(subject="Phase 3: Present findings", activeForm="Presenting findings")`
4. `TaskCreate(subject="Phase 4: Apply selected changes", activeForm="Applying changes")`

## Phase 1: Discover Overrides

Scan for all playbook-powered skills and their user overrides.

**Steps:**

1. Glob for default playbooks:
   `${CLAUDE_PLUGIN_ROOT}/skills/*/references/playbook.yaml`
2. Glob for user override files (all tiers per
   `references/config-resolution.md`):
   - `.claude/Dev10x/playbooks/*.yaml` (project-local)
   - `~/.config/Dev10x/playbooks/*.yaml` (global)
   - `~/.claude/memory/Dev10x/playbooks/*.yaml` (global legacy, backwards compat)
3. Match override files to default playbooks by filename
   (e.g., `work-on.yaml` matches `skills/work-on/references/playbook.yaml`)
4. Report skills with overrides vs. skills without

**Output:** A list of `(skill, default_path, override_path)` tuples
for skills that have user overrides. Skills without overrides are
skipped — they always use defaults and need no maintenance.

If no overrides are found, report "All skills use default playbooks
— nothing to maintain" and complete.

## Phase 2: Analyze Drift

For each skill with overrides, compare the override against the
current default. Create one subtask per skill being analyzed.

### Step 2a: Load and Parse

Read both the default playbook and the user override file. Parse
the YAML structure:
- `defaults.<play>.steps` — the current default steps
- `overrides[].steps` — the user's custom steps
- `fragments` — both default and user-defined fragments

### Step 2b: Compare Plays

For each play that has a user override, perform these comparisons:

**Step matching:** Match steps between default and override by
`subject` field (case-insensitive, trimmed). Steps are positional
but may be reordered, so match by subject first, then by position
for unmatched steps.

**Detect these drift categories:**

| Category | Detection | Severity |
|----------|-----------|----------|
| New default step | Subject exists in default but not in override | INFO |
| Removed default step | Subject exists in override but not in default | INFO |
| Prompt improvement | Same subject, different prompt text | LOW |
| Skills change | Same subject, different `skills` list | MEDIUM |
| Type change | Same subject, different `type` (detailed↔epic) | MEDIUM |
| New child steps | Same epic subject, default has more children | LOW |
| Fragment drift | Override uses a fragment that differs from default | MEDIUM |
| New fragment | Default defines a fragment not in override | INFO |

**Fragment-aware comparison:**

When a play references a fragment (e.g., `- fragment: shipping-pipeline`),
expand the fragment before comparing. If the user override file
defines a shadowing fragment (same name), compare the user fragment
against the default fragment step-by-step.

**Intentional divergence detection:**

Some differences are intentional (e.g., solo-maintainer removing
reviewer steps). Flag but do not treat as drift when:
- Override fragment has a different name than default fragment
  (e.g., `shipping-pipeline-solo` vs `shipping-pipeline`) — this
  is an intentional replacement, not missed drift
- Override has fewer steps AND a `prompt` explaining why
  (e.g., "solo maintainer, no reviewers")

### Step 2c: Produce Findings

For each play, collect all drift items into a structured list:

```
Skill: Dev10x:work-on
Play: feature
Findings:
  1. [INFO] New default step: "Draft Job Story" at position 2
     → Default added this step; your override skips it
  2. [LOW] Prompt improved: "Design implementation approach"
     → Default prompt is more detailed (added bounded-context guidance)
  3. [MEDIUM] Fragment drift: "shipping-pipeline" has 9 steps,
     your "shipping-pipeline-solo" has 8
     → Default added "Apply fixups to review comments" step
```

## Phase 3: Present Findings

Display all findings grouped by skill and play.

**Format:**

```markdown
## Playbook Drift Report

### Dev10x:work-on

#### feature (5 findings)
| # | Severity | Category | Step | Detail |
|---|----------|----------|------|--------|
| 1 | INFO | New step | Draft Job Story | Added in defaults at position 2 |
| 2 | LOW | Prompt | Design implementation | Default prompt expanded |
| 3 | MEDIUM | Fragment | shipping-pipeline | Default has 1 new step |

#### bugfix (2 findings)
...

### Dev10x:release-notes

#### release (1 finding)
...

---
Total: N findings across M plays (H high, M medium, L low, I info)
```

After presenting, offer action choices.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **Review and apply** (Recommended) — Walk through findings
  one by one, choose which to apply
- **Apply all non-INFO** — Auto-apply MEDIUM and LOW findings
- **Export report** — Save findings to a file for later review
- **Done** — No changes needed

## Phase 4: Apply Selected Changes

Based on the user's choice:

### Review and apply

For each finding (highest severity first):

1. Show the current override step vs. the default step
2. **REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
   Options:
   - **Apply** — Adopt the default's version
   - **Skip** — Keep the override as-is (intentional divergence)
   - **Customize** — Merge parts of both

3. If Apply or Customize: delegate to `Dev10x:playbook` to make
   the edit:
   ```
   Skill(skill="Dev10x:playbook", args="edit <skill> <play>")
   ```

4. After all findings are processed, show a summary of changes
   made vs. skipped.

### Apply all non-INFO

Batch-apply all MEDIUM and LOW findings automatically by
delegating to `Dev10x:playbook edit` for each affected play.
Show a summary when complete.

### Export report

Write the findings to a temporary file using the MCP mktmp tool
and report the path.

## Important Notes

- **Read-only by default** — this skill only reads playbooks and
  presents findings. All edits are delegated to `Dev10x:playbook`.
- **Fragment comparison is recursive** — if a fragment references
  another fragment (max depth 3), expand before comparing.
- **Override dates matter** — if an override's `added` date is
  older than the last plugin release, flag it as potentially stale.
- **No false positives on intentional divergence** — when the
  override uses a differently-named fragment or has explicit prompt
  text explaining the divergence, classify as INFO not MEDIUM.

## Examples

### Example 1: After plugin upgrade

**User:** `/Dev10x:playbook-maintenance`

Phase 1 finds 2 override files: `work-on.yaml`, `release-notes.yaml`

Phase 2 compares each. Finds that the default `shipping-pipeline`
fragment gained a new "Apply fixups" step that the solo override
`shipping-pipeline-solo` doesn't have.

Phase 3 presents:
```
### Dev10x:work-on
#### feature (1 finding)
| # | Severity | Category | Step | Detail |
|---|----------|----------|------|--------|
| 1 | MEDIUM | Fragment | shipping-pipeline-solo | Missing "Apply fixups to review comments" step (present in default shipping-pipeline) |
```

User chooses "Review and apply" → sees the new step → decides to
add it to their solo fragment.

### Example 2: No drift detected

**User:** `/Dev10x:playbook-maintenance`

Phase 1 finds overrides. Phase 2 compares — all overrides are
current with defaults (only intentional divergences detected).

Reports: "All overrides are up to date. 3 intentional divergences
detected (INFO level) — no action needed."

### Example 3: Specific skill check

**User:** `/Dev10x:playbook-maintenance work-on`

Runs only for the `work-on` skill overrides, skipping other skills.
Useful for quick checks after modifying a specific playbook.
