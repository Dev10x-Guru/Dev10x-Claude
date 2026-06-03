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
next — no checkpoints under adaptive friction. Never pause
between items to ask "should I continue?"

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

### Agent Isolation Matrix (GH-36)

Native `Agent` isolation supersedes the prior Permission-Aware
Dispatch table. Background agents now have full `Tools: *`
(Skill, Write, Edit, Bash, MCP) when dispatched as
`general-purpose`, and `isolation: "worktree"` provides a
per-agent temp worktree with automatic cleanup. The historic
"write-requiring tasks must run in the main session"
constraint no longer applies for the dispatch surface this
skill targets.

| Task type | Dispatch | Why |
|-----------|----------|-----|
| Issue implementation, PR fixes, rebase | `Agent(subagent_type="general-purpose", isolation="worktree", run_in_background=true, model="sonnet", mode="acceptEdits")` | Has Skill + Write + Edit; worktree isolates file changes; auto-cleanup if no changes |
| PR ready-to-merge (CI green, no comments) | `Agent(subagent_type="general-purpose", run_in_background=true, model="haiku")` | Read-only merge orchestration; no isolation needed |
| CI monitoring, status polling | `Agent(subagent_type="general-purpose", run_in_background=true, model="haiku")` | Read-only; cheaper without isolation |
| Investigation, research | `Agent(subagent_type="Explore" or "issue-investigator")` | Specialized agents with the right tools |

**Decision rule:** Default to `isolation="worktree"` for any
write-touching work item. Drop isolation only when the work
is provably read-only (monitoring, fetching, reviewing).

