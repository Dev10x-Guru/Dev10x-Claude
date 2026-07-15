# Git Branch History Grooming (Instructions)

## Overview

This skill helps restructure, polish, and clean up git commit history in the current branch before merging. Use it to create atomic, well-organized commits that tell a clear story.

**Guiding Principle:** When rewriting commit titles, shift the perspective from what changed in the code to what it enables for the user. Describe the user-facing outcome, not the implementation detail. E.g., `Enable automatic terminal discovery` not `Add DEVICES_READ to Square OAuth scopes`.

**When to use this skill:**
- After receiving review feedback that requires changes across multiple commits
- When commits have become messy during development
- Before creating a PR to ensure clean history
- When CI blocks merge due to fixup commits

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Read that file for full context on auto-advance and batched
decision queues.

**Auto-advance:** Complete each phase and immediately start the
next — no checkpoints under adaptive friction. Never pause
between phases to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Analyze commit history", activeForm="Analyzing commits")`
2. `TaskCreate(subject="Choose restructuring strategy", activeForm="Choosing strategy")`
3. `TaskCreate(subject="Execute restructure", activeForm="Restructuring commits")`
4. `TaskCreate(subject="Push and update PR references", activeForm="Pushing changes")`

Set dependencies: strategy blocked by analysis, execute blocked
by strategy, push blocked by execute.

**Nested-mode exemption:** When invoked as a nested skill within
a parent orchestrator (e.g., via `Skill()` from `Dev10x:work-on`),
startup task creation is optional — at most 1 summary task. See
`references/task-orchestration.md` § Delegated Invocation Exception.

**Scope of nested-mode exemption:** The exemption covers only
`TaskCreate` calls (task tracking overhead). It does NOT exempt
`REQUIRED: AskUserQuestion` decision gates — the Phase 2
strategy selection gate must still fire even in nested mode,
because the parent cannot predict which grooming strategy is
appropriate. The parent's "Full shipping pipeline" selection
establishes *intent to groom*, not *which strategy to use*.

**NEVER auto-select a grooming strategy at strict/guided
friction.** Even when invoked from a parent orchestrator that
has chosen "Full shipping pipeline", you MUST present the
`AskUserQuestion` gate for strategy selection. Auto-selecting
autosquash because it is "Recommended" is a gate bypass — the
recommendation is a default hint for the user, not permission to
skip the gate. Anti-pattern (GH-458): agent ran
`git autosquash-develop` without presenting the strategy gate in
nested mode.

**Friction level wins over nested mode (GH-591).** GH-458 (never
auto-select, even nested) and GH-530 (adaptive auto-selects
silently) only conflict if read as peers — they are not. The
friction level is the deciding axis. At `strict`/`guided` the
gate always fires (the rule above), nested or not. At `adaptive`
the deterministic auto-select in Phase 2 governs — nesting does
NOT re-impose the gate, because `adaptive` is the supervisor's
standing pre-authorization to proceed without prompts. The one
carve-out: `adaptive` may auto-select only deterministic,
non-destructive strategies (fast-exit, autosquash of `fixup!`
commits, message-only mass rewrite); when the only viable path is
a destructive Full restructure or interactive reorder, fire the
gate even at `adaptive`. See Phase 2 for the auto-select rules.

## Workflow

### Phase 0 Precondition: Refuse pre-merge groom with open threads (GH-68, Fix E)

Squashing a PR with unresolved review threads orphans every
permalink in every reply: the old SHAs no longer exist on the
branch, so `https://github.com/{owner}/{repo}/pull/{N}/commits/{sha}`
URLs return 404 and the per-comment audit trail is destroyed.
Reviewers who post fixups expect the SHAs they reference to
remain reachable until they resolve their threads.

**Hard rule:** When git-groom is invoked **as a nested skill from
`Dev10x:gh-pr-monitor`** (or any other background agent), refuse
to groom if any unresolved review thread exists. The supervisor's
main session may still groom under their direct control — only
agent-initiated grooming is blocked.

**Detection:**

1. Determine the invocation context. The parent skill MUST pass
   `invoker={parent-skill-name}` in the args (e.g.,
   `invoker=Dev10x:gh-pr-monitor`). Absent any `invoker=` arg,
   assume the invocation is supervisor-driven and skip this
   precondition.

