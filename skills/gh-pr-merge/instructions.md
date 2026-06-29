# Merge PR (Instructions)

## Orchestration

This skill follows `references/task-orchestration.md` patterns.
Create a task at invocation, mark completed when done:

**REQUIRED: Create a task at invocation.** Execute at startup:

1. `TaskCreate(subject="Merge PR", activeForm="Merging PR")`

Mark completed when done: `TaskUpdate(taskId, status="completed")`

## Overview

Pre-merge validation gate that checks 8 conditions before
executing `gh pr merge`. Prevents premature merges like PR #633
(merged with 7 unaddressed review comments) and PRs #690-692
(merged with unaddressed top-level automated review comments).

## Merge Strategy Resolution

The merge strategy is resolved using the config resolution order
(see `references/config-resolution.md`):

1. **Global with repo matching** — read
   `<Dev10x config>/settings-pr-merge.yaml`, match current
   repo against `projects[].match` globs
2. **Default** — `rebase`

Rationale for the `rebase` default: commits authored through this
plugin already follow gitmoji + ticket + JTBD conventions enforced
by `Dev10x:git-commit`, and `Dev10x:git-groom` produces a curated
linear history before merge. Squashing erases that structure and
breaks per-commit references in PR review threads. Rebase preserves
the curated commits as-is.

**Migration note for existing users:** If a project previously relied
on the implicit `squash` default, set `strategy: squash` explicitly
in `<Dev10x config>/settings-pr-merge.yaml` for that repo's
`projects[].match` entry. No behavior change for projects that
already declared `strategy:` explicitly.

### Config file format

**Global format** (preferred — one file for all repos):
```yaml
# <Dev10x config>/settings-pr-merge.yaml
projects:
  - match: "Dev10x-Guru/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
  - match: "example-org/*"
    strategy: rebase
    delete_branch: true
    solo_maintainer: true
  - match: "legacy-org/*"
    strategy: squash   # explicit opt-in to historical default
    delete_branch: true
```

All fields are optional. Defaults:
- `strategy`: `rebase`
- `delete_branch`: `true`
- `solo_maintainer`: `false`

## Self-Check Before Pre-Merge Validation

**REQUIRED — call `TaskList` now.** Verify the 8 pre-merge subtasks
exist under the merge task. If fewer are present, create the missing
ones before proceeding. Do NOT shortcut to `gh pr merge` based on a
single `gh pr view` JSON read — that is the regression this check
exists to catch (GH-112).

**Unskippable on every invocation (GH-253):** The `TaskList` call
above runs ONCE per skill invocation, at Step 1, before any check
or `gh pr merge` execution. It is not optional and it is not
satisfied by a prior invocation's call. If you proceed past Step 1
without calling `TaskList` in this invocation, HALT with the
message: "gh-pr-merge Step 1 self-check skipped — restart from
Step 1." Do not jump to Step 5 (`gh pr merge` / `merge_pr`) based
on the agent's recollection that "the checks just passed" — those
checks belong to a sibling skill's context, not this one.

**Re-invocation contract:** Every invocation of `Dev10x:gh-pr-merge`
re-runs the full skill body from Step 1, including all 8 pre-merge
checks. Check results from a prior `Dev10x:gh-pr-monitor` phase,
prior `Dev10x:verify-acc-dod` run, or earlier invocation of this
same skill are NOT reusable. CI state, review comments, draft
toggles, and force-push state can drift between invocations — the
8 checks exist precisely to detect that drift.

**"Re-run the skill" expansion:** When the supervisor says
"execute the whole skill again", "re-run the skill", "run it once
more", or any equivalent phrasing, treat that as a fresh invocation
starting from Step 1 of this body — NOT as "resume from the last
unfinished step" or "skip to the merge command". The full skill
body, including all 8 checks, runs every time.

Adaptive friction does NOT waive this skill body. The friction level
only governs `AskUserQuestion` gates marked `(Recommended)`; the 8
checks below still run. See `references/friction-levels.md` §
"Adaptive does not waive skill bodies".

## Pre-Merge Validation Checks

