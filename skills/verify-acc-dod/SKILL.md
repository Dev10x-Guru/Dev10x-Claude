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
  - mcp__plugin_Dev10x_cli__supervisor_review_status
  - mcp__plugin_Dev10x_cli__resolve_gate
  - mcp__plugin_Dev10x_cli__detect_base_branch
  - Read(~/.config/Dev10x/dod-acceptance-criteria.yaml)
  # Read-only grant on the GH-941-retired path so Step 2's one-release
  # fallback does not prompt. Deliberately no Edit grant here — writes
  # go to ~/.config/Dev10x/ only (GH-1035).
  - Read(~/.claude/memory/Dev10x/dod-acceptance-criteria.yaml)
  - Edit(~/.config/Dev10x/dod-acceptance-criteria.yaml)
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

## One Baseline (GH-1172)

There is a single verification behaviour, on every project:

| Automated checks | Manual checks | Completion gate |
|------------------|---------------|-----------------|
| Run, auto-pass/fail | Converted to `prompt` (Claude evaluates) | Merge-gated (GH-729) |

This skill takes no friction-level input and keeps no per-level
table — the key was retired for this layer by GH-1172. Which
checks run, how a `manual` item is decided, and which completion
option is recommended are the same everywhere. A playbook step cannot
dial this layer up or down.

### Boundary with `resolve_gate` (ADR-0016)

Two separate decisions. Neither overrides the other, and collapsing
them is a defect:

- **The resolver decides whether the gate FIRES.** Call
  `mcp__plugin_Dev10x_cli__resolve_gate(gate="completion_signoff")` and
  read `effect` — `ask` presents the widget, `auto-advance` takes the
  recommendation without interrupting, `skip` records it silently.
- **This skill decides what the gate RECOMMENDS.** The three-way
  Merged / Open-awaiting-review / failing recommendation comes from PR
  merge state plus blocking-check results (see PR Merge State below),
  whatever the resolver chose.

So an `auto-advance` still advances to the recommendation computed
here, and a **Go back** recommendation stays **Go back** whether it is
shown as a widget or taken automatically. The resolver never turns a
failing run into a passing one.

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

### Steps 1b–3: Re-inference, repo overrides, delta merge

See [`references/criteria-resolution.md`](references/criteria-resolution.md)
for the full procedure:

- **Step 1b — live-state re-inference (GH-780).** When an open PR
  exists but the caller passed a PR-less `work_type`
  (`local-only` / `investigation`), union `defaults.feature.checks`
  into the list, deduped by `name`. Union, never replacement; never
  downgrade a `work_type` that already carries PR checks.
- **Step 2 — repo overrides.** Read
  `~/.config/Dev10x/dod-acceptance-criteria.yaml` (with a one-release
  read-compat fallback to the retired memory path, announced when it
  fires). Never *write* to the legacy path.
- **Step 3 — delta merge.** Apply the repo's deltas in the order
  remove → replace → add, so a just-added check cannot be removed and
  a removed one cannot be replaced.

### Step 4: Filter by review posture and active modes

Resolve both inputs from the DURABLE gate policy — global
`~/.config/Dev10x/friction.yaml` (first matching `projects[]` entry),
falling back to legacy `.claude/Dev10x/config.yaml`. Do NOT read the
retired ephemeral `.claude/Dev10x/session.yaml`, which no longer
carries durable prefs (ADR-0018, GH-854 F3).

**4a. Review posture — `supervisor_review` (ADR-0022 D-2, superseding
ADR-0019's `human_review`).** Read it via
`mcp__plugin_Dev10x_cli__supervisor_review_status()`; absent or
malformed reads as `required`. Do NOT read the durable file directly —
the tool owns the precedence. When it is `none`, drop every check
declaring `requires_human_review: true` and report each as
`skipped (supervisor_review: none)`.

Which checks those are is declared in the **data**, not here — see the
`requires_human_review` field in
[`references/defaults.yaml`](references/defaults.yaml) (today: the
unresolved-threads and review-requested/re-review pairs), so a project
override can adjust the set without editing this skill.

With them out of scope, a green run honestly recommends Work complete /
Monitor instead of papering over a failing thread check (GH-736). When
`supervisor_review` is `required`, those checks run — an open thread is
a real failing blocking check and the recommendation is **Go back**.

This replaces the ephemeral `review-deferred` write, which targeted the
retired `session.yaml` and so was never read back in a configured repo.
There is no per-session deferral: the posture is a durable project fact.

**4b. Active modes.** Resolve `active_modes` from the same durable
prefs. For each check with a `modes:` field, if any active mode has
`skip: true`, remove the check and report it as "skipped (mode:
<mode-name>)". `solo-maintainer` skips only the review-request check
(thread resolution is still expected). `review-deferred` is
**deprecated** in favour of `supervisor_review` — its `skip` clauses
are still honored for back-compat when a playbook or legacy
`active_modes` names it, but nothing writes it anymore. See
[`references/active-modes.md`](../../references/active-modes.md).