2. If `invoker` matches `Dev10x:gh-pr-monitor` or another
   background-agent skill, fetch the PR and count unresolved
   threads via MCP tools:

   - `mcp__plugin_Dev10x_cli__pr_detect()` → returns `pr_number`
     (skip the precondition if no open PR exists — there are
     no permalinks to break)
   - `mcp__plugin_Dev10x_cli__pr_comments(action="list",
     pr_number=N, unresolved_only=True)` → returns the root
     comments of every unresolved thread; the count is the
     length of the returned `comments` list

3. If the count is greater than zero, refuse:

   ```
   BLOCKED: groom-refused-open-threads <count>

   git-groom refused: {count} unresolved review threads exist on
   this PR. Squashing pre-merge would orphan every commit-link
   permalink in the thread replies (the SHAs would no longer
   exist on the branch) and destroy the per-comment audit trail
   reviewers rely on.

   The fact that fixup commits exist IS the signal that a
   reviewer is mid-conversation. Wait for thread resolution
   before grooming, or invoke git-groom from the supervisor's
   main session (without `invoker=Dev10x:gh-pr-monitor`) if you
   explicitly want to override.
   ```

   Exit non-zero. Do NOT continue to Phase 1.

4. If zero unresolved threads OR `invoker` indicates supervisor
   session, proceed to Phase 0b normally.

### Phase 0b Precondition: Pre-merge Spec Drift Check (GH-173)

Before squashing or rewriting commit history, verify the
canonical spec at `docs/specs/<TICKET-ID>.md` still matches the
code on the branch. Grooming locks in whatever shape the branch
has — if behavioural drift exists, the merge would land code
that contradicts the spec, and every future agent generating
from that spec would silently regenerate the wrong behaviour.

**No-op rule.** If `docs/specs/<TICKET-ID>.md` does not exist,
skip this phase silently. Projects that haven't adopted SPDD
scoping continue as before.

**Check:**

```python
from pathlib import Path
from dev10x.spec import detect_drift

ticket_id = "<extracted from branch>"
spec_path = Path(f"docs/specs/{ticket_id}.md")
if spec_path.exists():
    report = detect_drift(
        spec_path=spec_path,
        project_root=Path("."),
    )
    if report.has_behavioural:
        # FAIL-CLOSE — refuse to groom.
        ...
```

**Fail-close on behavioural drift.** Print the same `BLOCKED:`
contract used in Phase 0:

```
BLOCKED: groom-refused-spec-drift behavioural

git-groom refused: spec drift detected at
docs/specs/{TICKET-ID}.md. Behavioural drift means the code
no longer matches the spec's Requirements / Acceptance Criteria
/ Safeguards sections. Squashing pre-merge would lock the
contradiction into history.

Run `Dev10x:spec-update` to fix the spec first (Golden Rule:
fix the prompt, then regenerate), then re-invoke git-groom.

To override (rare — only when the spec is intentionally being
retired with this merge), pass `--skip-spec-check` explicitly.
```

Exit non-zero. Do NOT continue to Phase 1.

**Warn on structural drift.** Allow the groom to continue, but
surface a warning that `Dev10x:spec-sync` should run before the
next session:

```
WARNING: structural spec drift detected at
docs/specs/{TICKET-ID}.md. The Architecture / Implementation
Steps sections describe a different code shape. Consider running
`Dev10x:spec-sync` after this merge so the next agent generating
from this spec gets the right file layout.
```

This precondition uses the shared `dev10x.spec.drift_detector`
module so `gh-pr-respond` and `git-groom` agree byte-for-byte
on what counts as drift.

### Phase 1: Analyze Current State

```bash
# View commits in current branch (relative to base)
git log --oneline develop..HEAD

# See what files changed in each commit
git log --oneline --stat develop..HEAD

# Identify the base commit for rebasing
git merge-base develop HEAD
```

**SHA Staleness Warning:** Record SHAs at analysis time only for planning.
Before writing any execution scripts (message files, sequence editor),
always re-run `git log --oneline <base>..HEAD` to get the current SHAs.
Any commit (rebase, amend, reset) changes all descendant SHAs. Using
analysis-time SHAs in execution scripts will silently target wrong commits.