Run ALL 8 checks before merging. Report results as a checklist.
If ANY check fails, refuse to merge and report which failed.

### Check 1: No unresolved review threads

Query unresolved review threads via the MCP wrapper — never raw
`gh api graphql` (GH-598). The wrapper runs the `reviewThreads`
GraphQL query and returns only the unresolved threads:

```
mcp__plugin_Dev10x_cli__unresolved_threads(repo="OWNER/REPO", pr_number=NUMBER)
```

`unresolved_threads` requires an explicit `repo` (no CWD default).
If it times out, retry once before falling back. Each returned
thread is unresolved; report the count and first comment of each.

### Check 1b: No unaddressed top-level PR comments (GH-698)

**REQUIRED:** This check MUST run after Check 1. Top-level PR
comments are invisible to the `reviewThreads` GraphQL query —
skipping this check silently misses automated review findings
(GH-728). Do NOT proceed to Check 2 until this script runs.

Top-level PR comments (posted via `gh pr comment`, not inline
review threads) are invisible to Check 1's `reviewThreads`
query. Automated reviewers (claude-review, hygiene-review)
post findings as top-level comments with severity markers.

```bash
${CLAUDE_PLUGIN_ROOT}/skills/gh-pr-merge/scripts/check-top-level-comments.sh \
  OWNER REPO NUMBER
```

The script returns a JSON array of unaddressed findings (empty
array = pass).

If any automated review comments contain unaddressed severity
markers (`REQUIRED`, `CRITICAL`, `BLOCKING`), report the count
and first line of each. A comment is considered "addressed" if
a subsequent comment replies to it (contains `Re:` or quotes
the finding).

**Heuristic for addressed comments:** Check if any later
comment in the thread references the automated comment's ID
or quotes its content. If no reply exists, the finding is
unaddressed.

### Check 1c: No unaddressed inline review comments (GH-760)

Inline review comments posted via `pulls/{n}/comments` are
invisible to both Check 1 (GraphQL `reviewThreads`) and
Check 1b (`issueComments`). Query them via the MCP wrapper —
never raw `gh api .../pulls/.../comments` (GH-598):

```
mcp__plugin_Dev10x_cli__pr_comments(pr_number=NUMBER, action="list", unresolved_only=true)
```

Filter for bot users with unaddressed severity markers
(`CRITICAL`, `BLOCKING`, `REQUIRED`). A comment is
addressed if a reply exists (same `in_reply_to_id`).
If unaddressed findings remain, report them and block
merge.

### Check 2: CI checks passing

```bash
gh pr checks NUMBER --json name,state,bucket
```

All checks must have `bucket` of `pass` — including checks
that are not required by branch protection. No checks may be
`PENDING` or `IN_PROGRESS`. Report any failing or pending
checks by name.

`gh-pr-merge` MUST NOT proceed silently past any `PENDING`,
`IN_PROGRESS`, or `bucket: fail` state. The default response
is to stay in the fix-and-monitor loop — not to ask the user.
The user is only consulted when all automated options have
been exhausted or the failure looks unrelated to the PR.

**Pending CI delegation (GH-775, GH-955):** If any check is
`PENDING` or `IN_PROGRESS`, do NOT poll inline with `sleep`
+ `gh pr checks` and do NOT ask the user. Instead, delegate
to `Skill(Dev10x:gh-pr-monitor)` to wait for CI to complete,
then retry the merge validation from Check 1. The monitor
skill handles CI polling reliably; inline sleep loops bypass
these guardrails. A pending check's verdict is by definition
unknown — waiting is the only correct behavior.

**Code-failure auto-fix loop (GH-955):** If a check has
`bucket: fail` and the failure looks caused by the PR's own
changes (e.g., lint, type, test, coverage, formatting), do
NOT ask the user. Delegate to `Skill(Dev10x:gh-pr-monitor)` —
its Phase 1 "CI Failure Handling" table maps each failure
type to a fixup strategy (format, type annotations, test
fixes, etc.). The monitor creates fixup commits, pushes,
and re-checks until CI turns green. Retry the merge
validation from Check 1 after the monitor returns.

