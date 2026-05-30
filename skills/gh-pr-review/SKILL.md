---
name: Dev10x:gh-pr-review
description: >
  Review a GitHub pull request and post findings with inline comments.
  Fetches PR diff, reads changed files, checks for interface impact,
  applies project review guidelines, and posts a review to GitHub.
  Supports Draft (PENDING) and submitted review modes via Step 8a gate.
  TRIGGER when: reviewing an external PR and posting review comments.
  DO NOT TRIGGER when: reviewing own branch changes before PR creation
  (use Dev10x:review), or PR does not exist yet.
user-invocable: true
invocation-name: Dev10x:gh-pr-review
allowed-tools:
  - Bash(gh:*)
  - Bash(/tmp/Dev10x/bin/mktmp.sh:*)
  - Bash(~/.claude/tools/gh-bot-comment.py:*)
  - Write(/tmp/Dev10x/git/**)
  - mcp__plugin_Dev10x_cli__pr_detect
  - mcp__plugin_Dev10x_cli__mktmp
  - AskUserQuestion
---

# GitHub PR Review

Review a pull request on GitHub and post findings as a review with
inline comments.

## Arguments

Accepts one of:
- **PR URL**: `https://github.com/owner/repo/pull/NUMBER`
- **PR number**: `1293` (uses current repo)

## When to Use

- Reviewing someone else's PR
- Reviewing any PR where you want findings posted to GitHub
- When asked to "review PR #N" or given a PR URL

**Not for self-review** — use `Dev10x:review` to review your own
branch before creating a PR.

## Orchestration

This skill follows `references/task-orchestration.md` patterns
(Tier: Standard).

**Auto-advance:** Complete each step and immediately start the next — no checkpoints under adaptive friction.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Fetch PR diff", activeForm="Fetching PR context")`
2. `TaskCreate(subject="Run spec compliance gate", activeForm="Checking spec compliance")`
3. `TaskCreate(subject="Review changes", activeForm="Reviewing changes")`
4. `TaskCreate(subject="Choose draft or submit", activeForm="Selecting review mode")`
5. `TaskCreate(subject="Post findings", activeForm="Posting review")`

Set sequential dependencies: spec gate blocked by fetch, review
blocked by spec gate, draft gate blocked by review, post blocked
by draft gate.

No user decision gates before Step 8a. All review decisions (what
to flag, severity) are made by applying `review-guidelines.md` and
`review-checks-common.md`. The Step 8a gate is the single user
interaction point.

## Workflow

### Step 1: Parse PR Reference

Extract owner, repo, and PR number from the argument. If only a
number is given, use the current git remote origin.

### Step 2: Gather PR Context

**REQUIRED first call:** `mcp__plugin_Dev10x_cli__pr_detect` to
resolve PR number, repo, state, base/head refs, and merge status
in one structured response (GH-181 F4). Raw `gh pr view --json`
is fallback only when the MCP tool is unavailable.

Then run in parallel:
1. `mcp__plugin_Dev10x_cli__pr_detect` (state, refs, merge state, labels)
2. `gh pr diff {N}` — full diff
3. `gh pr view {N} --json comments` — existing bot/human comments
4. `gh api repos/{owner}/{repo}/pulls/{N}/reviews` — existing reviews
5. `gh api repos/{owner}/{repo}/pulls/{N}/comments` — inline comments

**Why all 5?** Avoids duplicating feedback from previous review cycles
(per `review-guidelines.md` — "NEVER repeat feedback from previous
review cycles").

**Oversize-diff fallback (GH-181 F5).** GitHub's `gh pr diff` fails
with `HTTP 406: Sorry, the diff exceeded the maximum number of
lines (20000)` for very large PRs. When this happens:

1. Fall back to file-list-only context:
   `gh pr view {N} --json files,additions,deletions,changedFiles`
2. Read changed files individually at the PR head SHA via
   `gh api repos/{owner}/{repo}/contents/{path}?ref={head_sha}`
   (or from local checkout if present — but DO NOT `git checkout`
   the PR branch; see Step 3 REQUIRED).
3. Record `oversize_diff=true` so Step 8 selects the bot-comment
   transport (inline review threads anchor on diff hunks, which
   are unavailable).

### Step 2b: Phase 0 — Spec Compliance Gate (GH-69)

Dispatch the `spec-reviewer` agent to confirm the PR diff matches
the linked ticket's AC and the PR's Job Story before drafting
inline comments. Domain-level review is wasted effort when scope
is wrong.

See [`references/spec-gate.md`](references/spec-gate.md) for
skip conditions, the controller-side pre-read pattern, the
agent dispatch prompt, and how to branch on the trailing
status line (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT /
BLOCKED).

### Step 3: Read Changed Files

For each file in the PR's file list, use the Read tool to read the
file at the current HEAD of the PR's base branch. Compare with the
diff to understand the full context.

**REQUIRED: do NOT run `git checkout` on the PR branch (GH-181
F2).** If the PR branch is not checked out locally, the diff from
Step 2 is sufficient for review. When you need a file's full text
at the PR head, fetch it via
`gh api repos/{owner}/{repo}/contents/{path}?ref={head_sha}` (or
the equivalent `pr_detect` head SHA) — never disrupt the working
tree by checking out the PR branch. Checking out the branch risks
overwriting in-flight worktree changes and is a documented
regression.

### Step 4: Impact Analysis

**REQUIRED — main agent runs the grep pass (GH-181 F6).** Subagents
may help, but the main agent must perform (or summarize subagent
output of) the grep-for-callers sweep and include the findings in
the draft review's impact-analysis section. A skipped or
silently-delegated grep pass is a Step 4 violation.

For changed interfaces (renamed methods, changed signatures, modified
DTOs):
- Grep for all callers/consumers of the changed interface
- Verify the PR updates all call sites
- Flag any missed references
- Summarize the grep results in the draft review body (one bullet
  per affected call site or "no other callers found").

### Step 4b: Architecture Evaluation (GH-916)

**Independent of prior review comments.** Evaluate the PR's
structural compliance from scratch — do NOT anchor on whether
surface bugs from previous cycles were fixed.

See [`references/architecture-checklist.md`](references/architecture-checklist.md)
for the rules to load, the per-file signal/violation/severity
table, and the anchoring-bias anti-pattern.

### Step 4c: Cross-Consumer Behavioural-Reuse Check (GH-290)

Catches PRs that reuse an existing data structure when a sibling
repository (typically a frontend) gates feature visibility on
row presence.

**Trigger** — fire ONLY when the diff dereferences an existing
relation (model `related_name` / FK / OneToOne) with no sibling
`migrations/*.py` diff in the same PR. Skip otherwise; innocuous
resolver additions should not trigger cross-repo grep on every
review.

**How to run** — see
`references/review-checks/cross-consumer-reuse.md` for the
sibling-repo config schema (`.claude/Dev10x/sibling-repos.yaml`),
grep patterns (`!!<relation>`, `<relation>.length > 0`, etc.),
severity matrix, and silent-skip degradation rule.

### Step 5: Apply Review Guidelines

**REQUIRED — Read the reference files (GH-181 F1).** Skipping
these because "I know the rules" is the regression that
prompted this requirement. Apply the gate to every drafted
inline comment, not just to a sample.

1. `Read(file_path=".../references/review-guidelines.md")` — workflow,
   threads, summaries
2. `Read(file_path=".../references/review-checks-common.md")` —
   false positive prevention
3. Load domain-specific agents from `.claude/agents/` for the
   changed file types

Apply the **False Positive Prevention Gate** (defined in
`review-checks-common.md`) before drafting any inline comment:
1. Does this violate a documented rule? (No rule = preference)
2. Does this contradict an established codebase pattern?
3. Quality improvement or just preference?

If the gate fails any criterion, do not file the comment.

### Step 6: Draft Review

Compose:
- **Summary body**: High-level assessment, positives, cross-cutting
  concerns
- **Inline comments**: One per substantive issue, with file path and
  line number. Use GitHub suggestion syntax for committable fixes:
  ````
  ```suggestion
  fixed code here
  ```
  ````

### Step 7: Hide Obsolete Review Summaries

**Skip on closed/merged PRs (GH-181 F7) — jump straight to
Step 8.** On open PRs, minimize previous Claude review summaries
that are fully resolved.

See [`references/hide-obsolete.md`](references/hide-obsolete.md)
for the open-vs-merged skip rule, the GraphQL thread query
pattern, the resolved/unresolved/summary-only classification
matrix, and the `minimizeComment` mutation.

### Step 8: Post Review to GitHub

**Transport selection (GH-181 F3, F8).** Two transports exist:

- **A.** `gh api .../pulls/{N}/reviews` with inline comments —
  for OPEN PRs where the diff fits (≤ ~5,000 LOC, no 406).
- **B.** Bot top-level comment via `~/.claude/tools/gh-bot-comment.py`
  — for MERGED / CLOSED PRs, oversize diffs, or when inline
  anchors are infeasible.

See [`references/transport-selection.md`](references/transport-selection.md)
for the full selection matrix, Transport A payload schema + post
recipe (MCP-first mktmp, no heredocs), Transport B prerequisites
(bot config detection, GitHub App identity), and the
body-rewriting recipe that converts inline comments into a
single top-level findings block.

**Transport B bypasses Step 8a** — bot comments have no PENDING
state. Proceed directly to posting and then Step 9.

### Step 8a: Draft vs Submit Gate (GH-319)

**Only for Transport A (open PR, normal diff).** Before writing
the review JSON and posting, decide the `event` value.

**Intent detection:** Scan the original invocation argument for
draft-intent phrases:
- "draft", "hold", "before submitting", "leave as draft",
  "let me review", "let me submit", "do not submit", "don't submit"

If any phrase matches, default to **Draft (PENDING)**.
Otherwise default to **Submit as COMMENT**.

Also check: if the current user is the PR author (compare
`pr_detect` `author` field with `gh api /user` login), bias the
default toward Draft and surface a note that APPROVE is
unavailable to PR authors.

**REQUIRED: Call `AskUserQuestion`** (do NOT use plain text).

Options:
- **Draft (PENDING)** — Post without `event`; only you see it until
  you finish on GitHub. *[set as default when draft-intent detected]*
- **Submit as COMMENT** — Post and publish immediately as a
  comment. *[default otherwise]*
- **Submit as REQUEST_CHANGES** — Post and publish; blocks merge.
  Surface a warning before selecting.
- **Submit as APPROVE** — Post and publish as approval.
  Disabled when reviewer is the PR author.

**After the gate:**
- Draft (PENDING): omit `event` from the payload; record
  `review_state=PENDING` for Step 9.
- Submit as COMMENT: set `"event": "COMMENT"`; record
  `review_state=SUBMITTED`.
- Submit as REQUEST_CHANGES: set `"event": "REQUEST_CHANGES"`;
  record `review_state=SUBMITTED`.
- Submit as APPROVE: set `"event": "APPROVE"`; record
  `review_state=SUBMITTED`.

### Step 9: Report to User

Branch on `review_state`:

**`PENDING` (draft posted):**
- "Draft review posted (only you can see it). Open the
  Files changed tab on the PR and click 'Finish your review'
  to submit."
- Include `html_url` from the API response.
- Count of inline comments queued in the draft.

**`SUBMITTED`:**
- Link to the review on GitHub (`html_url`)
- Count of inline comments
- Brief summary of findings

## Review Principles

From `review-guidelines.md` and `review-checks-common.md`:

- Focus on substance: bugs, security, architecture, performance
- Trust automated tools (Black, Ruff) for formatting
- Review only changed lines; pre-existing issues are out of scope
- Verify claims by reading actual code, not just diff context
- Check for fixes in later commits before flagging
- One summary per review cycle
- Positive validation is valuable — clean code deserves acknowledgment

## Integration

```
Dev10x:gh-pr-review
├─ Standalone review of any GitHub PR
└─ Posts findings directly to GitHub
```

Complements:
- `Dev10x:review` — self-review before PR creation (no GitHub posting)
- `Dev10x:gh-pr-respond` — respond to review comments on YOUR PR
- `Dev10x:gh-pr-triage` — validate a single review comment