**Stale local base (GH-486):** Resolve the range against
`origin/<base>` (or the fork-point), not a possibly-stale local
`<base>`. Local `develop` lags `origin/develop` after rebase-merge,
long-lived feature work, or worktrees sharing an outdated ref —
anchoring on it mis-computes the commit range. The `rebase_groom`
MCP tool now qualifies a bare branch name to its `origin/<base>`
remote-tracking ref automatically and reports a `base_notice` when
the local ref lags. When analyzing by hand, prefer
`git merge-base --fork-point origin/develop HEAD` over
`git merge-base develop HEAD`, and `git log --oneline origin/develop..HEAD`
for the range.

### Phase 2: Choose Strategy

After analysis, queue the strategy decision in task metadata.
If no other tasks are running, present immediately. Otherwise
the orchestrator batches it with other pending decisions.

Mark the phase transition: `TaskUpdate(taskId=strategy_task, status="pending", metadata={"decision_needed": "Which restructuring strategy?", "options": ["Fixup", "Full restructure", "Mass rewrite", "Interactive rebase"]})`

**At strict/guided level:**

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text, call spec: [ask-restructuring-strategy.md](./tool-calls/ask-restructuring-strategy.md)).

The "Recommended" marker is **conditional on fixup presence** — fixup
commits are the discriminator between the two common requests:

- Fixup (Recommended when `fixup!`/`squash!` commits exist) — Small
  targeted fixes applied to specific commits
- Full restructure (Recommended when no fixups exist) — Reset all
  commits, rebuild from scratch as atomic layer/component commits
- Mass rewrite — Non-interactive message rewrite from JSON
- Interactive rebase — Full manual control over commit order

Rationale: if fixups exist, the user almost always wants them applied;
if there are no fixups, a "full restructure" is the probable request.

**At adaptive level (GH-530):**

Auto-select strategy based on commit analysis. **Fixup presence is the
primary discriminator** — if fixups exist, apply them; if there are no
fixups, a full restructure is the probable request:

- Single clean commit, no fixups, message OK → **fast exit**
  with "Nothing to groom" (GH-776). This keeps the decision
  within the groom skill rather than the orchestrator.
- **Fixup commits present → auto-select "Fixup" and apply them.**
  The presence of `fixup!`/`squash!` commits is the strongest signal
  the user wants targeted squashing, not a rebuild.
- No fixups, only message issues → auto-select "Mass rewrite"
- Mixed structural issues → auto-select "Fixup" (safest default)
- **No fixups and structural reorganization is needed → "Full
  restructure" is the probable request.** Because that path is
  destructive (soft reset + rebuild), do NOT auto-execute it — fire
  the strategy `AskUserQuestion` gate with Full restructure as the
  recommended option (see the destructive-ambiguity carve-out below).
- No `AskUserQuestion` call — execution continues uninterrupted
  (except the destructive Full-restructure case above)

**Applies even when nested (GH-591).** The nested-mode rule does
not re-impose the gate at adaptive — friction level wins (see the
Friction-level note near the top of this file). Every bullet above
is deterministic and non-destructive, so auto-selecting them
honors both GH-458 (no silent destructive rewrites) and GH-530
(no AFK prompts).

**Carve-out — destructive ambiguity still gates (GH-591).** If
commit analysis cannot resolve to one of the deterministic options
above and the only viable path is a destructive Full restructure
(soft reset + rebuild) or an interactive reorder, fire the
strategy `AskUserQuestion` gate even at `adaptive`. A
history-destroying operation with no deterministic answer is the
one case the supervisor must confirm regardless of friction.

See `references/friction-levels.md` for the universal model.

After selection, update the execute task description with the
chosen strategy and auto-advance into Phase 3.

### Phase 2b: Target-Shape Gate (Full Restructure only)

When Strategy B (Full Restructure) is selected, agree the target
shape with the supervisor BEFORE running `git reset --soft <base>`
— the gate captures five axes (final location, layer-per-commit,
tests-with-subject, ticket/PR-boundary split, repository/DAL
extraction) and names the atomicity criterion the rebuild must
satisfy. See [`references/target-shape-gate.md`](references/target-shape-gate.md)
for the full gate spec and the `AskUserQuestion` call. This phase
does not apply to Strategies A, C, or D.