Only escalate to `AskUserQuestion` when:

1. The failure has exhausted the monitor's fix attempts
   (e.g., 5+ rounds of fixup + re-check with the same check
   still failing), OR
2. The failure matches the infrastructure signals below
   (non-code cause — user judgement required to decide
   whether to merge despite the infra outage).

**Infrastructure failure override (GH-730, ALWAYS_ASK):**
When a check fails with a clear infrastructure cause — the
failure is not the PR's fault and no fixup will resolve it —
fire the user-confirmation gate. Signals include:

- "Credit balance is too low" (API billing / quota outage)
- "OIDC token validation" (auth handshake failure)
- "Resource not accessible by integration" (permissions)
- Repeated identical failures after fixup attempts
  (monitor exhaustion)

Never auto-classify without evidence — if uncertain whether
the failure is code or infra, default to the auto-fix loop
above (safer to attempt a fix than to ask the user
prematurely).

**REQUIRED: Call `AskUserQuestion`** in this escalation path:

- Question: "CI check `{check-name}` failed due to what
  looks like an infrastructure issue (`{error-summary}`)
  and the auto-fix loop cannot resolve it. Merge anyway,
  or wait?"
- Options:
  - **Wait (Recommended)** — re-invoke
    `Skill(Dev10x:gh-pr-monitor)` to retry CI, then retry
    merge validation from Check 1
  - **Merge anyway** — user MUST supply a reason (free text
    via the `Other` notes field). Record the reason in the
    skill's task metadata
    (`TaskUpdate(taskId, metadata={"merge_override_reason":
    "<user text>", "override_check": "<check-name>",
    "override_state": "<state>"})`) so `Dev10x:skill-audit`
    can surface override patterns later.
  - **Abort** — cancel merge.

The gate fires regardless of `friction_level` or
`active_modes` — `solo-maintainer adaptive` governs pacing
between skills, it does NOT authorize silent merges past
unresolved CI signal. The narrow scope (only after auto-fix
is exhausted or the failure is clearly infra) keeps the
user out of the loop for routine code fixes while still
requiring human judgement for cases where the agent cannot
safely decide.

### Checks 3, 4, 7: Draft / mergeable / approval (one `pr_get` call)

Raw `gh pr view` is hook-blocked and routes to the MCP wrapper.
`pr_get` now exposes `isDraft`, `mergeable`, `reviewDecision`, and
`reviewRequests` (GH-668), so a single call satisfies Checks 3, 4,
and 7 — read each field from the one response:

```
mcp__plugin_Dev10x_cli__pr_get(number=NUMBER, repo="OWNER/REPO")
```

### Check 3: PR is not in draft

Read `isDraft` from the `pr_get` response. If `isDraft` is `true`,
report that the PR must be marked ready before merging.

### Check 4: No merge conflicts

Read `mergeable` from the `pr_get` response. The field must be
`MERGEABLE`. If `CONFLICTING`, report that merge conflicts must be
resolved first.

### Check 5: Working copy is clean

```bash
git status --porcelain
```

If output is non-empty, report uncommitted changes that must
be committed or stashed before merging.

### Check 6: No fixup/squash commits remaining

```bash
git log --oneline origin/develop..HEAD
```

Scan commit subjects for `fixup!` or `squash!` prefixes.
If any exist, report that commit history must be groomed
first (via `Dev10x:git-groom`).

### Check 7: Review approval

Read `reviewDecision` from the `pr_get` response (same call as
Checks 3/4). Check that `reviewDecision` is `APPROVED`.

**Solo-maintainer override:** If `solo_maintainer: true` in
config, skip this check entirely. Solo maintainers do not
require external approval.

## Execution Flow

### Step 1: Detect PR

Detect the current PR from the branch name via the MCP wrapper
(raw `gh pr view` is hook-blocked):

```
mcp__plugin_Dev10x_cli__pr_detect(arg="")
```

