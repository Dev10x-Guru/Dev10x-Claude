---
name: Dev10x:gh-pr-review
description: >
  Review a GitHub pull request and post findings with inline comments.
  Fetches PR diff, reads changed files, checks for interface impact,
  applies project review guidelines, and posts a COMMENT review to GitHub.
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

**Auto-advance:** Complete each step and immediately start the next.
Never pause between steps to ask "should I continue?".

**REQUIRED: Create tasks before ANY work.** Execute these
`TaskCreate` calls at startup:

1. `TaskCreate(subject="Fetch PR diff", activeForm="Fetching PR context")`
2. `TaskCreate(subject="Run spec compliance gate", activeForm="Checking spec compliance")`
3. `TaskCreate(subject="Review changes", activeForm="Reviewing changes")`
4. `TaskCreate(subject="Post findings", activeForm="Posting review")`

Set sequential dependencies: spec gate blocked by fetch, review
blocked by spec gate, post blocked by review.

No user decision gates — this skill runs fully automated once
invoked. All review decisions (what to flag, severity) are made by
applying `review-guidelines.md` and `review-checks-common.md`.

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

Before reading per-file context or drafting inline comments,
dispatch the `spec-reviewer` agent to confirm the PR diff matches
the linked ticket's acceptance criteria and the PR's Job Story.
Domain-level review (architecture, style, suggestions) is wasted
effort when scope is wrong or AC are unmet — surfacing that
early lets the reviewer post a single short-circuit comment
instead of a multi-page review against the wrong target.

**Skip Phase 0 when:**
- The PR has no linked ticket AND no Job Story
- The diff is purely additive infra (a new agent spec, a new
  reference doc) where scope is self-evident from the file path

**Pre-read inputs (controller side):** The diff and PR body are
already loaded in Step 2. Fetch the linked ticket body via the
appropriate tracker MCP (parse `Fixes: GH-N` / `TEAM-N` /
`JIRA-N` from the PR body or branch name) and inline it. Do
NOT instruct the agent to fetch the ticket itself — that
triggers permission prompts inside the subagent.

**Dispatch:**

```
Agent(
    subagent_type="spec-reviewer",
    description=f"Spec compliance check for PR #{N}",
    prompt="""Verify the following PR diff matches the linked
    ticket's acceptance criteria and Job Story.

    <ticket>
    {inlined ticket body + AC, or "NO_LINKED_TICKET" if none}
    </ticket>

    <pr_body>
    {inlined PR body — Job Story is the first paragraph}
    </pr_body>

    <diff>
    {inlined output of `gh pr diff N`}
    </diff>

    Follow the checklist in your spec. Return one paragraph per
    finding (AC ref / file:line / verdict).

    Report your final status as the LAST line of your output,
    with exactly one of these prefixes:

    - DONE                       — PASS
    - DONE_WITH_CONCERNS: <text> — PARTIAL (proceed but flag)
    - NEEDS_CONTEXT: <what>      — re-dispatch needed
    - BLOCKED: <verdict>: <reason> — FAIL_SCOPE / FAIL_MISSING /
                                     FAIL_OVER

    Do not write anything after the status line.""")
```

**Parse the trailing status line** and branch:

- `DONE` → continue to Step 3 (read changed files)
- `DONE_WITH_CONCERNS: <text>` → continue; record the concern as
  a top-of-summary note in the eventual review body
- `NEEDS_CONTEXT: <what>` → re-dispatch with the requested
  additional inline context once
- `BLOCKED: <verdict>: <reason>` → skip Steps 3–6, post a
  concise review whose body cites the verdict and asks the
  author to address the spec gap before quality review. Still
  hide obsolete summaries (Step 7) and post via Step 8.

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

**Independent of prior review comments.** Do NOT anchor on
whether surface bugs from previous cycles were fixed — evaluate
the PR's structural compliance from scratch.

Load project architecture rules:
- `CLAUDE.md` — coding style, patterns, SRP
- Project-specific `code-implementation.md` (if exists)
- `review-checks-common.md` § Architecture Checklist

Check each new or substantially modified file for:

| Signal | Violation | Severity |
|--------|-----------|----------|
| New endpoint/view with >50 lines | Missing service layer extraction | WARNING |
| View calling repository directly | Missing Service layer (View→Service→Repository) | WARNING |
| Inline dict with 4+ keys passed across boundaries | Missing DTO | INFO |
| Manual `request.data["field"]` parsing | Missing serializer/DTO validation | WARNING |
| Function/method >50 lines | SRP violation — extract | WARNING |

**Anti-pattern (anchoring bias):** When previous review comments
exist, the skill tends to check only whether those bugs were fixed
and declare the PR "solid". This step forces an independent
structural evaluation regardless of prior feedback.

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

**Skip Step 7 entirely on closed/merged PRs (GH-181 F7).** The
`minimizeComment` mutation only meaningfully affects the
reviewer's pane on open PRs; on merged PRs nobody reads it and
the call is a no-op. Closed/merged PR → jump straight to Step 8.

Before posting the new review on an **open** PR, minimize previous
Claude review summaries that are fully resolved (per
`review-guidelines.md` step 6):

