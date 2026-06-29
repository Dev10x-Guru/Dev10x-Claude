---
name: Dev10x:verify-acc-dod
description: >
  Verify that definition-of-done / acceptance criteria are met before
  closing a task list. Loads executable checks from plugin defaults,
  applies project overrides (add/remove/replace), runs each check
  automatically, and prompts the user only for manual items.
  TRIGGER when: task list is complete and work needs shippability
  verification before handover.
  DO NOT TRIGGER when: mid-implementation, or task list has incomplete
  items.
user-invocable: true
invocation-name: Dev10x:verify-acc-dod
allowed-tools:
  - AskUserQuestion
  - Bash(gh:*)
  - Bash(git status:*)
  - Bash(git log:*)
  - Bash(git diff:*)
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__verify_pr_state
---

# Verify Acceptance Criteria / Definition of Done

**Announce:** "Verifying acceptance criteria for this work session."

## When to Use

- As the final step in any orchestrating skill's task list
  (work-on, fanout, gh-pr-monitor)
- When the user asks "is this done?" or "are we ready to ship?"
- Before closing a task list or handing off work

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Minimal).

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Verify acceptance criteria", activeForm="Verifying acceptance criteria")`

Mark completed when done.

## Friction Level Awareness

This skill adapts behavior based on the project's friction level
(see `references/friction-levels.md`):

| Level | Automated checks | Manual checks | Decision gate |
|-------|-----------------|---------------|---------------|
| strict | Run, must all pass | AskUserQuestion per item | AskUserQuestion required |
| guided | Run, failures shown | AskUserQuestion per item | AskUserQuestion with recommendation |
| adaptive | Run, auto-pass/fail | Converted to `prompt` (Claude evaluates) | Merge-gated (GH-729): auto-complete only when merged / PR-less; open PR → auto-start background monitor; any failure → Go back |

**Resolving friction level:** Read from session context or
playbook step metadata. If not available, default to `guided`.
Playbook steps may override with `friction_level: adaptive`
for unattended shipping pipelines.

## Input

The skill accepts an optional `work_type` argument. If not
provided, infer from session context:

| Context | Work type |
|---------|-----------|
| Ticket with implementation | `feature` |
| Sentry/bug ticket | `bugfix` |
| PR with review comments | `pr-continuation` |
| No ticket, no PR | `local-only` |
| Sentry/Slack only, no fix planned | `investigation` |
| Fanout (multi-item) | `fanout` |

## Criteria Resolution

Load criteria from two sources and merge them:

### Step 1: Load plugin defaults

Read executable checks from:
```
${CLAUDE_PLUGIN_ROOT}/skills/verify-acc-dod/references/defaults.yaml
```

Extract `defaults[work_type].checks` — an array of check objects.

### Step 2: Load repo overrides (if present)

Read overrides from a single global file:
```
~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml
```

This file maps repositories to their override deltas:

```yaml
repos:
  example-org/app-pos:
    bugfix:
      add:
        - name: Sentry issue linked
          check: >
            gh pr view {pr_number} --repo {repo}
            --json body -q .body  # cli-friction: allow raw-gh-pr
          expect_contains: "sentry.io"
      remove:
        - Slack notification posted
  Dev10x-Guru/dev10x-claude:
    feature:
      remove:
        - Review requested
      add:
        - name: PR ready (solo maintainer)
          check: >
            gh pr view {pr_number} --repo {repo}
            --json isDraft -q .isDraft  # cli-friction: allow raw-gh-pr
          expect: "false"
```

**Repo detection:** Resolve the current repo via `gh repo view
--json nameWithOwner -q .nameWithOwner` or session context.
Look up `repos[nameWithOwner][work_type]` for deltas.

### Step 3: Merge with delta semantics

Apply the repo-scoped deltas from the global file to the
plugin defaults:

**`add`** — append checks to the defaults list.
**`remove`** — remove checks by `name` (exact match).
**`replace`** — replace a check by `name` with the new definition.

Apply in order: remove first, then replace, then add. This
prevents removing a just-added check or replacing a removed one.

### Step 4: Filter by active modes