### Resolution order (summary)

1. Load plugin defaults for `work_type`
2. Re-infer from live state (GH-780): if an open PR exists and
   `work_type` is PR-less (`local-only`/`investigation`), union in
   `defaults.feature.checks` (dedupe by `name`); never downgrade a
   PR-carrying `work_type`
3. If global file exists and has overrides for current repo +
   `work_type`: apply remove → replace → add
4. If global file is absent: use plugin defaults as-is
5. If `work_type` has no entry in defaults: use empty checks list
   and warn
6. Filter by review posture (`supervisor_review: none` drops every
   `requires_human_review` check) and then by active modes

## Executing Checks

### Placeholder resolution

Before running each check command, resolve placeholders:

| Placeholder | Source |
|-------------|--------|
| `{pr_number}` | Current PR number (from `mcp__plugin_Dev10x_cli__pr_detect(arg="")` → `PR_NUMBER`, or session context) |
| `{repo}` | Current repo (from `gh repo view --json nameWithOwner -q .nameWithOwner` or session context) |
| `{base_branch}` | PR base branch from `mcp__plugin_Dev10x_cli__detect_base_branch` (`develop`→`main` fallback) — never hardcode `develop` (GH-854 F2) |

If no PR exists (e.g., `local-only`), skip checks that reference
`{pr_number}` and mark them as "skipped (no PR)".

### Run each check

For each check in the merged list:

1. **If `check: manual`** — treat it as a `prompt` check and evaluate
   its `prompt` contextually (see Manual Checks below)
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

Every `check: manual` item is converted to a `prompt` check. Claude
evaluates it from session context (code state, conversation history,
tool outputs) and reports pass/fail with a brief rationale. There is
no per-item `AskUserQuestion`: a manual item is a judgement call, and
the judgement is made the same way on every project.

`manual` stays in the schema as the **authoring** form for a
judgement-shaped criterion — project overrides written against it keep
working, and the conversion happens at run time. A converted check
that Claude cannot decide from context **fails**; it does not pass by
default, and it does not escalate to a prompt.

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
  ✅ Findings documented — release notes list both fixes (judged)

5/6 checks passed.
```

Mark a judged (`prompt`, or `manual` converted to `prompt`) check with
its rationale so the reader can tell a judgement from a command
result.

Show the actual command output on failure so the user can
diagnose without re-running.

When Step 1b added checks, name them so the reduced-coverage risk
is visible rather than silent:

```
+ 5 checks added by live-state re-inference (open PR #42 present;
  caller work_type was 'local-only'): CI passing, PR not draft,
  No fixup commits, No unresolved review threads, Review requested
```

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

| PR state | Blocking checks | Recommended | On auto-advance |
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

Then ask the resolver how to PRESENT it — this skill never decides
that for itself. Call
`mcp__plugin_Dev10x_cli__resolve_gate(gate="completion_signoff")` and
branch on `effect`.

### `effect: ask`

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text). The
resolved recommendation is always the first, Recommended option:

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

### `effect: auto-advance` (GH-851 F4, GH-729)

Skip `AskUserQuestion` and take the **same** recommendation without
interruption. Print the resolver's `record` line so the choice stays
visible:
- **Work complete** (merged / PR-less, all checks pass) →
  auto-complete
- **Monitor for review** (open PR, otherwise green) → dispatch
  `Skill(Dev10x:gh-pr-monitor)` in the background and keep the
  session open. The residual terminal task becomes **"Monitor PR
  #<N> for review / merge"** — do NOT auto-complete.
- **Go back** (any check fails/pending) → report failures to the
  parent orchestrator for resolution

### `effect: skip`

Record the recommendation and continue without prompting. A **Go
back** recommendation is still reported to the parent orchestrator —
`skip` suppresses the *prompt*, never the verdict.

**No "non-blocking" exception category exists**, under any effect.
Every check in pending or fail state resolves to "Go back". An open PR
is **not** a failed check — it routes to monitor, never to
auto-complete.

If the user picks "Override" (reachable only under `ask`), ask whether
to persist:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- **"Always"** — Save override with `persist: true`
- **"Just this time"** — Save with `persist: false`

Update the global YAML file at
`~/.config/Dev10x/dod-acceptance-criteria.yaml` accordingly.
Create the file if absent. Add the override under the current
repo's key using add/remove/replace semantics.

**Writes always target `~/.config/Dev10x/`** — never the legacy
memory path, even when Step 2's read-compat fallback supplied the
criteria this run. Writing back to the retired location is the
re-creation loop GH-925 E1 described: `dev10x config migrate` folds
the legacy file forward, and the next skill run recreates it.

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

Under `auto-advance`, "all checks pass → auto-complete" still routes
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