It returns `PR_NUMBER`, `REPO`, `PR_URL`, and `BRANCH`. If no PR
exists for the current branch, report and stop. (The base branch,
if needed, is available from `pr_get`'s `baseRefName`.)

### Step 2: Load merge strategy config

Read the per-project config file. If it does not exist, use
defaults (`strategy: rebase`, `delete_branch: true`,
`solo_maintainer: false`).

### Step 3: Run all 8 validation checks

**Comment-check ordering (GH-462 F3):** Checks 1, 1b, and
1c fetch comment state that is time-sensitive — automated
review bots continue posting comments during the CI window,
so comment state read before CI settles is stale. Run
Checks 2–7 first (CI, draft, mergeable, working copy,
fixup, approval). Only after Check 2 confirms CI is green
(all checks `pass`) re-fetch and run Checks 1, 1b, and 1c
as a final gate immediately before Step 5 merge. This
eliminates the race where a bot posts a REQUIRED finding
after the comment check but before the merge.

Run non-comment checks in parallel where possible (Check 2 uses
`gh pr checks`, Checks 3/4/7 share one `pr_get` MCP call, and
Checks 5/6 use `git`). **Check 1b MUST be run as a
separate step after Check 1** — it calls
`check-top-level-comments.sh` and is NOT part of the
GraphQL batch (GH-728). Collect all results before
reporting.

### Step 4: Report validation results

Present results as a checklist:

```
## Pre-Merge Validation

- [x] No unresolved review threads (0 unresolved)
- [x] No unaddressed automated review comments (0 found)
- [x] CI checks passing (12/12 green)
- [x] PR is not in draft
- [x] No merge conflicts (MERGEABLE)
- [x] Working copy is clean
- [x] No fixup/squash commits (8 clean commits)
- [x] Review approved (or solo-maintainer override)
```

If any check fails, show `[ ]` with failure details:

```
- [ ] CI checks passing (2 failing: lint, type-check)
```

### Step 5: Merge or refuse

**All checks pass:** Execute merge via the MCP tool (GH-232):

```
mcp__plugin_Dev10x_cli__merge_pr(
    pr_number=NUMBER,
    strategy="rebase",        # or "squash" / "merge" per config
    delete_branch=True,       # or False per config
    repo="OWNER/REPO",        # auto-detected if omitted
)
```

The `admin` and `auto` parameters default to `false` here — a
normal merge never sets them. They are set ONLY by the
required-review block override below, and only with explicit
user confirmation.

The MCP tool wraps `gh pr merge` inside the MCP server's
subprocess, so the PreToolUse hook that blocks raw `gh pr
merge` Bash invocations does not apply. This is the only
authorized way to execute the merge — do NOT fall back to a
raw `gh pr merge` invocation or any caller-level env-bypass.
Hook overrides for transient MCP unavailability live in the
hook layer (see `.claude/rules/hook-patterns.md`), not at the
skill caller.

The tool returns `{pr_number, url, strategy, branch_deleted,
admin, auto, repo}` on success and `{error: "..."}` on failure.

**Worktree safety (GH-773):** The tool always passes
`--repo OWNER/REPO` to `gh pr merge` (auto-detected when
`repo` is omitted) so it never tries to check out the base
branch locally — required when the base branch is already
checked out in another worktree.

**MCP unavailable fallback:** If the MCP server is
disconnected (`merge_pr` listed as "no longer available" in
system-reminders), STOP and ask the user to reconnect via
`/mcp` or restart the session. Raw `gh pr merge` is blocked
and the SKIP env-var prefix is not the documented contract.

**Required-review block override (GH-733, ALWAYS_ASK):** When
Checks 1–7 pass but the merge cannot land because the PR is
`BLOCKED` by a required-review branch-protection rule the
current account cannot satisfy, `merge_pr` returns an error
containing "base branch policy prohibits the merge" (and `gh`
advises adding `--admin` or `--auto`). This is the canonical
solo-maintainer case — GitHub forbids self-approval, so the
PR can never reach `reviewDecision: APPROVED` on its own. It
is NOT a check failure to route around: the 7 non-approval
checks already passed, and approval (Check 7) is the only
unsatisfiable gate.

Fire this gate **only when `solo_maintainer: true`** in config.
Without solo-maintainer mode, a `BLOCKED` PR means a real
reviewer still owes an approval — do NOT offer an admin bypass;
report the block and stop.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).
This gate is `ALWAYS_ASK` — it fires at every friction level
including `adaptive`+`solo-maintainer`, mirroring the Check-2
infrastructure override. Auto-merging with admin privileges
silently would defeat the gate's purpose.