### Phase 2c: Backup Tag (REQUIRED before soft reset)

Immediately before `git reset --soft <base>` in Strategy B, create
`git tag -f groom-backup-<branch-slug> HEAD` so the pre-rebuild tree
is recoverable by name. See
[`references/tree-reconstruction.md`](references/tree-reconstruction.md)
for the tagging convention and the tree-equality assertion this tag
enables at the end of Phase 3.

### Phase 3 Precondition: Stash Guard

Before any rebase operation, check for unstaged changes that
would cause `git rebase` to fail:

```bash
git status --porcelain
```

If unstaged changes exist (e.g., lock files, generated files):
1. Stash them: `git stash --include-untracked`
2. Run the rebase strategy
3. Pop the stash: `git stash pop`

This prevents the common failure: `error: cannot rebase: You
have unstaged changes.` — which halts the entire groom pipeline.

#### Strategy A: Fixup Commits (for small targeted changes)

Use when making small fixes to specific commits:

```bash
# Create a fixup commit targeting a specific commit
git add <files>
git commit --fixup=<target-commit-sha>

# Simple autosquash (fixup commits only, no reordering):
git autosquash-develop

# Custom sequence (reordering, message rewrites, splits):
# 1. Create unique seq file: /tmp/Dev10x/bin/mktmp.sh git rebase-seq .txt
# 2. Write sequence to the returned path
# 3. Run: ${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh <path> develop
```

**Key insight:** For pure autosquash (squashing fixup commits into their targets), use `git autosquash-develop` — an alias that wraps `GIT_SEQUENCE_EDITOR=true git rebase -i --autosquash $(git merge-base develop HEAD)` internally, avoiding env-prefix and subshell permission friction. The rebase script (`git-rebase-groom.sh`) replaces the todo with your sequence file, so commits not listed in the file are dropped. Only use the script when you need custom sequence control.

#### Strategy B: Full Restructure (for major reorganization)

Use when commits need complete reorganization. The target-shape gate
(Phase 2b) and backup tag (Phase 2c) MUST both complete before the
soft reset below runs:

```bash
# Phase 2c: tag the pre-rebuild tip first
git tag -f groom-backup-<branch-slug> HEAD

# Soft reset to base, keeping all changes staged
git reset --soft <base-commit>
```

**Execute the rebuild via the documented plumbing recipe**, not ad
hoc `git commit -m` calls — see
[`references/tree-reconstruction.md`](references/tree-reconstruction.md)
for the full non-interactive `git reset HEAD` → `git add -f` →
`git write-tree` → `git commit-tree ... -F <msgfile>` loop, its
partition-completeness check, and the required tree-equality
assertion (`git diff groom-backup-<branch-slug> HEAD`) before Phase
3's force-push.

##### Granularity & cohesion

A "full restructure" decomposes the branch — it does **not** collapse it.
**"Full restructure" ≠ squash-to-one.**
Squash-to-one is the *Fixup* strategy's outcome (Strategy A), not a full
restructure; producing a single commit here is the opposite of what was
asked.

When rebuilding the atomic commits, make each one:

1. **Small — the smaller the better, up to a point.**
   Commit-per-class is *too* granular.
   The unit is a coherent layer/component, not a single file or symbol.
2. **Separated by architectural layer and component.**
   Each layer gets its own commit, ordered bottom-up by dependency so
   each commit builds on the ones before it.
3. **Highly cohesive — tests and fakers ship in the SAME commit as the
   production code they cover.**
   A commit carries its own verification; do not split tests or fakers
   into a separate "add tests" commit.
4. **Autonomous.**
   Each commit should build / typecheck / test in isolation and in
   dependency order.
   Pre-commit stashing of unstaged files already gives a good isolation
   signal — staging whole files per layer means each commit's hooks run
   standalone.

**Layer → commit example** (from a Square payments terminal branch,
ordered bottom-up):

| # | Commit (layer / component)              | Example modules                              |
|---|-----------------------------------------|----------------------------------------------|
| 1 | API facade / client adapters            | `payments.square.client.*`                   |
| 2 | service adapter / aggregator + its DTO  | `payments.square.terminal` + `dto`           |
| 3 | transport / GraphQL layer               | `payments.api.queries`                       |

