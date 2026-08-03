---
name: Dev10x:session-wrap-up
description: >
  Capture and route unfinished work at session end — so nothing is
  lost when the session closes.
  TRIGGER when: session ending, user says "wrap up" / "pause" / "done
  for today", or too many open loops pile up.
  DO NOT TRIGGER when: mid-session active work with manageable task
  list, or starting new work (use Dev10x:work-on).
user-invocable: true
invocation-name: Dev10x:session-wrap-up
allowed-tools:
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__task_index_append
  - mcp__plugin_Dev10x_cli__task_index_get
  - mcp__plugin_Dev10x_cli__task_index_set
---

# Dev10x:session-wrap-up — Session End Orchestrator

**Announce:** "Using Dev10x:session-wrap-up to capture open loops
before closing this session."

## Mandatory Invocation Triggers (GH-163)

Audit GH-163 caught a session that wound down with CI still
unconfirmed, 5 newly-created follow-up issues unlinked to the
parent ticket, no plan-sync archive, and no parking note —
`Dev10x:session-wrap-up` matched every trigger but was never
invoked, and the parent orchestrator marked its wrap-up task
`completed` without a `Skill()` call.

**Hard trigger signals that REQUIRE this skill (do not skip):**

- User signals end-of-session: "wrap up", "pause", "done for
  today", "that's it"
- CI on a session-created PR is still pending or unconfirmed
  and the user is stepping away
- Open loops (PRs awaiting review, deferred tasks, unfiled
  follow-ups) exist with no plan-sync archive
- Orchestrators (`Dev10x:work-on`, `Dev10x:fanout`) reach the
  plan completion gate with non-empty pending tasks

**Anti-pattern (PROHIBITED):** Marking a "Session wrap-up" or
"Park items" task `completed` in an orchestrator's task list
without calling `Skill(Dev10x:session-wrap-up)` first. The task
completion is the side effect of the skill running — not a
substitute for running it.

## Overview

Collect all open loops, present them to the user, and help defer
each one to the right discovery context.

## Orchestration

This skill follows `references/task-orchestration.md` patterns.

**Auto-advance:** Complete each step, immediately start the next — no checkpoints under adaptive friction.
Never pause to ask "should I continue?" between steps.

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Discover open items", activeForm="Scanning for open loops")`
2. `TaskCreate(subject="Route deferred items", activeForm="Routing deferred items")`
3. `TaskCreate(subject="Post session summary", activeForm="Posting summary")`

Set dependencies: route blocked by discover, summary blocked by
route. Update status as each completes.

## Phase 1: Auto-Scan

Run all scans silently, collecting results into a structured list.

### 1a. In-session tasks

Use `TaskList` to get all tasks. Filter for non-completed tasks.

### 1b. Git status

```bash
git status --short
```

Summarize: N uncommitted files, N staged files, N untracked files.
Group by directory for readability.

### 1c. Session TODOs

```bash
git diff HEAD --unified=0
```

Scan the diff for any `# TODO:` or `# FIXME:` lines added in this
session (lines starting with `+` that contain TODO or FIXME).

### 1d. Open PRs

Call `mcp__plugin_Dev10x_cli__pr_detect(arg="")` (no arg) — the
tool auto-detects the PR for the current branch and returns
`pr_number`, `repo`, `pr_url`, and `branch`. Treat an `error`
response (no PR for branch) as "no open PR" rather than a
failure. No raw `gh` invocation or branch-name subshell is
needed.

**Merge-gated completion (GH-729).** An open/unmerged PR means the
session is **not** complete — "shippable / handed off to review" is
not terminal. When a detected PR is unmerged, the right deferral is
a **"Monitor PR #<N> for review / merge"** task (owned by
`Dev10x:gh-pr-monitor`), not a passive "Verify AC and close". This
mirrors `verify-acc-dod`'s merge-gated Decision Gate and keeps the
task-list invariant (GH-149) pointed at the real remaining work.

### 1e. Project TODO file

Read `.claude/TODO.md` if it exists. Extract pending items (lines
matching `- [ ]`).

### 1f. MEMORY.md in-progress section

Read the project MEMORY.md. Extract items under "## In-progress work"
heading if present.

## Phase 2: Present & Gap-Fill

Present all discovered open loops in a scannable format:

```markdown
## Session Wrap-up — Open Loops Found

### In-session tasks (N)
• [status] Task description

### Git status
• N uncommitted files in path/to/dir/

### TODOs added this session (N)
• file.py:LINE: TODO description

### Open PRs (N)
• #123: PR title (url)

### Project TODO items (N)
• Existing deferred item from previous session

---

Is there anything else to capture before closing?
```

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text)
to let the user add free-text items.

## Phase 3: Per-Item Triage

For each open loop, **REQUIRED: Call `AskUserQuestion`**
(do NOT use plain text) to present a choice:

**Options:**
- **Finish now** — keep as session task, continue working
- **Defer** — invoke `Dev10x:park` for target selection
- **Drop** — remove, no longer needed

If the user picks "Finish now" for any item, pause the wrap-up and
let them work. When they return, resume from where they left off.

If the user picks "Defer", invoke `Dev10x:park` with the item.

If the user picks "Drop", mark the task as completed via `TaskUpdate`
and move on.

## PR Reminder Format

When deferring an item by posting a reminder comment on an open PR,
use this standard prefix so `Dev10x:park-discover` §2f can discover it:

```markdown
🔖 **Session bookmark**

This is an automated self-reminder left by `Dev10x:session-wrap-up` for the
PR author to pick up in a future session.

**Current state:** <brief summary of where the PR stands>

**Next steps:**
- <actionable item 1>
- <actionable item 2>
```

The `🔖 **Session bookmark**` prefix on the first line is required —
`Dev10x:park-discover` scans for this exact pattern when checking open
PRs for deferred work.

## Phase 3b: Session State Persistence (GH-917, GH-782)

**After triage, before summary**, persist session state to the
per-repo task index so a future session can resume where this one
left off. Write it through the MCP tools — never with Write/Edit
(ADR-0018 D5, GH-1009).

**What to persist:**

1. **Uncompleted tasks** — append each pending/in-progress entry
   from `TaskList` with `source: session-wrap-up`, one call per
   task:
   ```
   mcp__plugin_Dev10x_cli__task_index_append(entry={
       "subject": "Implement fix",
       "status": "pending",
       "source": "session-wrap-up",
       "metadata": {"type": "epic"},
   })
   ```

2. **Continuation prompt** — generate a one-paragraph summary
   of what was in progress and what to do next. Pass it as
   `continuation_prompt` to `task_index_set` (below). This
   bootstraps context after `/clear` or a new session.

3. **Collected insights** — any lessons learned, patterns
   discovered, or decisions made during the session that
   are not captured in code or commits. Pass as `insights`.

4. **Freshness stamp (GH-782)** — stamp the index with the wrapping
   session's branch/tickets and a wrap timestamp so a later session
   can tell live deferrals from stale carryover (see the scope note
   below — this is `park-discover`'s input, not the
   `session_adoption` gate's identity). Steps 2–4 are one call:
   ```
   mcp__plugin_Dev10x_cli__task_index_set(
       continuation_prompt="<one paragraph>",
       insights=["<lesson>"],
       branch="<current git branch>",
       tickets=["GH-782"],          # ticket IDs this session worked
       wrapped_at="2026-07-09T10:30:00Z",   # ISO8601 UTC
   )
   ```
   Only the fields you pass are written, so this cannot blank the
   `tasks:` appended in step 1. `Dev10x:park-discover` reads these
   keys to classify each carried entry as **live** (branch matches,
   or a ticket overlaps the resuming session) or **stale** (identity
   mismatch, or an old `wrapped_at`) — see that skill's *Staleness
   classification*. Without the stamp a months-old `tasks:` list /
   `continuation_prompt` is silently re-surfaced as if current — the
   GH-782 root cause.

**Ephemeral-only, no durable keys (GH-774, ADR-0018).** Durable
preferences — `friction_level`, `active_modes`, and the
`gate_*` keys — live in the global
`~/.config/Dev10x/friction.yaml`. This skill persists **only**
ephemeral state: do NOT write `friction_level` or `active_modes`
anywhere. A leftover `active_modes: [solo-maintainer]` carried in
session state was the PR #740 auto-merge hazard; keeping durable
keys out of what this skill rewrites removes that class of
stale-mode bug.

**The freshness stamp is NOT the gate's session identity
(GH-1001).** Two things once shared these key names, and only one
of them still lives here:

- The `branch:` / `tickets:` written in step 4 above stay. Their
  consumer is `Dev10x:park-discover`, which classifies each carried
  entry live-or-stale against them. Dropping the stamp reintroduces
  the GH-782 bug where a months-old `tasks:` list resurfaces as
  current.
- The identity the Phase 0 `session_adoption` gate reads is a
  *different* thing and does not come from here. Plan-sync persists
  it (MCP-written, gate-free) and `_computed_session_stale()` reads
  it from there — so do not expect `task_index_set(branch=…)` to
  influence that gate, and do not treat this stamp as a durable pref.

**Integration with `/clear`:** After persisting, inform the user:
"Session state saved. To resume after `/clear`, invoke
`Dev10x:work-on` — it will detect the saved state and offer to
continue."

> **Rehomed in GH-1009 (ADR-0018 D5).** This phase — and the `park`
> family and `Dev10x:gh-pr-bookmark` — used to Write/Edit the task
> index at `.claude/Dev10x/session.yaml`. GH-1001 left that in place
> as a documented exception pending a destination decision; GH-1009
> made it, because a Write/Edit under a project's `.claude/` trips
> Claude Code's self-settings consent gate on every session
> regardless of allow rules (ADR-0018 RC-A) — so the exception was
> paying the exact cost the ADR exists to remove. The index now lives
> outside every repo and only the `task_index_*` MCP tools write it.
> The retired path is read for one release, then deleted by
> `Dev10x:plugin-doctor`.

## Phase 4: Summary

After all items are triaged, present a brief summary:

```
## Wrap-up Complete

Finished: 2 items
Deferred: 3 items (2 → TODO.md, 1 → Slack)
Dropped: 1 item

Session is ready to close.
```

## Batch Mode

If the user has many items (>5), offer batch operations:

- "Defer all to .claude/TODO.md" — sends all remaining to project file
- "Defer all to Slack" — sends all as one combined Slack DM
- "Triage one by one" — standard per-item flow

## Used By

- Invoked directly by user: `/Dev10x:session-wrap-up`
- Can be suggested by Claude when detecting session-end signals
  (e.g., user says "that's it for today", "let's wrap up")
