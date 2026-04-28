# Dev10x:fanout — Parallel Work Stream Orchestrator (Instructions)

**Announce:** "Using Dev10x:fanout to process [N] work items
in parallel."

## Overview

This skill processes multiple independent work items
concurrently, honoring dependency order and minimizing merge
conflict risk. It is the multi-item counterpart to
`Dev10x:work-on` (which handles a single work item).

**When to use fanout vs work-on:**
- **work-on**: Single ticket, PR, or investigation. Also
  handles multiple issues bundled into one PR with atomic
  commits (user requests "one PR" or "bundle these").
- **fanout**: Multiple PRs to merge, multiple issues to
  implement as separate PRs, or a mix of both

**Default mode:** Fully autonomous with auto-advancement.
No confirmation gates between items unless a genuine
dependency or conflict is detected.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each item, immediately start the
next. Never pause between items to ask "should I continue?"

**REQUIRED: Create tasks before ANY work.** Execute
`TaskCreate` calls at startup — one per phase:

1. `TaskCreate(subject="Scan: discover work items", activeForm="Scanning")`
2. `TaskCreate(subject="Classify: dependency and conflict analysis", activeForm="Classifying")`
3. `TaskCreate(subject="Execute: process work streams", activeForm="Processing")`
4. `TaskCreate(subject="Monitor: track PRs through merge", activeForm="Monitoring")`
5. `TaskCreate(subject="Verify: confirm all items resolved", activeForm="Verifying")`
6. `TaskCreate(subject="Audit: review session skill usage", activeForm="Auditing")`

## Phase 0: Session Friction Level (GH-689)

**At the very start** — before Phase 1 — prompt the user to set
the session friction level. This controls how aggressively the
skill auto-advances vs pauses for confirmation.

**Skip this prompt when:**
- Session config already exists at `.claude/Dev10x/session.yaml`
  (loaded after compaction or from a prior invocation)

**REQUIRED: Call `AskUserQuestion`** (ALWAYS_ASK — fires at all
friction levels, including adaptive).

Options:
- Guided (Recommended) — Gates fire with recommendations,
  user can override. Default for attended sessions.
- Adaptive (AFK) — Auto-select recommended options at all
  gates. No `AskUserQuestion` interruptions except
  `ALWAYS_ASK` gates. Best for walk-away sessions.
- Strict — All gates fire, no auto-selection. Every
  decision requires explicit user input.

**Persist the choice** to `.claude/Dev10x/session.yaml`:

```yaml
friction_level: guided  # strict | guided | adaptive
```

Write this file using the Write tool. The PreCompact hook
reads it to inject friction context into recovery summaries.

When `adaptive` is selected, propagate to all `Dev10x:work-on`
delegations — nested work-on invocations skip their own
Phase 0 prompt and inherit the fanout session level.

## Phase 1: Scan

Discover all open work items in the current repo or
specified scope.

**Default scan** (no arguments): Fetch both open PRs and
open issues:
```
gh pr list --state open --json number,title,headRefName,isDraft,mergeable
gh issue list --state open --json number,title,labels
```

**Issue fetching:** Use MCP `mcp__plugin_Dev10x_cli__issue_get`
as the primary tool for fetching individual issue details. Fall
back to `gh issue view` only when the MCP tool is unavailable.
MCP calls avoid permission friction and provide structured
responses.

**With arguments**: Accept a space-separated list of URLs,
issue numbers, or PR numbers. Classify each argument
independently:

| Pattern | Type | Action |
|---------|------|--------|
| `https://github.com/{owner}/{repo}/issues` | `scope:issues` | Restrict scan to issues only |
| `https://github.com/{owner}/{repo}/pulls` | `scope:pulls` | Restrict scan to PRs only |
| `https://github.com/{owner}/{repo}/milestone/{N}` | `scope:milestone` | Fetch milestone title, list issues |
| `https://github.com/{owner}/{repo}/issues/{N}` | `item:issue` | Fetch specific issue |
| `https://github.com/{owner}/{repo}/pull/{N}` | `item:pr` | Fetch specific PR |
| `#N` or bare number | `item` | Classify per `Dev10x:work-on` Phase 1 rules |
| `PRs`, `issues` (bare keyword) | `scope` | Restrict scan to matching type (same as scope URL) |
| Free text (anything else) | `note` | Parse intent to infer scope and work items (see below) |