**Child worktree file-access allowlist (GH-424 F1):** A spawned
agent's file access is limited to the session's project
directories plus `/tmp`. A worktree created at a path *outside*
that allowlist is not readable or writable by the child — it
returns `BLOCKED` ("could not read/write files at the worktree
path") or silently falls back to branching in the primary
checkout (polluting the human's working copy). When a child must
self-create a worktree, place it under an allowlisted path
(e.g. `/tmp/<id>-<repo>-wt`), never a shared `.worktrees/` root
that may sit outside the allowlist. Note that
`isolation="worktree"` isolates only the orchestrator's own
repo — for cross-repo (sibling-repo) items it does NOT create a
worktree in the sibling repo, so those children must self-create
one in an allowlisted location or they branch in the sibling's
primary checkout.

**Worktree Write-deny on path-scoped rule targets (GH-376,
GH-399 F1):** Write allow-rules are keyed on the canonical
worktree path (e.g. `/work/dx/.worktrees/<name>`). An agent
running in an ephemeral worktree (`.claude/worktrees/agent-<id>/`)
will be denied writes to path-scoped targets like
`.claude/rules/**` because the allow-rule path prefix does not
match the agent's ephemeral path. This is GH-376 in action —
currently framed as interactive-session friction, but it also
silently degrades swarm output (agents return
`DONE_WITH_CONCERNS` for issues they cannot actually fix).
Two valid responses:
1. If the work item requires editing `.claude/rules/**` or
   other path-scoped targets, dispatch WITHOUT isolation so
   the agent runs in the canonical worktree where rules apply.
2. If isolation is still desired, document the known limit in
   the agent prompt so the agent reports `DONE_WITH_CONCERNS`
   with the specific file path that was blocked, rather than
   silently skipping the change.

**DONE_WITH_CONCERNS recovery (GH-399 F2):** When a
`isolation="worktree"` agent returns `DONE_WITH_CONCERNS`
because it could not apply a required change (Write-deny or
similar), the orchestrator CANNOT use `EnterWorktree` to
reach the agent's ephemeral worktree from a sibling top-level
worktree — `EnterWorktree` requires the target to share the
same repository root. Instead, use this recovery sequence:
1. Read the agent result for the PR branch name and the
   specific file(s) that were blocked.
2. Run `git worktree remove <agent-worktree-path>` to free
   the branch from the agent's ephemeral worktree.
3. In the main session, `git checkout <pr-branch>` and apply
   the missing change, then push and continue the merge
   lifecycle.
If `git worktree remove` fails (uncommitted changes), pass
`--force` — the agent's ephemeral worktree is disposable.

**Cross-repo salvage (GH-427).** When `worktree_orchestrator`
is true (see Worktree-Orchestrator Precheck), steps 2–3 above do
NOT work: the agent's worktree lives under a different repo root,
`git worktree remove` from the orchestrator targets the wrong
repo, and `git checkout <pr-branch>` cannot reach the branch. The
object store IS shared, though, so the agent's commit is reachable
via `git cat-file -e <sha>` from the orchestrator. Salvage by
cherry-picking it onto a fresh orchestrator-side branch:
1. Read the agent result for the commit SHA (or branch tip). If
   the agent stopped before committing, its work lived only as
   uncommitted files in an unreachable worktree — re-dispatch
   from scratch instead.
2. From the orchestrator worktree: create a branch from
   `origin/<base>` via `Skill(Dev10x:ticket-branch)`, then
   `git cherry-pick <agent-sha>` (the shared object store makes
   the SHA reachable even though the branch ref is not).
3. Resolve any conflicts, then ship the orchestrator-side branch
   through the normal lifecycle.
This is why the commit-early contract (ANTI-STALL CONTRACT) is
mandatory: an uncommitted agent leaves nothing in the object
store to cherry-pick.

### Worktree-Orchestrator Precheck (GH-427)

**Run this BEFORE the first Swarm Dispatch.** When the
orchestrator session itself runs from a worktree whose physical
root is *outside* the main repository tree (e.g. CWD is
`/work/dx/.worktrees/<name>` while the repo lives at
`/work/dx/<repo>`), `isolation="worktree"` agents land their
ephemeral worktrees under `<repo>/.claude/worktrees/agent-<id>/`
— a path the orchestrator cannot reach. `EnterWorktree(path=…)`
rejects the switch ("not inside the repository at …") because
the orchestrator's CWD is outside that repo root, so the GH-399
F2 recovery sequence is unavailable and a mid-lifecycle agent
(see ANTI-STALL CONTRACT) cannot be salvaged except by
cherry-picking from the shared object store.

**Detection (no subshell — two reads):**

```
git rev-parse --show-toplevel      # orchestrator worktree root
git rev-parse --git-common-dir     # shared .git → the main repo root
```

If `--show-toplevel` is NOT a path prefix of the directory that
holds `--git-common-dir`'s parent repo (i.e. the orchestrator is
a sibling worktree, not the main checkout), set
`worktree_orchestrator = true`.

**When `worktree_orchestrator` is true, default to serial mode**
(invoke `Skill(Dev10x:work-on)` inline, sequentially — see Serial
fallback below) rather than dispatching a swarm that cannot be
recovered. Announce the downgrade: "Orchestrator runs from a
sibling worktree (cross-repo root); using serial mode per
GH-427." The supervisor may override and force the swarm, but
only with the cherry-pick salvage path (DONE_WITH_CONCERNS
recovery, below) understood as the only recovery route.

### Swarm Dispatch (REQUIRED, GH-36)

**Every work item MUST be delegated to a worktree-isolated
background `Agent` whose prompt invokes
`Skill(Dev10x:work-on)`.** Do NOT implement issues inline in
the orchestrator session, and do NOT inline the work-on
contract into the agent prompt — the spawned agent calls
`Skill(Dev10x:work-on)` directly so work-on remains the
single source of truth for the implementation lifecycle.

**Wave-based dispatch.** Group non-conflicting items into
waves of size `max_concurrency` (default 3). Send all agents
in one wave as a **single assistant turn with multiple Agent
tool uses** so they run concurrently and share the
parent's prompt-cache prefix. Wait for completion
notifications before dispatching the next wave; do NOT poll.

**Sibling pub/sub bus (GH-133, GH-385 F3).** Before
dispatching a wave, create the per-wave JSONL bus that lets
children coordinate file ownership without serialising through
the orchestrator.

**Bus creation is the orchestrator's responsibility** — the
file and its parent directory MUST exist before any child is
dispatched. Children MUST NOT rely on creating the bus
themselves (the `mktmp` default returns a path without
creating the file, and nested-prefix creation fails when the
parent directory does not exist). Create the bus in two steps:

```
# Step 1: Create the wave directory
wave_dir = mcp__plugin_Dev10x_cli__mktmp(
    namespace="fanout",
    prefix=wave_id,
    directory=True,  # always created
)
# wave_dir["path"] → /tmp/Dev10x/fanout/<wave_id>.XXXX/

# Step 2: Create the bus file inside that directory
# Use Write tool to create an empty JSONL file:
Write(file_path=wave_dir["path"] + "/bus.jsonl", content="")
bus_path = wave_dir["path"] + "/bus.jsonl"
```

Children that cannot write to `bus_path` (permission deny or
file not found) MUST log the failure in their result message
but MUST NOT abort — sibling coordination via the bus is
best-effort. The orchestrator reads the bus on wave drain; a
missing or empty bus is treated as "no events".

Inline `bus_path` into every child's prompt. The orchestrator
is a passive consumer — it reads the bus once on wave drain to
harvest `bailout` and `conflict_signal` events for re-dispatch
decisions, but never publishes. Full event schema,
decision-gate rules (wait vs bail), and producer/consumer
contracts live in
[`references/orchestration/fanout-bus.md`](../../references/orchestration/fanout-bus.md).

**Per-item agent prompt template:**

```
You are working as part of a Dev10x:fanout swarm.

Swarm context:
- wave_id: <uuid>
- siblings: ["<item_id_a>", "<item_id_b>", ...]
- your_item_id: <item_id>
- conflict_group: <group_id>
- shared_files_with_siblings: [<paths>]  # should be empty within a wave
- bus_path: /tmp/Dev10x/fanout/<wave_id>/bus.jsonl
- lock_wait_timeout: 30s

Bootstrap (REQUIRED first, before Skill invocation):
1. Write .claude/Dev10x/session.yaml inside your isolated
   worktree with:
       friction_level: adaptive
       active_modes: [solo-maintainer, swarm-child]
   This signals Dev10x:work-on to skip its Phase 0 friction
   prompt and inherits the fanout session's friction level.

Task:
Invoke Skill(Dev10x:work-on) with this input: <issue or PR URL>

ANTI-STALL CONTRACT (highest priority — read before invoking work-on):
- "Branch created" = 0% done. "PR created" = 0% done.
  Only "PR MERGED" counts as task complete.
- Do NOT stop after branch creation or after PR creation.
  Run straight through: branch → implement → commit → push →
  PR → CI monitor → merge. Every step is mandatory.
- COMMIT EARLY (GH-427): reach a committed (ideally pushed)
  state as soon as the change compiles — before deep test
  polishing or refactoring. The commit is your durable
  checkpoint: if your turn ends mid-lifecycle, the orchestrator
  can salvage a committed SHA from the shared object store, but
  uncommitted files in your ephemeral worktree are lost when the
  worktree is reclaimed.
- After work-on returns, if the PR is open but not merged,
  that is NOT done. Invoke Skill(Dev10x:gh-pr-monitor) and
  then Skill(Dev10x:gh-pr-merge) to complete.
- If your turn ends before the PR is merged, your final line
  MUST be NEEDS_CONTEXT (not DONE). The orchestrator will
  re-dispatch to finish.

Sibling coordination (REQUIRED when shared_files_with_siblings
is non-empty OR mid-work drift is detected):
- Append events to bus_path. One JSON object per line.
- Before writing a path that overlaps with a sibling, append
  a file_lock_request event and wait up to lock_wait_timeout
  for a matching file_lock_grant from the implicated sibling.
- On detected drift, append a conflict_signal event then
  apply the decision gate:
    - Wait: severity=soft AND sibling reachable AND timeout
      not yet exceeded → poll bus.jsonl for a file_lock_grant
      or the sibling's bailout.
    - Bail: severity=hard, sibling unreachable, or wait
      timed out → append a bailout event and return
      "BLOCKED: file-scope drift on <path>".
- Never busy-loop. Never delete or rewrite bus.jsonl.
- Full schema and field definitions:
  references/orchestration/fanout-bus.md

Etiquette (REQUIRED):
- You are running concurrently with siblings. Do NOT call
  Skill(Dev10x:fanout) recursively.
- If you discover a file conflict with a sibling mid-work,
  use the bus to coordinate (above). If the bus does not
  resolve the conflict, pause, report via your result
  message, and do not push. The orchestrator will resolve.
- Do not force-push and do not touch main/develop directly.
- Branch upstream guard (GH-424 F2): if you self-create a
  worktree with `git worktree add -b <new> <base>`, the new
  branch tracks `<base>` — a bare `git push` would then advance
  the base branch's PR. Immediately run `git branch
  --unset-upstream`, and always push explicitly with
  `git push -u origin HEAD` (never a bare `git push`).
- Your worktree is ephemeral; assume it is destroyed if you
  make no changes.

Return on completion:
- PR URL (or "no PR produced — <reason>")
- Merge state: MERGED | OPEN | DRAFT (if open, explain why)
- Worktree path: the absolute path of your ephemeral worktree
  (run `git rev-parse --show-toplevel` to get it)
- Cost (total_cost_usd if known)
- Any sibling-coordination signals raised (reference bus
  event types: file_lock_request, conflict_signal, bailout)
- One of: DONE | DONE_WITH_CONCERNS: <text> |
  NEEDS_CONTEXT: <what> | BLOCKED: <reason>

Status line rules (GH-368, GH-385):
- DONE requires: PR merged, no open comments, CI green.
- DONE_WITH_CONCERNS: PR merged but flagged issues remain.
- NEEDS_CONTEXT: interrupted before merge (branch or PR open
  but not merged) — the orchestrator will re-dispatch.
- BLOCKED: permission wall, MCP unavailable, or merge blocked
  by branch protection requiring human action.
- A missing or non-terminal trailing line is treated by the
  orchestrator as NEEDS_CONTEXT → re-dispatch.
- NEVER end with a plain text summary and no status token.
```

**Subtask tracking.** Before dispatching the wave, create one
subtask per item under the Phase 3 parent and mark it
`in_progress`. Mark `completed` only when the agent's
completion notification arrives — never on dispatch (see
`references/orchestration/subagent-dispatch.md` Background
Agent Tracking).

**Serial fallback.** When the Agent tool is unavailable or
the user opts out (`mode: serial` playbook override),
invoke `Skill(skill="Dev10x:work-on", args="<item-url>")` in
the orchestrator session, sequentially. This trades
parallelism for compatibility with environments where
background agents are disabled.

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

Each issue (or parallel group of issues) is dispatched as a
worktree-isolated background Agent per the Swarm Dispatch
section above. The agent's `Skill(Dev10x:work-on)` invocation
runs the full lifecycle inside its isolated worktree:
branch setup, design, implementation, code review, commit,
PR creation, CI monitoring through merge. By the time the
agent's completion notification arrives, the PR is either
merged or surfaced via the agent's structured result for
follow-up.

After all agents in a wave complete, before starting the
next wave: fetch the merge base for the conflict-chain
successor items and rebase downstream branches if any
in-wave merges affected them.

**Note on work-on inside spawned agents.** A spawned agent
inherits no SessionStart context (memory, plan-sync, MOTD),
so `Dev10x:work-on`'s Phase 0 friction-level prompt would
fire fresh each time. The skill recognises fanout-nested
invocations via the swarm-context marker in the dispatch
prompt and skips Phase 0 accordingly. If work-on later
adds context dependencies that the spawned agent cannot
satisfy, surface them as `BLOCKED: <reason>` in the agent
result; the orchestrator will fall back to serial mode for
that item.

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

**Cascade/AFK and review thread auto-resolution (GH-399 F3):**
Under `merge_mode: cascade` (or `friction_level: adaptive`
defaulting to cascade), the orchestrator MAY auto-resolve a
review thread when ALL of the following hold:
- The user explicitly approved cascade or AFK mode at Phase 0
  (the `AskUserQuestion` gate at session start counts as
  explicit approval).
- The thread's concern has been addressed in a pushed commit
  (the fix is live on the PR branch, not just described).
- The thread was opened by an automated bot (e.g.
  `claude-review`, `hygiene-review`, `openai-review`) — not
  by a human reviewer.

If a human reviewer opened the thread, auto-resolution is
NEVER authorized regardless of merge mode. Escalate via
`AskUserQuestion` and wait for an explicit "resolve it" answer.

This policy only applies when the orchestrator is doing the
resolving (e.g., landing a fixup commit itself). When
re-dispatching a fresh agent to land the fix, the agent MUST
NOT auto-resolve threads — it should return
`DONE_WITH_CONCERNS: addressed thread, pending resolution`
and let the orchestrator decide based on the policy above.

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

## Phase 4: Collect

In the swarm model, each spawned agent runs the full
`Dev10x:work-on` lifecycle inside its isolated worktree —
including `Dev10x:gh-pr-monitor` for its own PR through to
merge. By the time the agent completes, its PR is either
merged or surfaced as a failure mode in the result.

Phase 4's job is therefore **collection**, not orchestration:

1. As each background agent's completion notification
   arrives, parse its result for: PR URL, status (DONE /
   DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED), cost, and
   any sibling-coordination signals.
   **Missing status line (GH-368 F2, GH-385 F1):** If the
   agent's trailing line does not match any of the four
   status tokens, treat it as `NEEDS_CONTEXT: agent
   terminated without a status line`. Re-dispatch the item
   with the last known PR URL inlined so the new agent can
   resume from the PR rather than restarting from scratch.
   **"PR created but not merged" (GH-368 F1):** If the
   agent result contains a PR URL and the trailing line is
   `DONE` but the PR state (via `mcp__plugin_Dev10x_cli__pr_get`)
   shows the PR is still OPEN, downgrade the status to
   `NEEDS_CONTEXT: PR open, merge incomplete` and re-dispatch
   to finish the monitor → merge lifecycle.
2. Mark the matching Phase 3 subtask `completed` only when
   the PR is confirmed MERGED. Mark `pending` again if the
   agent reported `NEEDS_CONTEXT` or if the PR is open.
3. For `BLOCKED` results, queue an `AskUserQuestion` so the
   orchestrator can decide between retry, fallback to
   serial, or skip.
4. **Harvest the sibling pub/sub bus (GH-133).** Once per
   wave drain, read `/tmp/Dev10x/fanout/<wave_id>/bus.jsonl`
   (using `Read`; the file is JSONL with one event per line).
   Collect every `bailout` and `conflict_signal` event.
   `bailout` events with `recoverable: true` mark their item
   for re-dispatch in a follow-up wave; `recoverable: false`
   bailouts escalate via `AskUserQuestion` alongside any
   `BLOCKED:` agent results. Treat the bus as authoritative
   for sibling-to-sibling drift — it captures conflicts the
   agent result message may have omitted.
5. After a full wave drains, before dispatching the next
   wave: rebase downstream conflict-chain successors onto
   the latest develop via `Skill(Dev10x:git-groom)`.
6. **Teardown the completed agent's worktree (GH-463).**
   After confirming the PR is MERGED (step 2), run the
   post-agent teardown sequence for that agent's worktree.
   See `### Post-Agent Worktree Teardown` below.

**Do NOT poll.** The harness notifies the orchestrator
session when each background agent finishes (per Agent
tool semantics). Polling, sleeping in a loop, or running a
`Monitor` over the agent state is wasted context.

**Serial-fallback mode.** When the swarm was skipped in
favour of in-session `Skill(Dev10x:work-on)`, this phase
collapses to "verify each call returned successfully"
since the lifecycle already ran inline.

### Post-Agent Worktree Teardown (GH-463)

After each background agent completes and its PR is confirmed
MERGED, clean up the agent's ephemeral worktree. The worktree
path is embedded in the agent's dispatch context as the
`isolation="worktree"` working directory — it follows the
pattern `.claude/worktrees/agent-<id>/`.

**Teardown decision tree (per worktree):**

1. Run `git -C <worktree-path> status --porcelain` to check
   for uncommitted modifications.

2. **Clean worktree (empty output):** PR is merged and
   worktree has no uncommitted changes.
   → `git worktree remove <worktree-path>`
   → Delete the child branch if it still exists locally:
     `git branch -d <branch>` (safe delete — already merged)
   → Proceed.

3. **Dirty worktree (non-empty output):** The worktree has
   uncommitted modifications. For each modified file:
   - Compare the working-copy version against the base branch
     HEAD: `git diff origin/<base> -- <file>` inside the
     worktree.
   - **Diff is empty (identical or not present on base):** The
     file is a stale duplicate — content already on develop or
     the file was removed upstream. Safe to discard.
   - **Diff is non-empty:** The file contains content not yet
     on the base branch. This is genuinely unique work.

4. **All dirty files are stale duplicates:**
   → `git worktree remove --force <worktree-path>`
   → Delete the child branch: `git branch -D <branch>`
   → Add a note to the Phase 4 subtask metadata:
     `"teardown": "force-removed (stale duplicates only)"`
   → Proceed.

5. **Any dirty file has unique content:**
   → Do NOT remove the worktree.
   → Add a note to the Phase 4 subtask metadata:
     `"teardown": "kept — unique content in <files>"`
   → Surface in the Phase 5 summary so the supervisor
     can decide what to do with the unique content.

**Timing:** Teardown runs AFTER the PR is confirmed MERGED
and AFTER all child-scoped processes have exited (i.e., after
the agent's completion notification arrives). Never tear down
a worktree while the agent is still running.

**Worktree path discovery:** The orchestrator knows the path
because it dispatched the agent with `isolation="worktree"`.
If the path is not recorded, use `git worktree list --porcelain`
and match the branch name to find the worktree path.

**Do not use `EnterWorktree`** for teardown inspection —
`EnterWorktree` requires the target to share the repository
root; use `git -C <path>` for status and diff commands instead.

## Phase 5: Verify

After all items are processed and PRs merged:

**REQUIRED: Wait for all background agents (GH-859).** Before
ANY verification step, call `TaskList` and check for tasks with
status `in_progress`. If any exist (e.g., Phase 4 monitor agents
still running), do NOT proceed — wait for all agents to complete.
The completion gate must not fire while monitors are still
tracking CI or merges.

**This wait is NOT a checkpoint.** Under adaptive friction, "no
checkpoints" means no implicit pauses for the user to acknowledge
progress between steps. It does not mean "skip waiting for
genuine async work to finish". Background agents finishing CI
monitoring and merge confirmation are hard dependencies of the
Phase 5 verification gate, not optional acknowledgements. The
distinction:

- Checkpoint (forbidden): "Phase 4 dispatched — ready to verify?"
- Dependency wait (required): `TaskList` polling until all
  in-progress agents return their results

See `references/friction-levels.md` § "No checkpoints" rule for
the full taxonomy.

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

## Swarm Teardown (GH-463)

After the Phase 5 gate confirms "Work complete", run a final
cleanup sweep. This catches any worktrees not removed during
Phase 4 (e.g., items that ended as NEEDS_CONTEXT → serial
fallback, or agents that were re-dispatched and left a
previous ephemeral worktree behind).

### Step 1: Prune stale worktree records

```
git worktree prune
```

This removes administrative records for worktrees whose
directories no longer exist. Run unconditionally — it is safe
even when there is nothing to prune.

### Step 2: Inspect surviving agent worktrees

List all worktrees: `git worktree list --porcelain`.
For each worktree whose path matches `.claude/worktrees/agent-*`
and whose branch is a `worktree-agent-*` branch:

Apply the same decision tree as Phase 4's Post-Agent Worktree
Teardown:
- Clean → `git worktree remove`
- All dirty files are stale duplicates → `git worktree remove --force`
- Any dirty file has unique content → keep; add to the
  swarm-end summary for supervisor review

Collect a list of worktrees kept (with reason) for the summary.

### Step 3: Clean abandoned agent branches (GH-463)

After removing worktrees, look for local `worktree-agent-*`
branches that no longer have a checked-out worktree and were
never pushed (no remote tracking ref).

**Delegate to `Dev10x:git-branch-prune` if available:**
When the `Dev10x:git-branch-prune` skill is present, invoke
`Skill(skill="Dev10x:git-branch-prune")` — it runs the full
classification + AskUserQuestion gate to confirm deletions.

**Fallback (git-branch-prune not yet available):** For each
local `worktree-agent-*` branch with no upstream and no open
PR, and whose tip is an ancestor of `origin/<base>` or whose
commits landed on the base branch (check via
`git log origin/<base> --ancestry-path <tip>` or commit-subject
match), mark it as safe to delete. Collect the list and present
it to the supervisor via `AskUserQuestion` before deleting.

Do NOT delete branches that are:
- Currently checked out in any worktree (`git worktree list`)
- Ahead of the base branch with no matched commits on the base
- Tracking an upstream that is not `: gone]`

### Step 4: Swarm summary

Include a teardown table in the Phase 5 summary:

```
| Worktree | Branch | Teardown |
|----------|--------|----------|
| agent-abc | worktree-agent-abc | Removed (clean) |
| agent-def | worktree-agent-def | Force-removed (stale dup) |
| agent-ghi | worktree-agent-ghi | Kept — unique content in foo.md |
```

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

## Subagent Status Protocol (GH-69, GH-368, GH-385)

When fanout dispatches `Agent()` for either swarm work (per
the Agent Isolation Matrix) or read-only monitoring fallback,
every prompt MUST instruct the agent to end its output with
one of:

- `DONE` — task complete (PR MERGED, CI green, no comments)
- `DONE_WITH_CONCERNS: <text>` — PR merged but flagged issues
- `NEEDS_CONTEXT: <what>` — re-dispatch needed; includes the
  case where the agent was interrupted before merge (branch or
  PR exists but is still open)
- `BLOCKED: <reason>` — permission wall or unrecoverable error

**Success bar (GH-368 F1):** `DONE` requires a MERGED PR,
not just a created or open one. A swarm agent that opens a PR
and stops must return `NEEDS_CONTEXT`, not `DONE`.

**Interruption guarantee (GH-368 F2, GH-385 F1):** Every
agent prompt MUST include the instruction:
> "Even if your turn ends before the PR is merged (context
> limit, permission wall, or any other interruption), your
> FINAL line MUST still be one of the four status tokens.
> Never end with free-form prose as your last line."

The orchestrator treats a missing or non-terminal trailing line
as `NEEDS_CONTEXT` and re-dispatches. Agents MUST NOT rely on
this fallback — the status line is their responsibility.

The main-session controller parses the trailing line and
branches deterministically: continue, queue concern, re-dispatch
with more context, or escalate to the user via
`AskUserQuestion`. A `BLOCKED:` status replaces today's
heuristic agent-failure detection — the agent self-reports the
failure, no guesswork.

See [`references/orchestration/subagent-status-protocol.md`](
../../references/orchestration/subagent-status-protocol.md)
for the full prompt template, parse pattern, and migration
notes.

## Recursive-Fanout Guard (GH-36)

A spawned swarm child MUST NOT re-invoke
`Skill(Dev10x:fanout)` — that would runaway-fork into a
swarm-of-swarms. Guards in priority order:

1. **Prompt etiquette (always).** Every Phase 3 agent
   prompt explicitly states "Do NOT call
   Skill(Dev10x:fanout) recursively" (see Swarm Dispatch
   template).