Read `active_modes` from `.claude/Dev10x/session.yaml`. For each
check with a `modes:` field, check if any active mode has
`skip: true`. If so, remove the check from the list and report
it as "skipped (mode: <mode-name>)".

### Resolution order (summary)

1. Load plugin defaults for `work_type`
2. If global file exists and has overrides for current repo +
   `work_type`: apply remove → replace → add
3. If global file is absent: use plugin defaults as-is
4. If `work_type` has no entry in defaults: use empty checks list
   and warn
5. Filter by active modes (skip checks marked for active modes)

## Executing Checks

### Placeholder resolution

Before running each check command, resolve placeholders:

| Placeholder | Source |
|-------------|--------|
| `{pr_number}` | Current PR number (from `mcp__plugin_Dev10x_cli__pr_detect(arg="")` → `PR_NUMBER`, or session context) |
| `{repo}` | Current repo (from `gh repo view --json nameWithOwner -q .nameWithOwner` or session context) |

If no PR exists (e.g., `local-only`), skip checks that reference
`{pr_number}` and mark them as "skipped (no PR)".

### Run each check

For each check in the merged list:

1. **If `check: manual`** — queue for user confirmation (see
   Manual Checks below)
2. **If `check: prompt`** — evaluate the `prompt` contextually
   from the current session (code state, conversation history,
   tool outputs). Report pass/fail with a brief rationale.
   Use this for criteria that require judgment but not user
   interaction (e.g., "Does the PR description contain a Job
   Story?").
3. **Otherwise** — run the command via Bash and evaluate:

| Field | Evaluation |
|-------|-----------|
| `expect` | Trim command output; pass if exactly equals the value |
| `expect_contains` | Pass if output contains the substring |
| `expect_not_contains` | Pass if output does NOT contain the substring |
| `expect_gt` | Parse output as number; pass if > value |

If none of the expect fields match the output, the check **fails**.
Capture the actual output for the failure report.

### Manual checks

**At strict/guided level:**

Collect all `check: manual` items and present them in a single
`AskUserQuestion` call after all automated checks complete:

**REQUIRED: Call `AskUserQuestion`** for manual checks (do NOT
assume pass/fail).

Present each manual check as a yes/no confirmation using its
`prompt` field.

**At adaptive level:**

Convert `manual` checks to `prompt` checks — Claude evaluates
each from session context (code state, conversation history,
tool outputs). Report pass/fail with a brief rationale. No
`AskUserQuestion` call. This enables fully unattended ACC
verification in AFK/solo-maintainer workflows.

## Presentation

Present results as a pass/fail table:

```
Acceptance criteria (feature):

Checks:
  ✅ Working copy clean
  ✅ CI passing
  ✅ PR not draft
  ✅ No fixup commits
  ❌ Review requested — actual: "0" (expected > 0)
  ⏭️  Slack posted (skipped — no PR)
  ✋ Findings documented — awaiting confirmation

4/5 automated checks passed. 1 manual check pending.
```

Show the actual command output on failure so the user can
diagnose without re-running.

## PR Merge State (GH-729)

Completion is reserved for the **merged** state — "shippable / handed
off" is **not** terminal. Before resolving the gate, determine the PR
state and feed it in as a gate input:

1. Resolve the associated PR via
   `mcp__plugin_Dev10x_cli__pr_detect(arg="")`. An `error` / no-PR
   response means **PR-less** (e.g. `investigation` / `local-only`).
2. When a PR exists, read its merge state via
   `mcp__plugin_Dev10x_cli__verify_pr_state` (or the PR's `mergedAt`
   field) — merged vs open.

This merge signal is a **gate input, not a pass/fail check.** Do NOT
add it to the automated checks list: an unmerged-but-otherwise-green
PR is the normal *awaiting-review* state, and a failing "PR merged"
check would auto-route to "Go back" forever (you cannot merge without
review). Instead it selects the recommended option below.

The three-way recommendation is encoded once in
`dev10x.domain.session_rules.completion_gate_recommendation()` — this
skill's prose and `work-on`'s Plan Completion Gate defer to it rather
than re-deriving the matrix:

| PR state | Blocking checks | Recommended | Auto (adaptive) |
|----------|-----------------|-------------|-----------------|
| Merged / no PR | pass | **Work complete** | auto-complete |
| Open, awaiting review | pass | **Monitor for review** (→ `Dev10x:gh-pr-monitor`, ~5 min) | auto-start monitor (background) |
| Any | fail / pending | **Go back** | Go back |

"Blocking checks" are the automated/manual criteria above (CI, draft
state, unresolved threads, clean tree). The merge signal is excluded.

## Decision Gate

Resolve the recommendation from PR merge state + blocking-check
results (see the table above). **Never** offer or auto-select "Work
complete" while an associated PR is open/unmerged.

**At strict/guided level:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). The
options depend on the resolved recommendation:

*Recommendation **Work complete*** (merged or PR-less, all checks pass):
- **"Work complete" (Recommended)** — All criteria met, close the
  task list
- **"Go back"** — Re-examine a completed step

*Recommendation **Monitor for review*** (open PR, otherwise green):
- **"Monitor for review" (Recommended)** — Keep the session open;
  dispatch `Dev10x:gh-pr-monitor` to background-watch the PR every
  ~5 min and surface review comments / ready-to-merge
- **"Keep open (manual)"** — Leave the session open, no auto-monitor
- **"Override — complete anyway"** — Accept the unmerged PR as done
  (ask whether to persist)

*Recommendation **Go back*** (a blocking check failed):
- **"Go back" (Recommended)** — Return to fix the failing checks
- **"Override — complete anyway"** — Accept despite failures (ask
  whether to persist)

**At adaptive level (GH-851 F4, GH-729):**

Skip `AskUserQuestion`. Auto-select on the same recommendation:
- **Work complete** (merged / PR-less, all checks pass) →
  auto-complete
- **Monitor for review** (open PR, otherwise green) → dispatch
  `Skill(Dev10x:gh-pr-monitor)` in the background and keep the
  session open. The residual terminal task becomes **"Monitor PR
  #<N> for review / merge"** — do NOT auto-complete.
- **Go back** (any check fails/pending) → report failures to the
  parent orchestrator for resolution
- No user interruption in any case
- **No "non-blocking" exception category exists.** Every check in
  pending or fail state triggers "Go back". An open PR is **not** a
  failed check — it routes to monitor, never to auto-complete.

If the user picks "Override", ask whether to persist:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **"Always"** — Save override with `persist: true`
- **"Just this time"** — Save with `persist: false`

Update the global YAML file at
`~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml` accordingly.
Create the file if absent. Add the override under the current
repo's key using add/remove/replace semantics.

## Session Close vs Task Completion (GH-681)

A green run of this skill is a **precondition** for closing the
session — it is **not** the supervisor sign-off itself. The terminal
"Verify acceptance criteria" task is closed only when the supervisor
explicitly chooses "Work complete" (or runs `Dev10x:session-wrap-up`).
"Checks pass" ≠ "supervisor confirmed session done": a draft/open PR
with a pending human review can satisfy every automated check while the
session is still live. The Decision Gate makes this concrete (GH-729):
while the PR is open/unmerged, the recommended action is **Monitor for
review** (→ `Dev10x:gh-pr-monitor`), never "Work complete".

The empty-task-list guard (`hooks/scripts/task-guard.py`, GH-149)
enforces this: it **refuses** a `TaskUpdate` that marks the terminal
Verify-AC task — or the last remaining open task — `completed`/`deleted`
in a `Dev10x:work-on` session. When the supervisor has confirmed
completion, close the task with the deliberate marker so the guard
allows it:

```
TaskUpdate(taskId=<verify-ac-id>, status="completed",
           metadata={"supervisor_confirmed": true})
```

At adaptive level, "all checks pass → auto-complete" still routes
through this marker — auto-completion is not a licence to empty the
list without the explicit sign-off step.

**Post-completion re-open.** If new supervisor instructions arrive
after Verify-AC was closed, create a fresh "Verify acceptance criteria"
task **before** starting the new work, so the task list never sits
empty mid-session.

## Integration

```
Dev10x:work-on → ... → Dev10x:verify-acc-dod (last step)
Dev10x:fanout  → ... → Dev10x:verify-acc-dod (last step)
```

Callers pass the work type and let this skill handle criteria
resolution, state checking, and user confirmation.