- Question: "PR #NUMBER passed all checks but is BLOCKED by a
  required-review rule you cannot self-approve. Merge with
  administrator privileges, enable auto-merge, or abort?"
- Options:
  - **Merge with admin override (Recommended)** — re-call
    `merge_pr(pr_number=NUMBER, strategy="...", admin=true,
    repo="OWNER/REPO")`. Record the reason in task metadata:
    `TaskUpdate(taskId, metadata={"merge_override_reason":
    "solo-maintainer required-review block",
    "override_check": "branch-protection",
    "override_state": "BLOCKED"})` so `Dev10x:skill-audit`
    can surface override patterns later.
  - **Enable auto-merge** — re-call
    `merge_pr(pr_number=NUMBER, strategy="...", auto=true,
    repo="OWNER/REPO")`. GitHub queues the merge and lands it
    once branch-protection requirements are met; nothing merges
    immediately. Use when a reviewer is expected to approve
    later.
  - **Abort** — leave the PR open.

Never set `admin=true` or `auto=true` autonomously — only the
user may authorize either path through this gate. The flags
exist so the sanctioned MCP path can complete the merge
instead of forcing a raw `gh api .../merge` admin bypass that
skips the entire 8-check gate.

**Any check fails:** Do NOT merge. Report which checks failed
and what action is needed to resolve each one. Suggest the
appropriate skill for remediation:

| Failed check | Remediation |
|-------------|-------------|
| Unresolved threads | `Dev10x:gh-pr-respond` |
| Unaddressed automated comments | Review and address findings |
| CI failing | `Dev10x:gh-pr-monitor` |
| Still in draft | `gh pr ready` |
| Merge conflicts | Rebase onto base branch |
| Dirty working copy | `Dev10x:git-commit` |
| Fixup commits | `Dev10x:git-groom` |
| No approval | Request review |

### Step 6: Confirm merge

After successful merge, report:

```
PR #NUMBER merged via STRATEGY into BASE_BRANCH.
Remote branch deleted: yes/no
```

## Auto-Advance Behavior

This skill is designed to auto-advance in shipping pipelines —
**no checkpoints under adaptive friction**. After a successful
merge, the calling skill proceeds immediately to the next step
(typically acceptance criteria verification). There is NO
confirmation gate after merge: a trailing "PR merged — ready to
verify acceptance?" is a checkpoint and is forbidden under
adaptive friction. The merge is a step in the no-checkpoints
shipping sequence, not a natural stopping point.

If merge fails (e.g., branch protection rules), report the
error and let the calling skill decide how to proceed. A
genuine merge failure is a hard blocker, not a checkpoint —
treat it accordingly.

The ALWAYS_ASK "merge anyway" override (Check 2 failure path)
is the only documented in-skill pause, and only fires when the
auto-fix loop is exhausted. See `references/friction-levels.md`
§ "No checkpoints" rule for the canonical definition.

## Important Notes

- Never merge without running ALL 8 checks first
- Never bypass checks even if "it looks fine" — any `PENDING`,
  `IN_PROGRESS`, or `FAILURE` (required or not) blocks the
  merge. Check 2 handles these by delegating to
  `Dev10x:gh-pr-monitor` (pending → wait; code failure →
  fixup + re-check). The ALWAYS_ASK gate (GH-955, GH-730)
  only fires when the auto-fix loop is exhausted or the
  failure is clearly infrastructure-related. All
  "Merge anyway" overrides require explicit user
  confirmation via `AskUserQuestion` with a recorded reason.
- The solo-maintainer override only skips check 8 (approval),
  not the other 7 checks
- This skill must NOT be called from background agents
  (`Dev10x:gh-pr-monitor` explicitly forbids merge operations)
- Always use `gh pr merge` (not `git merge`) to ensure GitHub
  records the merge event properly