1. Query review threads via GraphQL — check `isResolved` and group
   by `pullRequestReview.databaseId`
2. For each previous Claude review with a non-empty body:
   - ALL threads resolved → minimize with `OUTDATED` classifier
   - ANY thread unresolved → leave visible
   - No inline threads (summary-only) → minimize
3. Use `gh api graphql` with `minimizeComment` mutation:
   ```graphql
   mutation { minimizeComment(input: {
     subjectId: "<review_node_id>", classifier: OUTDATED
   }) { minimizedComment { isMinimized } } }
   ```

Skip this step on the first review (no previous summaries exist).

### Step 8: Post Review to GitHub

**Transport selection (GH-181 F3, F8).** Pick the transport based
on the PR state and diff size detected in Step 2:

| Condition | Transport |
|---|---|
| PR is OPEN AND diff fits in `gh pr diff` (≤ ~5,000 LOC, no 406) | A. `gh api .../pulls/{N}/reviews` with inline comments |
| PR is MERGED / CLOSED, OR `oversize_diff=true`, OR inline anchors infeasible | B. Bot top-level comment via `~/.claude/tools/gh-bot-comment.py` |

#### A. Standard review payload (open PR, normal diff)

Use the Write tool to create the review JSON, then post via `gh api --input`:

1. **MUST** create the unique temp path via the MCP tool — the shell
   `mktmp.sh` is a fallback for when the MCP server is unavailable.
   Reaching for the shell first is the regression GH-181 F8 closes:

   ```
   mcp__plugin_Dev10x_cli__mktmp(namespace="git", prefix="pr-review", ext=".json")
   ```

   Shell fallback (only when MCP unavailable):
   `/tmp/Dev10x/bin/mktmp.sh git pr-review .json`

2. Write the review payload to the returned path:
```json
{
  "event": "COMMENT",
  "commit_id": "{HEAD_SHA}",
  "body": "## Review Summary\n\n...",
  "comments": [
    {
      "path": "src/file.py",
      "line": 42,
      "body": "Issue description\n\n```suggestion\nfix\n```"
    }
  ]
}
```

3. Post the review:
```bash
gh api repos/{owner}/{repo}/pulls/{N}/reviews \
  --method POST --input <unique-path>
```

> **Do not use `cat <<'JSON' | gh api --input -`** — the heredoc is
> blocked by `validate-bash-security.py`. Always Write to a file first.

**Rules**:
- Always use `"event": "COMMENT"` — never REQUEST_CHANGES or APPROVE
- Include `commit_id` from the PR's latest commit
- Inline comments must reference lines that exist in the PR diff

#### B. Bot top-level comment (merged PR / oversize diff)

**Prerequisites.** Transport B requires two user-provided
resources outside this plugin:

- `~/.claude/tools/gh-bot-comment.py` — user-installed script
  that posts comments under a GitHub App identity. Not bundled
  with Dev10x. Users wire it up alongside their own GitHub App
  credentials.
- `~/.claude/Dev10x/github-bot/github-app.yaml` — App identity
  config (App ID, private-key path, installation ID). Users
  create this file when setting up the bot. Step 1 below checks
  `enabled: true` before selecting Transport B.

If either is missing, Transport B falls back to Transport A even
for merged or oversize PRs. The fallback posts under the user's
own GitHub identity rather than the App's — document the chosen
identity in the eventual review summary.

The `pulls/{N}/reviews` endpoint requires every entry in
`comments[]` to anchor on a line that exists in the diff. On
merged PRs the diff is finalized and inline anchors still work,
but the bot-identity transport is preferred because it preserves
review attribution after merge. For oversize diffs, inline
anchors are unavailable (no diff fetched). In both cases,
restructure the review into a single top-level issue comment
posted as the GitHub App.

1. **Detect bot config:** `Read(file_path="~/.claude/Dev10x/github-bot/github-app.yaml")`.
   If `enabled: true`, proceed; otherwise fall back to transport A
   (best-effort with whatever inline anchors are available).

2. **Restructure the payload:** convert each `comments[]` entry
   into a quoted `file:line` block inside the body:

   ```markdown
   ## Review Summary

   <summary text>

   ### Findings

   **`src/file.py:42`** — Issue description

   ```suggestion
   fix
   ```

   **`src/other.py:101`** — …
   ```

3. **Create the body file** via the MCP tool (MUST, not shell):
   ```
   mcp__plugin_Dev10x_cli__mktmp(namespace="git", prefix="pr-review-body", ext=".md")
   ```
   Write the restructured body to the returned path.

4. **Post via the bot tool:**
   ```bash
   ~/.claude/tools/gh-bot-comment.py OWNER/REPO PR_NUMBER <body-path>
   ```

   This posts a top-level issue comment using the GitHub App
   identity configured in `github-app.yaml`. The bot transport
   does NOT support inline review threads — every finding must
   be in the body with explicit `path:line` references.

5. Report the resulting comment URL to the user in Step 9.

### Step 9: Report to User

Confirm what was posted:
- Link to the review on GitHub
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