**Re-run Phase 4 for every rewritten SHA.** A multi-commit split orphans
more PR permalinks than a single squash does — each new commit boundary
is a new SHA — so the PR-reference refresh in Phase 4 (Update PR
References) must run for *all* rewritten commits, not just the tip.

#### Strategy D: Non-Interactive Mass Rewrite (for bulk message updates)

Use when rewriting many commit messages without structural changes (no
splits, squashes, or file renames beyond what the commits already have).
Fully automatable — no interactive editor required.

**Use the script** (single permission approval, runs unattended):
```bash
/tmp/Dev10x/bin/mktmp.sh git groom-config .json
```
Write the config to the returned path, then run:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/git-groom/scripts/mass-rewrite.py <config-path>
```
The script creates its own isolated workdir under `/tmp/Dev10x/git/`.

Config format:
```json
{
  "base": "develop",
  "commits": {
    "abc1234": "New outcome-focused message",
    "def5678": {
      "message": "New message with file renames",
      "renames": [["old/path/file.md", "new/path/file.md"]]
    }
  }
}
```

The script validates SHAs against the current log before doing anything,
prints a preview of all commits (marking which will be rewritten), then
runs the full rebase unattended. See the script docstring for details.

**Manual steps (reference / fallback):** The script implements the
following steps — useful to understand internals or when the script
cannot be used.

**Step 1:** Re-check current SHAs (never use analysis-time SHAs):
```bash
git log --oneline $(git merge-base develop HEAD)..HEAD
```

**Step 2:** Create an isolated workdir for this groom session:
```bash
/tmp/Dev10x/bin/mktmp.sh -d git groom
```
Store the returned path as `$WORKDIR`.

**Step 3:** Write one message file per commit to rewrite using the Write tool:

```
Write $WORKDIR/msgs/<7-char-sha>:
Enable user login with HMAC session auth
```

Repeat for each commit needing a new message. The Write tool creates
parent directories as needed.

**Step 4:** Write the complete rebase sequence using the Write tool:

```bash
/tmp/Dev10x/bin/mktmp.sh git rebase-seq .txt
```

Write to the returned path:
```
pick <oldest-sha> First commit
exec git commit --amend -F $WORKDIR/msgs/<oldest-sha-short>
pick <sha> Second commit with git mv
exec git mv old/path new/path && git commit --amend -F $WORKDIR/msgs/<sha-short>
pick <newest-sha> Third commit (no rewrite needed)
```

Oldest commit at top.

**Step 5:** Run the non-interactive rebase:
```bash
${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh <seq-path> develop
```

`GIT_EDITOR="true"` suppresses the commit message editor for `--amend`
so the rebase runs fully unattended.

#### Strategy C: Interactive Rebase (for reordering/editing)

Use when you need to reorder, edit messages, or split commits:

```bash
git rebase -i <base-commit>
```

Commands in interactive rebase:
- `pick` - keep commit as-is
- `reword` - change commit message
- `edit` - stop to amend the commit
- `squash` - meld into previous commit (keep message)
- `fixup` - meld into previous commit (discard message)
- `drop` - remove commit

### Conflict Resolution During Rebase

When any rebase strategy encounters conflicts, resolve them
inline before falling back to abort + Strategy B:

1. Run `git diff --name-only --diff-filter=U` to list conflicted files
2. For each conflicted file:
   a. Read the file with the Read tool
   b. Identify conflict markers and determine the correct resolution
   c. Edit the file to remove markers and apply the resolution
   d. Stage: `git add <file>`
3. Continue: `git rebase --continue`
4. If conflicts recur, repeat (max 3 rounds)
5. If resolution fails after 3 rounds or conflicts are too complex,
   abort and fall back to Strategy B (soft reset)

**MCP tool callers:** When `rebase_groom` or `mass_rewrite` returns
`{"conflict": true}`, the rebase is paused — not aborted. Use the
`conflicted_files` list to resolve, then run `git rebase --continue`
via Bash. Do NOT call `git rebase --abort` unless resolution fails.

### Phase 3: Push Changes

Mark phase transition: `TaskUpdate(taskId=execute_task, status="completed")` then `TaskUpdate(taskId=push_task, status="in_progress")`

**REQUIRED for Strategy B only — tree-equality assertion before the
force-push.** Run `git diff groom-backup-<branch-slug> HEAD` and
confirm it is empty before continuing. A non-empty diff means the
rebuild changed content, not just commit boundaries — roll back with
`git reset --hard groom-backup-<branch-slug>` and re-run the
reconstruction loop instead of pushing. See
[`references/tree-reconstruction.md`](references/tree-reconstruction.md)
§ "Tree-Equality Post-Condition".

```bash
# Force push with lease (safer than --force)
git push origin <branch> --force-with-lease
```

**Important:** `--force-with-lease` fails if someone else pushed to the branch, preventing accidental overwrites.

**CI invalidation warning:** Force push triggers new CI runs on
the new HEAD. All previous CI results become invalid. The calling
skill (e.g., `Dev10x:work-on`) MUST re-monitor CI after grooming
completes — do not declare CI green based on pre-groom results.

### Phase 4: Update PR References (MANDATORY)

**Hard rule:** After force-pushing groomed history, this phase
MUST execute when an open PR exists for the branch. PR body and
summary comment contain stale commit hashes that confuse
reviewers and break permalink traceability. Skipping this phase
leaves stale SHAs in the PR body — detected as PARTIALLY_COMPLIANT
in session 0aa83b83.

**Anti-pattern:** Marking Phase 4 as "optional" or skipping it
because "the PR will be updated later" — the groom skill owns
the full rewrite lifecycle including reference updates.

1. Detect open PR: `gh pr view --json number,state`
   - If no PR or PR is closed/merged → skip Phase 4, mark done
   - If PR is open → proceed with updates
2. Get the new commit hash(es): `git log --oneline develop..HEAD`
   and record the mapping `old_sha → new_sha` for each commit that
   was rewritten (read it from the pre-rebase reflog snapshot
   captured in Phase 3).
3. Update the PR body commit links with new hashes via the
   `mcp__plugin_Dev10x_cli__update_pr` MCP tool (auto-permitted under
   `mcp__plugin_Dev10x_cli__*`; pass the rebuilt body string):
   ```
   mcp__plugin_Dev10x_cli__update_pr(pr_number=<N>, body=<rebuilt_body>)
   ```
4. Update the summary comment (first comment by the author) with new hashes.
5. **Rewrite permalinks in review-thread replies (GH-68, Fix F).**
   The PR body and summary comment are not the only surfaces
   that hold commit permalinks — replies inside review threads
   reference SHAs too (e.g., `Fixed in <permalink>`). After a
   force-push those replies point at orphaned SHAs and 404.

   For each rewritten commit, list every thread comment that
   contains the old SHA and replace it with the new SHA.

   List the thread comments via the MCP tool:

   - `mcp__plugin_Dev10x_cli__pr_comments(action="list",
     pr_number=N)` → returns all review-thread comments with
     `id`, `body`, etc. Filter the returned list to those whose
     body matches `/commits/[0-9a-f]{7,40}` (case-insensitive).

   For each match, substitute `old_sha → new_sha` in the body
   (full-SHA substring replace — careful not to match a prefix
   of an unrelated hash) and patch the comment body via the
   GitHub REST API:

   ```bash
   gh api -X PATCH "/repos/$OWNER/$REPO/pulls/comments/$comment_id" -f body="$rewritten_body"  # cli-friction: allow raw-gh-api — no MCP edit action exists for PR-review-comment bodies; pr_comments supports list/get/reply/resolve only
   ```

   Top-level PR comments live on a different REST endpoint
   (`/repos/$OWNER/$REPO/issues/comments/$id`); same `body`
   field. Walk both surfaces.

   If a SHA is referenced but does not appear in the
   `old_sha → new_sha` map, leave it untouched (it predates the
   groom and is still reachable) and log a warning.

6. If the PR body has a Job Story, preserve it unchanged.

After completing, mark all tasks done: `TaskUpdate(taskId=push_task, status="completed")`

## Common Scenarios

### Scenario 1: Review Comments Need Fixes

```bash
# Make the fix
vim file.py

# Create fixup targeting the original commit
git add file.py
git commit --fixup=$(git log --oneline | grep "original message" | cut -d' ' -f1)

# Squash before pushing
git rebase -i --autosquash $(git merge-base develop HEAD)

# Push
git push --force-with-lease
```

### Scenario 2: CI Blocks Fixup Commits

Many repos have CI checks that block merging if fixup commits exist:

```bash
# Squash all fixup commits
git rebase -i --autosquash $(git merge-base develop HEAD)

# The editor opens with fixup commits already positioned - just save and exit
git push --force-with-lease
```

### Scenario 3: Split One Commit Into Two

```bash
git rebase -i <base>
# Mark the commit as 'edit'
# When rebase stops:
git reset HEAD^           # Undo the commit, keep changes
git add -p                # Stage first logical change
git commit -m "First part"
git add .                 # Stage remaining changes
git commit -m "Second part"
git rebase --continue
```

### Scenario 4: Combine Multiple Commits

```bash
git rebase -i <base>
# Keep first commit as 'pick'
# Change subsequent commits to 'squash' or 'fixup'
# Save and edit the combined commit message
```

## Best Practices

1. **Atomic commits**: Each commit should represent one logical change
2. **Meaningful messages**: Follow project conventions (gitmoji, ticket refs, etc.)
3. **Test before pushing**: Ensure each commit in history passes CI individually
4. **Communicate**: If others are working on the branch, coordinate before force pushing
5. **Backup first**: Create a backup branch before complex rewrites:
   ```bash
   git branch backup-before-rewrite
   ```

## Commit Message Conventions

Follow project standards. Common patterns:
- Gitmoji: `PAY-123 Add new feature`
- Conventional: `feat(payments): add new feature [PAY-123]`

Limit title to 72 characters. Add body for complex changes.

## Troubleshooting

### Rebase Conflicts

When a rebase hits merge conflicts, the groom skill is responsible
for resolving them rather than aborting and asking the user.

**Detection:** Scripts output `CONFLICT_DETECTED` with structured
info (conflicted files, rebase HEAD). MCP tools return
`{"conflict": true, "conflicted_files": [...]}`.

**Resolution loop:**

1. Read each conflicted file with the Read tool
2. Examine the conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`)
3. Resolve by choosing the correct version or merging both sides
4. Write the resolved file with the Edit tool (remove all markers)
5. Stage resolved files: `git add <file>`
6. Continue: `git rebase --continue`
7. If new conflicts arise, repeat from step 1