2. **Skill self-check (always).** When `Dev10x:fanout`
   starts, scan the incoming prompt and
   `.claude/Dev10x/session.yaml` for swarm-child markers —
   the dispatch prompt's literal `wave_id` line, or
   `swarm-child` appearing in `active_modes`. If detected,
   exit with an explicit error message directing the agent
   to use `Skill(Dev10x:work-on)` instead.
3. **Hook (future, v2).** A PreToolUse hook on
   `Skill(Dev10x:fanout)` invocations could check a
   global marker file written by the orchestrator before
   dispatch. Deferred to a follow-up ticket — prompt + skill
   self-check covers the surface today.

## Known Limitations

- **No native per-agent cost cap.** The Agent tool does
  not expose a hard budget knob equivalent to
  `claude -p --max-budget-usd`. The orchestrator can
  observe `total_cost_usd` post-hoc from agent results but
  cannot kill a runaway child mid-flight. Tracked as
  YAGNI until a real overrun is observed.

- **Pub/sub between siblings is not yet implemented.**
  When mid-wave file-scope drift is detected (sibling
  needs a file Phase 2 assigned to another sibling), the
  spawned agent reports the conflict via its result
  message and the orchestrator resolves between waves.
  Real-time sibling-to-sibling coordination via a JSONL
  bus or MCP `fanout_bus` server is planned as a
  follow-up (see ADR 0004).

- **SessionStart context is not inherited by spawned
  agents.** Memory, plan-sync state, and MOTD-injected
  context do not propagate into `Agent` subagents. The
  swarm dispatch prompt carries everything the child
  needs inline. If `Dev10x:work-on` evolves to depend
  on session-start state, the spawned agent will surface
  the gap as `BLOCKED:` and the orchestrator falls back
  to serial mode.

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