**Free-text input:** When an argument doesn't match any URL,
number, or keyword pattern, treat it as a `note`. Analyze the
text to infer the user's intent:

- Identify scope hints (e.g., "merge all open PRs" → `scope:pulls`,
  "triage the bug reports" → `scope:issues`)
- Extract implicit item references (e.g., "fix the timeout bug
  from last week" → search recent issues)
- Determine parallelism intent (e.g., "split this into parallel
  tasks" → plan parallel processing)

Classification follows `Dev10x:work-on` Phase 1 `note` handling.
When scope cannot be inferred, default to scanning both PRs and
issues.

**Scope keywords and URLs** constrain the default scan.
When a scope URL is present, run only the matching `gh` command
instead of both:

- `scope:issues` → run `gh issue list` only, skip `gh pr list`
- `scope:pulls` → run `gh pr list` only, skip `gh issue list`

Scope URLs and specific items can be mixed. When both are
present, the scope restricts the default scan while specific
items are fetched regardless of scope:

```
/Dev10x:fanout https://github.com/org/repo/issues #42
```
→ Scan issues only (`gh issue list`) + fetch PR #42 explicitly.

Create one subtask per discovered item under the Phase 1
parent task.

## Phase 2: Classify

For each work item, determine:

1. **Type**: PR-continuation, feature, bugfix, investigation
2. **Files touched**: Read the PR diff or issue description
   to identify affected files/directories
3. **Dependency edges**: If item A's target files overlap
   with item B's, they conflict — order matters
4. **Priority**: PRs before issues (PRs are closer to done).
   Within PRs: ready-to-merge first, then draft with CI
   passing, then draft needing work.

### Conflict Analysis

Build a conflict graph:

```
For each pair (A, B):
  if files_touched(A) ∩ files_touched(B) ≠ ∅:
    mark A ↔ B as conflicting
```

**Conflicting items** must run sequentially — the first to
merge wins, and later items rebase before continuing.

**Non-conflicting items** can run in parallel.

### Execution Order

1. **PRs ready to merge** — mark ready, monitor CI, merge
2. **PRs needing fixes** — fix review comments, rebase,
   push, monitor, merge
3. **Issues with no conflicts** — implement in parallel
   worktrees
4. **Issues with conflicts** — implement sequentially in
   dependency order

Present the execution plan as a numbered list showing
parallel groups and sequential chains:

```
Parallel group 1: PR #42 (ready), PR #55 (needs fixes)
Sequential chain: Issue #10 → Issue #15 (shared files)
Parallel group 2: Issue #20, Issue #25 (independent)
```

### Supervisor Gate

**Implicit approval bypass:** If the user's original input
contains explicit ordering or parallelism instructions,
skip the approval gate and proceed.

Otherwise:

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Approve plan (Recommended) — Start execution
- Edit — Describe changes to ordering or grouping

## Phase 3: Execute

Process items according to the approved plan.

**REQUIRED: Create one subtask per work item** under the Phase 3
parent task before starting any execution. Each subtask tracks
the lifecycle of a single issue or PR:

```
TaskCreate(subject="Process: PR #42 — fix payment routing",
    parentTaskId=phase3TaskId,
    metadata={"type": "pr-continuation", "item": "#42"})
TaskCreate(subject="Process: GH-10 — add retry mechanism",
    parentTaskId=phase3TaskId,
    metadata={"type": "feature", "item": "GH-10"})
```

Mark each subtask `in_progress` when starting and `completed`
when the item's PR is merged or work is handed off.

### Pre-Item Self-Check (REQUIRED)

Before processing **each** work item, execute this two-step gate:

1. **Branch verification:** Run `git symbolic-ref --short HEAD`
   and confirm the current branch matches the expected item.
   If it does not, create or switch to the correct branch
   before proceeding. This prevents commits landing on the
   wrong branch when processing items sequentially.
   **NEVER use raw `git checkout -b`** — always delegate to
   `Skill(skill="Dev10x:ticket-branch")` for branch creation.
   Raw checkout bypasses naming conventions, worktree detection,
   and base-branch validation.

2. **Delegation check:** STOP and ask yourself: "Am I about to
   implement this item directly?" If yes, invoke
   `Skill(skill="Dev10x:work-on", args="<item-url>")` instead.
   Fanout is an **orchestrator**, not an implementor.

Skipping either step causes cascading errors — wrong-branch
commits require destructive `git reset --hard` cleanup, and
inline implementation bypasses work-on's structured lifecycle
(branch setup, code review, shipping pipeline).

### Post-Item Delegation Verification (REQUIRED)

After completing **each** work item, verify that
`Skill(Dev10x:work-on)` was invoked for that item. If not,
this is a compliance violation — do NOT proceed to the next
item. The same rule applies to merge operations: each PR
MUST use `Skill(Dev10x:gh-pr-merge)`, never raw `gh pr merge`.

**Post-item comment check (GH-829):** After each item's PR is
merged, call `mcp__plugin_Dev10x_cli__pr_comments(pr_number=N)`
and verify zero unaddressed comments. If comments exist, invoke
`Skill(skill="Dev10x:gh-pr-respond", args="{pr_url}")` before advancing
to the next item. This catches unaddressed comments early —
agents degrade after item 3+ and skip per-item acceptance
criteria under auto-advance pressure. The Phase 5 enforcement
loop is a safety net; this per-item check is the primary gate.

Fanout agents degrade after the first 1–2 items, falling back
to inline implementation and raw CLI commands for the rest of
the batch. This check catches the drift before it cascades.

### Permission-Aware Dispatch

Classify each work item before dispatch to avoid Write/Edit
failures in background agents:

| Task type | Needs Write/Edit? | Dispatch method |
|-----------|-------------------|----------------|
| Issue implementation | Yes | Main session via `Skill()` |
| PR with code fixes needed | Yes | Main session via `Skill()` |
| PR ready to merge (CI green, no comments) | No | Background `Agent()` OK |
| CI monitoring only | No | Background `Agent()` OK |
| Investigation / research | No | Background `Agent()` OK |

**Decision rule:** If the task MAY require creating or editing
files (implementation, fixups, conflict resolution), it MUST
run in the main session via `Skill()`. Background agents are
only safe for read-only operations (monitoring, fetching,
reviewing without fixes).

**Pre-dispatch check:** Before dispatching a background agent,
verify the item does NOT need Write/Edit by checking:
1. PR has no unaddressed review comments requiring code changes
2. PR CI is passing (no fixup commits needed)
3. PR has no merge conflicts (no rebase needed)

If any check fails → route to main session instead.

### Work-On Delegation

**REQUIRED: Every issue MUST be delegated to `Dev10x:work-on`.**
Do NOT implement issues inline within the fanout session. Fanout
dispatches work to `Dev10x:work-on` and tracks results. Inline
implementation bypasses work-on's structured lifecycle (branch
setup, Job Story, code review, shipping pipeline) and produces
untracked work.

**Enforcement:**
- Each issue → `Skill(skill="Dev10x:work-on", args="<issue-url>")`
- Each PR → `Skill(skill="Dev10x:work-on", args="<pr-url>")`
- After work-on completes → invoke `Dev10x:gh-pr-monitor` to
  track the resulting PR through CI and merge

### Processing PRs

For each PR, delegate to `Dev10x:work-on` with the PR URL.
Work-on executes the pr-continuation play:

1. Check out the PR branch (or work in existing worktree)
2. If review comments exist → `Dev10x:gh-pr-respond`
3. If conflicts with develop → rebase and resolve
4. `Dev10x:git-groom` to clean commit history
5. Mark ready via `gh pr ready`
6. Monitor CI — fix failures with fixup commits

**Fixup race condition guard (GH-724):** Before creating any
fixup commit for a PR that is also being monitored in Phase 4,
verify the PR is still open via
`mcp__plugin_Dev10x_cli__pr_detect(arg="<pr-number>")` and check
the returned `state` field. If the result is not `OPEN`, the PR
was merged by the monitor
while you were preparing the fix. Do NOT push the fixup commit
to the dead branch — create a follow-up branch from develop
and open a new PR instead.

7. **Pre-merge gate (REQUIRED):** Before merging, verify ALL:
   - CI checks pass (`gh pr checks`)
   - No unaddressed review comments
     (`mcp__plugin_Dev10x_cli__pr_comments` or
     `gh api repos/{owner}/{repo}/pulls/{N}/comments`)
   - PR is marked ready (not draft)
   - Working copy is clean
   Do NOT merge via raw `gh pr merge` — delegate to
   `Skill(Dev10x:gh-pr-merge)` which validates all 7
   pre-merge conditions. Raw merge bypasses review comment
   checks (GH-549 F-05).
8. After merge → rebase any downstream items that
   depend on this PR's changes

**Draft → Ready cycle:** PRs that revert to draft after
CI review posts comments need immediate `gh pr ready`
followed by merge attempt. Do not wait for another CI
cycle if the review is informational only.

### Processing Issues

For each issue (or parallel group of issues):

1. Create a worktree or branch per issue
2. **REQUIRED:** Delegate to `Dev10x:work-on` with the issue URL
3. After work-on completes → invoke `Dev10x:gh-pr-monitor`
   to track the resulting PR through CI and merge
4. After merge → update develop, rebase downstream items

**Parallel execution:** Background `Agent()` subagents
**cannot invoke `Skill()`** — the Skill tool is only
available in the main session. This means background agents
bypass the full `Dev10x:work-on` lifecycle (branch setup,
code review, shipping pipeline, CI monitoring).

**REQUIRED: Use Permission-Aware Dispatch (see above).**
Issues always need Write/Edit → process sequentially via
`Skill()` in the main session:

```
Skill(skill="Dev10x:work-on", args="<issue-url>")
```

Background `Agent()` dispatch is only permitted for
read-only operations per the Permission-Aware Dispatch
table. For write-requiring work, background agents fail
on Write/Edit due to permission non-propagation (GH-549,
GH-555).

### Post-Merge Rebase

After merging any item, check if downstream items in the
same sequential chain are affected:

1. Fetch the base via `mcp__plugin_Dev10x_cli__detect_base_branch`
   to determine the merge target.
2. For each active branch in the chain, delegate the rebase to
   `Skill(Dev10x:git-groom)` — it rebases onto the resolved base
   and force-pushes through `Skill(Dev10x:git)` (protected-branch
   safety). Never invoke `git rebase origin/<base>` directly from
   this skill — see Skill Routing Enforcement in
   `skills/work-on/instructions.md`.
3. If rebase conflicts → resolve, commit, then re-invoke
   `Skill(Dev10x:git-groom)` to complete the force-push.
4. If rebase succeeds → continue processing.

### Merge Mode (GH-688)

Controls whether PRs are merged autonomously after CI passes.

| Mode | Behavior |
|------|----------|
| `manual` | Mark ready, stop. User merges explicitly. |
| `autonomous` | After CI green + no comments → invoke `Dev10x:gh-pr-merge` |
| `cascade` | Autonomous + auto-rebase downstream PRs in the same fanout chain |

**Resolution order** (first match wins):
1. **Session friction level:** If `adaptive` (AFK mode from
   Phase 0), default to `cascade`
2. **Playbook override:** `merge_mode` in the user's
   `work-on.yaml` playbook
3. **Default:** `manual`

**Cascade logic** (when merge_mode is `cascade`):
1. Merge PR N via `Skill(Dev10x:gh-pr-merge)`
2. `git fetch origin develop`
3. Rebase PR N+1 onto `origin/develop`
4. Force-push, wait for CI (60s initial delay)
5. Merge PR N+1
6. Repeat for all PRs in the sequential chain

**Autonomous and cascade modes** skip the Phase 4 monitor's
`AskUserQuestion` gate — merges proceed without confirmation.
The `ALWAYS_ASK` marker on Phase 5's verification gate still
fires to confirm final session state.

### Merge Strategy

The merge command uses a configurable strategy flag. Resolution
order (first match wins):

1. **Playbook override:** `merge_strategy` in the user's
   `work-on.yaml` playbook (e.g., `merge_strategy: rebase`)
2. **Memory note:** user feedback memory mentioning merge
   preference (e.g., "prefer --rebase")
3. **Default:** `--rebase` — preserves groomed commit history
   and minimizes stacked-branch friction

| Strategy | Flag | When to use |
|----------|------|-------------|
| Rebase | `--rebase` | Default — atomic commits preserved |
| Squash | `--squash` | Single-commit PRs or messy history |
| Merge commit | `--merge` | Protected branches requiring merge |

### Stacked-Branch Merge Protocol

When merging stacked PRs (PR B depends on PR A's branch),
squash merges rewrite history and make downstream PRs
unmergeable. Follow this protocol:

1. Merge the base PR (A) using the configured strategy
2. `git fetch origin develop`
3. For each downstream PR (B):
   - `git checkout <branch-B>`
   - `git rebase origin/develop`
   - If conflicts → resolve, commit, force-push
   - Wait for CI to pass on the rebased branch
4. Merge downstream PR (B)
5. Repeat for further stacked PRs

**Note:** `--rebase` merge minimizes this friction compared
to `--squash` because the base commits remain intact.

### Progress Compaction

After completing each parallel group or sequential chain,
compact progress per `references/task-orchestration.md`
Pattern 8. Summarize completed items in task metadata to
free context for remaining work.

## Phase 4: Monitor

After all items have been processed in Phase 3, track every
PR created during this session through to merge.

**REQUIRED: Create one subtask per PR** under the Phase 4
parent task:

```
TaskCreate(subject="Monitor: PR #101 — GH-10 implementation",
    parentTaskId=phase4TaskId)
```

**REQUIRED: Use `Skill(Dev10x:gh-pr-monitor)` for every PR
(GH-724).** Raw `Agent(general-purpose)` monitoring bypasses
CI failure detection, review comment handling, and merge safety
gates — it is NOT a valid substitute. If the named skill is
unavailable, use `Agent(subagent_type="gh-pr-monitor")` with
the agent spec. Never use a bare `Agent(general-purpose)` for
PR monitoring.

For each PR:
1. Invoke `Dev10x:gh-pr-monitor` to watch CI and review status
2. If CI fails → fix with fixup commits, push, re-monitor
3. If new review comments → delegate to `Dev10x:gh-pr-respond`
4. When CI passes and PR is approved → merge via
   `Skill(Dev10x:gh-pr-merge)` (validates all pre-merge
   conditions, uses configured merge strategy)
5. After merge → rebase downstream branches if needed

Mark each subtask `completed` when the PR is merged or
handed off for external review.

## Phase 5: Verify

After all items are processed and PRs merged:

**REQUIRED: Wait for all background agents (GH-859).** Before
ANY verification step, call `TaskList` and check for tasks with
status `in_progress`. If any exist (e.g., Phase 4 monitor agents
still running), do NOT proceed — wait for all agents to complete.
The completion gate must not fire while monitors are still
tracking CI or merges.

**Enforcement loop:**
1. Call `TaskList`
2. If any task has status `in_progress` → wait and re-check
3. Only proceed when ALL tasks are either `completed` or
   `pending` (no `in_progress` tasks remain)

This prevents the failure mode where the completion gate fires
as soon as Phase 3 marks items as dispatched, before Phase 4
monitors confirm CI green or merges complete.

1. Call `TaskList` to show the full task list
2. **REQUIRED: Enforce PR comment resolution for every PR
   (GH-829).** For each PR processed in this session:
   a. Call `mcp__plugin_Dev10x_cli__pr_comments(pr_number=N)`
   b. If unaddressed comments exist, invoke
      `Skill(skill="Dev10x:gh-pr-respond", args="{pr_url}")` to
      address them — do NOT skip or defer
   c. After responding, re-check with `pr_comments()` to
      confirm zero unaddressed comments remain
   d. Repeat b-c until all comments are resolved
   e. **Do NOT proceed to step 3 while any PR has unaddressed
      comments.** This is a hard gate, not advisory.
   CI-green is NOT sufficient — unaddressed review comments
   (including bot comments) must be resolved before declaring
   work complete (GH-549 F-01). Under context pressure in
   large batches (5+ PRs), agents skip acting on comment
   check results — the loop in steps b-d prevents this by
   making resolution mandatory before advancing.
3. Verify all items are either merged, closed, or have
   research comments posted
4. Show summary table:

```
| Item | Type | Result |
|------|------|--------|
| PR #42 | PR | Merged |
| Issue #10 | Feature | PR #101 merged |
| Issue #20 | Research | Comment posted |
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
Options:
- Work complete — done (Recommended)
- Add more items
- Revisit an item

## Phase 6: Audit

**Phase 6 is REQUIRED when the session processes 3 or more
work items.** "Fewer than 3" means exactly 0, 1, or 2 items.
Do not add qualifiers like "independent" or "unique" to
justify skipping — count all items processed, regardless of
type or complexity.

**REQUIRED:** Invoke `Skill(skill="Dev10x:skill-audit")` to
analyze skill usage, compliance rates, and identify process
improvements.

**Hard self-check before marking Phase 6 complete (GH-724):**
Verify that `Skill(Dev10x:skill-audit)` was **actually called**
in this session (check your tool-use history). Saving findings
as memory notes or task descriptions is NOT a substitute —
only a real `Skill()` invocation counts. If the call is missing,
invoke it now before marking this task completed.

**Skip this phase** only when the session processed 0, 1, or
2 work items, or when the user explicitly declines.

## Pause/Resume

At any pause signal, invoke `Dev10x:session-wrap-up`.
Active worktrees and in-progress PRs are bookmarked
automatically.

## Known Limitations

- **`bypassPermissions` non-propagation:** The
  `bypassPermissions` flag does not propagate into background
  `Agent()` subagents. All background agents run with default
  permissions, causing Write/Edit tool blocks when the user's
  settings require approval. **Mitigation:** Use the
  Permission-Aware Dispatch table in Phase 3 to route
  write-requiring tasks to the main session (GH-549 F-04,
  GH-555, GH-562).

- **`Skill()` unavailable in subagents:** Background agents
  cannot call `Skill()` — only the main session has access.
  All implementation work MUST run in the main session via
  `Skill(Dev10x:work-on)`. Background agents are limited to
  monitoring and read-only operations (GH-549 F-02).

- **Worktree Write/Edit restriction:** Agents with
  `isolation: "worktree"` cannot use Write/Edit tools. See
  `Dev10x:work-on` parallelism policy for workarounds.

## Examples

### Example 1: Close all open loops

**User:** `/Dev10x:fanout`

Scans repo → finds 2 draft PRs and 5 open issues.
Classifies: PRs have no conflicts, 3 issues share files.
Plan: merge both PRs first (parallel), then issues in
2 parallel groups + 1 sequential chain.

### Example 2: Specific items

**User:** `/Dev10x:fanout #42 #55 GH-10 GH-15 GH-20`

Classifies the 5 items, builds conflict graph, presents
plan, executes.

### Example 3: PRs only

**User:** `/Dev10x:fanout PRs`

Scans only open PRs. Processes each to merge — mark ready,
monitor CI, fix comments, merge. Repeats until all merged.