**When to abort instead of resolving:**
- Conflicts span 5+ files with complex semantic changes
- The conflict indicates a fundamental structural divergence
  that requires the user's domain knowledge to resolve
- After 3 resolution rounds with recurring conflicts

In abort cases, run `git rebase --abort` and fall back to
Strategy B (soft reset) as documented below.

```bash
git rebase --abort
git reset --soft $(git merge-base develop HEAD)
git reset HEAD
# Recommit in clean atomic chunks
```

### Autosquash Fails on Cross-Commit Fixups

When a fixup commit modifies files that span multiple original commits
(e.g., service layer in commit A and mutation layer in commit B),
`--autosquash` places the fixup after one target but before the other.
This causes conflicts because the later commit's files don't exist yet
at that point in history.

**Symptom:** Rebase conflict immediately after autosquash reorders commits.

**Fix:** Abort and use Strategy B (soft reset) instead:

```bash
git rebase --abort
git reset --soft $(git merge-base develop HEAD)
git reset HEAD
# Recommit in clean atomic chunks
```

*Why?* Example: a fixup touching both `service.py` (commit 1)
and `mutations.py` (commit 3) failed autosquash. Strategy B resolved
it in one pass.

### exec Steps Leaving Staged Changes Halt Rebase

When using `exec` lines in an interactive rebase todo, each `exec` command
runs in the repo's working tree with the index from the previous step.
If an `exec git mv` stages a rename but does not commit it, the next
`exec` command (or the next `pick`) finds the index dirty and rebase halts:

