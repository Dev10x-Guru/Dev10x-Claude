---
name: dev10x:permission-audit-apply
invocation-name: dev10x:permission-audit-apply
description: >
  Use when a permission-auditor report has landed and its proposed
  fixes need applying — so each accepted fix becomes one approved edit
  and nothing outside the approved scope rides along, instead of the
  user hand-editing settings files finding by finding.
  TRIGGER when: dev10x:plugin-maintenance step 10 (or
  dev10x:upgrade-cleanup) finished a permission audit, or the user
  asks to "apply the audit findings".
  DO NOT TRIGGER when: no auditor report exists yet (run the
  permission-auditor agent first), or the user wants a single rule
  changed by hand.
user-invocable: true
allowed-tools:
  - Bash(uvx dev10x permission findings:*)
  - Bash(dev10x permission findings:*)
  - Bash(jq empty:*)
  - mcp__plugin_dev10x_cli__mktmp
  - Read
  - Edit
  - Edit(/tmp/Dev10x/permission-audit/**)
  - AskUserQuestion
  - TaskCreate
  - TaskUpdate
---

# dev10x:permission-audit-apply

**Announce:** "Using dev10x:permission-audit-apply to apply the
auditor's findings one approved fix at a time."

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Apply permission-audit findings", activeForm="Applying audit findings")`

Mark completed when the summary report is shown:
`TaskUpdate(taskId, status="completed")`.

## Why

`permission-auditor` ends with a severity-labelled report, and nothing
consumed it — users edited each settings file by hand. During GH-965
that hand-edit pass bundled MEDIUM findings into a scope the user had
approved as CRITICAL+HIGH only. This skill makes the approved scope
mechanical: one gate per finding, one `Edit` per accepted fix, and a
severity ceiling for the unattended path (GH-1631).

## Arguments

- `<path>` (optional) — a JSON file holding the findings block. When
  omitted, use the last fenced `json` block of the most recent
  permission-auditor report in this session.
- `--severity-max=<LEVEL>` (optional) — unattended bulk apply of
  findings from CRITICAL down to `LEVEL` (`HIGH` applies CRITICAL and
  HIGH). Passing the flag is the supervisor's approval for exactly that
  set; findings below the ceiling are listed, never applied.

## Workflow

### Step 1: Load and validate the findings

1. When no `<path>` was given, allocate one with
   `mktmp(namespace="permission-audit", prefix="findings", ext=".json")`
   and Write the auditor's JSON block to it verbatim.
2. Validate and order it:

   ```bash
   uvx dev10x permission findings <path> [--severity-max <LEVEL>]
   ```

   stdout is one JSON object. `{"error": ...}` means the block does not
   match `references/agents/permission-auditor/finding-schema.md` —
   report the error and STOP; never apply a partly-parsed block. On
   success it holds `findings` (most severe first) and
   `excluded_by_severity` (ids under the ceiling).

### Step 2: Decide each finding

Iterate `findings` in order.

**Attended (no `--severity-max`) — REQUIRED: Call `AskUserQuestion`**
(do NOT use plain text) once per finding. Show severity, `file`,
`current_rule`, the proposed fix and `rationale`. Options:

- Apply (Recommended) — make this one edit
- Skip — leave this finding unapplied and continue
- Stop — apply nothing more; go to the summary

For an `action: "manual"` finding, the options are **Done by hand
(Recommended)** / **Skip** / **Stop** — the skill shows the `note` and
never edits for it.

A decline is final for this run: never re-ask a skipped finding, and
never fold it into a later "apply the rest" choice.

**Unattended (`--severity-max` given):** apply every mechanical finding
in `findings` without a gate; list `manual` findings and every id in
`excluded_by_severity` in the summary as not applied.

### Step 3: Apply one fix

1. `Read` the finding's `file` (expand `~`).
2. Check it applies — otherwise mark it **inapplicable** and continue:

   | Action | Applies when |
   |--------|--------------|
   | `add` | `rule` is absent from `permissions.<list>` |
   | `remove` | `rule` is present in `permissions.<list>` |
   | `replace` | `rule` is present and `replacement` is not yet in `permissions.<list>` |

3. Make exactly one `Edit` to the `permissions.<list>` array: insert
   the rule, delete its line, or swap it for `replacement`. Touch no
   other line — no reformatting, no reordering.
4. Validate: `jq empty <file>`. On failure, revert the edit with a
   second `Edit` and mark the finding **failed**.

### Step 4: Summary report

```
Permission audit — applied 3, skipped 1, inapplicable 1, manual 1
  ✓ F1 CRITICAL  add deny  Bash(gh repo delete:*)    ~/.claude/settings.json
  ✓ F3 HIGH      replace   Bash(rm:*) → Bash(rm /tmp/Dev10x/:*)
  – F4 MEDIUM    skipped by the user
  ∅ F5 MEDIUM    inapplicable: rule not present
  ✋ F6 LOW      manual: register hooks/validate-bash.py under PreToolUse
  ⏭ below ceiling (HIGH): F7, F8
```

Settings changes take effect in the **next** session; say so.

## Integration

- `dev10x:plugin-maintenance` step 10 dispatches the auditor and hands
  its findings block to this skill.
- Never runs the auditor itself — a fresh audit is the agent's job.

## Common Mistakes

| Mistake | Consequence |
|---|---|
| Applying all findings after one approval | MEDIUM fixes land in a CRITICAL+HIGH scope — the GH-965 over-reach |
| Re-serializing the whole settings file | A one-rule fix becomes a whole-file diff nobody can review |
| Applying a block that failed validation | The finding that failed to parse is silently dropped |
| Editing for a `manual` finding | Hook and path fixes are not list edits; a guessed edit breaks the file |