```
error: cannot rebase: Your index contains uncommitted changes.
```

**Symptom:** Rebase stops mid-run on a commit that involves `git mv`.

**Fix:** Chain all operations for a single commit into **one `exec` line**
using `&&` so the index is clean before the next `pick`:

```
exec git mv old/path/A new/path/A && git mv old/path/B new/path/B && git commit --amend -F $WORKDIR/msgs/<sha>
```

Never use separate `exec git mv` lines for the same commit amendment.

### GIT_SEQUENCE_EDITOR file must be oldest-first

`git rebase -i` expects commits listed **oldest at the top, newest at the
bottom** — the opposite of `git log` default output (newest first).

**Symptom:** Immediate modify/delete conflict on files added in later commits
(e.g., `package.json deleted in HEAD and modified in <sha>`).

**Fix:** Reverse `git log` order when building the sequence file:

```bash
git log --oneline <base>..HEAD | tac  # tac reverses line order
```

Verify: the **first line** of the sequence file must be the **oldest** commit SHA.

### Stale SHAs in multi-pass rebases

After each rebase pass all commit SHAs change. A sequence file written before
pass 1 contains stale SHAs that will silently pick the wrong commits in pass 2.

**Symptom:** A commit gets the wrong message (e.g., Makefile commit gets the
Docker commit's name because the stale SHA pointed elsewhere).

**Fix:** Always run `git log --oneline <base>..HEAD` after each rebase pass
and use the fresh SHAs when writing the next sequence file.

### git-rebase-groom.sh Drops Commits on Autosquash

`git-rebase-groom.sh` uses a custom `GIT_SEQUENCE_EDITOR` that
replaces the rebase todo with the contents of
`$GROOM_SEQ_FILE`. If the sequence file
doesn't list ALL commits, the missing ones are dropped.

**Symptom:** After running `git-rebase-groom.sh`, only a subset
of commits remain in history.

**Fix:** For simple autosquash (no custom reordering), skip the
script entirely:

```bash
git autosquash-develop
```

Use `git-rebase-groom.sh` only when you need custom sequence
control (message rewrites, splits, reordering).

### Files Excluded by Global ~/.gitignore in Soft Reset

When using Strategy B (soft reset + recommit), files tracked in the
original branch may be ignored by the user's global `~/.gitignore`
(e.g. `.nvmrc`, `.DS_Store`). `git add <file>` silently skips them,
causing the commit to be incomplete.

**Symptom:** Script exits with error mid-run; a commit is missing
expected files that appear in the backup but not in the new history.

**Diagnose:**
```bash
git check-ignore -v <file>   # shows which gitignore rule is blocking
```

**Fix:** Use `git add -f` to force-add the file:
```bash
git add -f apps/web/.nvmrc
```

Add the `-f` flag to every `git add` call in the recommit script
for files that are in the global gitignore.

### `$()` Subshells Cause Permission Friction

When calling skill scripts, never wrap arguments in `$()` subshells:

```bash
# BAD — $() changes the effective command prefix, breaking allow rules
BASE=$(git merge-base develop HEAD)
${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh "$BASE"

# GOOD — pass branch name directly, script resolves merge-base internally
${CLAUDE_PLUGIN_ROOT}/skills/git/scripts/git-rebase-groom.sh develop
```

**Symptom:** Every invocation prompts for permission even though the
script path matches an existing `Bash(~/.claude/skills:*)` allow rule.

**Why?** `settings.local.json` allow rules match the command prefix.
`BASE=$(git merge-base develop HEAD) && script` has prefix `BASE=...`,
not `~/.claude/skills/...`. Even a standalone `git merge-base` before
the script is unnecessary friction — the script accepts branch names.

*Source:* Prior sessions: 3 consecutive user corrections to eliminate
`$()` from the grooming workflow.

### Recover from Bad Rewrite

```bash
# Find the previous HEAD position
git reflog

# Reset to before the rewrite
git reset --hard HEAD@{n}
```

## Integration with Other Skills

### Dev10x:git-commit-split

When the user asks to split a specific commit mid-session (e.g. "Split
<sha>"), invoke the `Dev10x:git-commit-split` skill rather than handling it inline.
`Dev10x:git-commit-split` provides the canonical workflow with dependency-order
guidance and commit message conventions.

```
User: "Split 835fc34"
-> Invoke Skill(Dev10x:git-commit-split) before proceeding
```

## Integration with PR Workflow

1. Create fixup commits as you address review comments
2. Reply to each comment with "Fixed in commit <sha>"
3. Before final push, squash all fixups: `git rebase -i --autosquash`
4. Force push to trigger fresh CI run
5. CI should now pass (no fixup commits blocking merge)
